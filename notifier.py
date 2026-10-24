import requests
from config import log_msg, short_err, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID

_missing_config_warned = False

def _redact(text):
    """요청 URL이 포함된 예외 메시지에 봇 토큰이 노출되지 않도록 가림"""
    return text.replace(TELEGRAM_TOKEN, '***') if TELEGRAM_TOKEN else text

def send_telegram_message(text, reply_markup=None):
    global _missing_config_warned
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        if not _missing_config_warned:
            log_msg("[알림] TELEGRAM_TOKEN/TELEGRAM_CHAT_ID 미설정 - 텔레그램 발송을 건너뜁니다.", "WARN")
            _missing_config_warned = True
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
            # 제목의 특수문자로 Markdown 파싱이 실패하는 경우가 많아 일반 텍스트로 한 번 더 시도
            log_msg(f"[알림] Markdown 발송 실패({res.status_code}) → 일반 텍스트로 재시도", "DEBUG")
            payload.pop("parse_mode", None)
            res = requests.post(url, json=payload, timeout=10)
            if res.status_code != 200:
                log_msg(f"[알림] 텔레그램 발송 실패({res.status_code}): {short_err(_redact(res.text))}", "ERROR")
    except Exception as e:
        log_msg(f"[알림] 텔레그램 발송 오류: {short_err(_redact(str(e)))}", "ERROR")
