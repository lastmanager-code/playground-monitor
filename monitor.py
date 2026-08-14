import os
import time
import re
import random
import requests
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from dotenv import load_dotenv

# --- 1. 환경 변수 및 설정 ---
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# 감시할 놀이터 목록 (True: 감시 활성화, False: 제외)
PLAYGROUND_CONFIG = {
    "irwon": {"name": "일원어린이실내놀이터", "code": "irwon_playground", "mid": "ID04_04074703", "enabled": True},
    "segok": {"name": "세곡어린이실내놀이터", "code": "segok_indoor_playground", "mid": "ID04_04070903", "enabled": True},
    "dogok": {"name": "도곡어린이실내놀이터", "code": "memewe_clean_playground", "mid": "ID04_02071902", "enabled": True},
}

# 감시할 회차/시간대 설정
TARGET_TIMES = ["10:00"]

# 요일 필터 (평일/주말 감시 여부)
INCLUDE_WEEKDAY = False
INCLUDE_WEEKEND = True

# 특정 날짜만 집중 감시할 경우 리스트로 입력 (예: ["2026-08-20", "2026-08-21"])
# 비워둘 경우(SPECIFIC_DATES = []) 오늘 기준 14일간 요일 필터 기준으로 전체 감시
SPECIFIC_DATES = []

# 감시 주기 설정 (초 단위, 차단 방지를 위한 랜덤 간격 범위)
MIN_INTERVAL = 30
MAX_INTERVAL = 50


# --- 2. 헬퍼 함수 ---
def log(msg):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now}] {msg}", flush=True)


def send_telegram(message):
    """텔레그램 알림 발송"""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        log("⚠️ 텔레그램 토큰 또는 Chat ID가 설정되지 않았습니다.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    params = {"chat_id": TELEGRAM_CHAT_ID, "text": message}
    try:
        resp = requests.get(url, params=params, timeout=10)
        if resp.status_code == 200:
            log("🔔 텔레그램 알림 발송 성공")
        else:
            log(f"❗ 텔레그램 발송 실패 (Status Code: {resp.status_code})")
    except Exception as e:
        log(f"❗ 텔레그램 통신 오류: {e}")


def extract_seats_left(text):
    """(예약수/정원) 텍스트에서 잔여 좌석 계산"""
    match = re.search(r"\((\d+)\s*/\s*(\d+)\)", text)
    if match:
        try:
            return int(match.group(2)) - int(match.group(1))
        except Exception:
            return 0
    return 0


def get_monitor_dates():
    """오늘 기준 14일치 날짜 객체 생성"""
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    return [today + timedelta(days=i) for i in range(14)]


def build_url(playground, date_obj):
    """강남구 예약 페이지 URL 생성"""
    today = datetime.now()
    btn = "prev" if date_obj.month <= today.month else "next"
    yyyymm = date_obj.strftime("%Y-%m")
    return f"https://www.gangnam.go.kr/resv/apply/{playground['code']}/list.do?btn={btn}&sch_week_day={yyyymm}&mid={playground['mid']}"


# --- 3. 크롤링 로직 ---
def check_once():
    all_available = []
    monitor_dates = get_monitor_dates()

    # 활성화된 놀이터만 필터링
    active_playgrounds = [pg for pg in PLAYGROUND_CONFIG.values() if pg.get("enabled", True)]

    if not active_playgrounds:
        log("⚠️ 활성화된 놀이터가 없습니다. 설정을 확인해주세요.")
        return []

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    for pg in active_playgrounds:
        for date_obj in monitor_dates:
            url = build_url(pg, date_obj)
            try:
                resp = requests.get(url, headers=headers, timeout=15)
            except Exception:
                log(f"❗ {pg['name']} 서버 지연/타임아웃 (건너뜀)")
                continue

            soup = BeautifulSoup(resp.text, "html.parser")
            buttons = soup.find_all("button")
            
            for btn in buttons:
                raw = btn.get_text(separator=" ", strip=True)
                text = " ".join(raw.split())
                
                date_tag = btn.find_parent("td")
                date_text = date_tag.find("span", class_="pl5") if date_tag else None
                if not date_text:
                    continue

                date_info = date_text.get_text(strip=True).replace("일", "")
                try:
                    full_date = datetime.strptime(
                        f"{date_obj.strftime('%Y-%m')}-{date_info.strip().zfill(2)}",
                        "%Y-%m-%d",
                    )
                except Exception:
                    continue

                if full_date.date() != date_obj.date():
                    continue

                # 특정 날짜 필터
                if SPECIFIC_DATES:
                    if full_date.strftime("%Y-%m-%d") not in SPECIFIC_DATES:
                        continue
                else:
                    is_weekday = full_date.weekday() < 5
                    if is_weekday and not INCLUDE_WEEKDAY:
                        continue
                    if not is_weekday and not INCLUDE_WEEKEND:
                        continue

                # 시간대 및 잔여 좌석 매칭
                for target_t in TARGET_TIMES:
                    if target_t in text:
                        seats = extract_seats_left(text)
                        if seats > 0:
                            slot_info = f"[{pg['name']}] {full_date.strftime('%m-%d')} ({target_t}) - 잔여: {seats}석"
                            all_available.append(slot_info)

            # 대상별 요청 간 미세 딜레이 (차단 방지)
            time.sleep(random.uniform(0.5, 1.2))

    return all_available


# --- 4. 메인 실행 루프 ---
def main():
    active_names = [pg['name'] for pg in PLAYGROUND_CONFIG.values() if pg.get('enabled', True)]
    log(f"▶️ 강남구 실내놀이터 모니터링 시작 (대상: {', '.join(active_names)})")

    while True:
        try:
            found = check_once()
            if found:
                log(f"🔥 예약 가능 슬롯 발견 ({len(found)}개)!")
                for item in found:
                    log(f" ➡ {item}")

                message = "✅ [강남구 놀이터 예약 가능]\n" + "\n".join([f"- {s}" for s in found])
                send_telegram(message)
            else:
                log("❌ 예약 가능 슬롯 없음")

            # 차단 방지 랜덤 딜레이
            sleep_time = random.uniform(MIN_INTERVAL, MAX_INTERVAL)
            log(f"⏳ {sleep_time:.1f}초 대기 후 재확인...")
            time.sleep(sleep_time)

        except KeyboardInterrupt:
            log("⏹️ 사용자에 의해 모니터링이 중단되었습니다.")
            break
        except Exception as e:
            log(f"❗ 메인 루프 예외 발생: {e}")
            time.sleep(20)


if __name__ == "__main__":
    main()
