import os
import re
import requests
from datetime import datetime, timedelta
from bs4 import BeautifulSoup

# 환경 변수에서 텔레그램 값 가져오기
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# ==========================================
# ⚙️ [감시 조건 설정] - 필요에 맞춰 수정하세요
# ==========================================
AVAILABLE_TIMES = ["10:00"]  # 감시할 시간대
INCLUDE_WEEKDAY = False   # 평일 포함 여부 (True/False)
INCLUDE_WEEKEND = True   # 주말 포함 여부 (True/False)

# 특정 날짜만 지정할 때 (비워두면 요일 필터 적용)
# 예시: SPECIFIC_DATES = ["2026-08-01", "2026-08-02"]
SPECIFIC_DATES = []
# ==========================================

PLAYGROUNDS = [
    {"name": "일원어린이실내놀이터", "code": "irwon_playground", "mid": "ID04_04074703"},
    {"name": "세곡어린이실내놀이터", "code": "segok_indoor_playground", "mid": "ID04_04070903"}
]

def send_telegram(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("❗ 텔레그램 토큰 또는 Chat ID가 설정되지 않았습니다.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    params = {"chat_id": TELEGRAM_CHAT_ID, "text": message}
    try:
        resp = requests.get(url, params=params, timeout=10)
        if resp.status_code == 200:
            print("🔔 텔레그램 알림 전송 완료!")
        else:
            print(f"❗ 텔레그램 전송 실패: {resp.text}")
    except Exception as e:
        print(f"❗ 텔레그램 발송 오류: {e}")

def extract_seats_left(text):
    match = re.search(r"\((\d+)\s*/\s*(\d+)\)", text)
    if match:
        try:
            return int(match.group(2)) - int(match.group(1))
        except:
            return 0
    return 0

def get_monitor_dates():
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    return [today + timedelta(days=i) for i in range(14)]

def build_url(playground, date_obj):
    today = datetime.now()
    btn = "prev" if date_obj.month <= today.month else "next"
    yyyymm = date_obj.strftime("%Y-%m")
    return f"https://www.gangnam.go.kr/resv/apply/{playground['code']}/list.do?btn={btn}&sch_week_day={yyyymm}&mid={playground['mid']}"

def check_once():
    all_available = []
    monitor_dates = get_monitor_dates()
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    for pg in PLAYGROUNDS:
        for date_obj in monitor_dates:
            # 1. 1차 날짜 필터링 (조회 대상 날짜 확인)
            date_str = date_obj.strftime("%Y-%m-%d")
            is_weekday = date_obj.weekday() < 5

            if SPECIFIC_DATES:
                if date_str not in SPECIFIC_DATES:
                    continue  # 특정 날짜 지정 목록에 없으면 URL 요청 자체를 스킵
            else:
                if is_weekday and not INCLUDE_WEEKDAY:
                    continue
                if not is_weekday and not INCLUDE_WEEKEND:
                    continue

            url = build_url(pg, date_obj)
            try:
                resp = requests.get(url, headers=headers, timeout=15)
            except Exception as e:
                print(f"❗ {pg['name']} 요청 오류: {e}")
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
                    full_date = datetime.strptime(f"{date_obj.strftime('%Y-%m')}-{date_info.strip().zfill(2)}", "%Y-%m-%d")
                except Exception:
                    continue

                # 달력 크롤링 특성상 다른 달 날짜나 타깃 날짜와 다르면 스킵
                if full_date.date() != date_obj.date():
                    continue

                # 2. 시간대 필터링 및 잔여 좌석 확인
                for t in AVAILABLE_TIMES:
                    if t in text:
                        seats = extract_seats_left(text)
                        if seats > 0:
                            res_msg = f"[{pg['name']}] {full_date.strftime('%m-%d')} ({t}) - 잔여: {seats}석"
                            all_available.append(res_msg)

    return all_available

if __name__ == "__main__":
    print(f"▶️ [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 감시 조건 검증 후 스크립트 실행")
    print(f"📌 설정 - 평일:{INCLUDE_WEEKDAY}, 주말:{INCLUDE_WEEKEND}, 시간:{AVAILABLE_TIMES}, 지정날짜:{SPECIFIC_DATES}")
    
    found = check_once()
    if found:
        message = "✅ [강남구 놀이터 예약 가능 발견]\n" + "\n".join([f"- {item}" for item in found])
        send_telegram(message)
        print(f"🔥 조건에 맞는 잔여석 발견: {len(found)}개")
    else:
        print("❌ 조건에 맞는 예약 가능 슬롯이 없습니다.")
