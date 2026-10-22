import requests
from config import log_msg, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID

def send_telegram_message(text, reply_markup=None):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID: 
        log_msg("텔레그램 연동 환경변수가 부재하여 메시지 발송을 취소합니다.", "DEBUG")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID, 
        "text": text, 
        "parse_mode": "Markdown"
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try: 
        res = requests.post(url, json=payload, timeout=10)
        if res.status_code != 200:
            log_msg(f"⚠️ 텔레그램 발송 실패 (상태: {res.status_code}, 내용: {res.text}) -> Markdown 없이 재시도", "WARN")
            payload.pop("parse_mode", None)
            res = requests.post(url, json=payload, timeout=10)
            if res.status_code == 200:
                log_msg("텔레그램 일반 텍스트 모드로 재발송 성공", "INFO")
            else:
                log_msg(f"⚠️ 텔레그램 재발송 실패: {res.text}", "ERROR")
        else:
            log_msg(f"텔레그램 발송 요청 완료 (응답 코드: {res.status_code})", "DEBUG")
    except Exception as e: 
        log_msg(f"⚠️ 텔레그램 알림 메시지 발송 예외 발생: {e}", "ERROR")
