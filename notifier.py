import requests
from config import log_msg, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID

def send_telegram_message(text):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID: 
        log_msg("텔레그램 연동 환경변수가 부재하여 메시지 발송을 취소합니다.", "DEBUG")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"}
    try: 
        res = requests.post(url, json=payload, timeout=10)
        log_msg(f"텔레그램 발송 요청 완료 (응답 코드: {res.status_code})", "DEBUG")
    except Exception as e: 
        log_msg(f"⚠️ 텔레그램 알림 메시지 발송 예외 발생: {e}", "ERROR")
