"""삼성카드 결제 안내 메일을 네이버 메일함에서 읽어 카드 한도에 반영하는 감시 프로그램 (fmkorea-mail 컨테이너).

한 연결로 '기다리기 → 새 메일 확인'을 반복함. 서버가 IMAP IDLE을 지원하면 새 메일 통보나 IDLE_SECONDS 중 먼저 오는 때에,
지원하지 않으면 POLL_SECONDS마다 확인. 통보는 '지금 확인' 신호로만 쓰고 실제 수집은 마지막으로 본 메일 번호(UID) 이후를
읽는 한 경로뿐이라, 통보를 놓쳐도 다음 확인 때 잡히고 재시작해도 이어서 읽음. 같은 결제는 승인번호로 한 번만 등록.
메일함은 읽기 전용으로 열어 읽음 표시를 바꾸지 않음.
"""
import email
import imaplib
import re
import time
from datetime import date, datetime
from email import policy
from email.utils import parseaddr

from bs4 import BeautifulSoup

from config import log_msg, short_err, NAVER_MAIL_USER, NAVER_MAIL_APP_PASSWORD, CARD_MAIL_FOLDER
from notifier import send_telegram_message
from card_store import card_mail_position, set_card_mail_position, set_card_mail_status, record_card_payment

IMAP_HOST = 'imap.naver.com'
IMAP_PORT = 993
SOCKET_TIMEOUT_SECONDS = 60
IDLE_SECONDS = 5 * 60
POLL_SECONDS = 90
# 끊겼을 때 다시 접속하는 간격 (점점 늘림). 로그인 실패는 계정이 잠기지 않도록 훨씬 길게 쉼
RETRY_MIN_SECONDS = 30
RETRY_MAX_SECONDS = 10 * 60
LOGIN_RETRY_SECONDS = 60 * 60

SENDER = 'cardweb@samsungcard.com'
SUBJECT_TEXT = '전자상거래 결제내역'
MONTHS = ('Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec')

# 실제 메일은 숫자·구분자가 칸으로 나뉘어 있어 글자로 바꾸면 '2026 . 11 . 08 09 : 36'처럼 띄어짐
PAID_AT_RE = re.compile(r'결제일시\s*:?\s*(\d{4})\s*[.\-/]\s*(\d{1,2})\s*[.\-/]\s*(\d{1,2})\s*\.?\s+(\d{1,2})\s*:\s*(\d{2})')
PLACE_RE = re.compile(r'이용가맹점\s*:?\s*(.+?)\s*결제금액')
AMOUNT_RE = re.compile(r'결제금액\s*:?\s*([\d,]+)\s*원')
APPROVAL_RE = re.compile(r'승인번호\s*:?\s*(\d+)')
CANCEL_RE = re.compile(r'(승인|결제)\s*취소|취소\s*(금액|일시)')


class LoginFailed(Exception):
    pass


def is_target(from_header, subject):
    return parseaddr(from_header or '')[1].lower() == SENDER and SUBJECT_TEXT in (subject or '')


def parse_payment(text):
    """메일 본문 글자에서 결제 정보를 꺼냄. 취소 안내이거나 형식이 다르면 None"""
    text = re.sub(r'\s+', ' ', text.replace('\xa0', ' ')).strip()
    if CANCEL_RE.search(text):
        return None
    paid = PAID_AT_RE.search(text)
    place = PLACE_RE.search(text)
    amount = AMOUNT_RE.search(text)
    approval = APPROVAL_RE.search(text)
    if not (paid and place and amount and approval):
        return None
    year, month, day, hour, minute = map(int, paid.groups())
    try:
        paid_at = datetime(year, month, day, hour, minute).strftime('%Y-%m-%d %H:%M')
    except ValueError:
        return None
    value = int(amount.group(1).replace(',', '') or 0)
    if value <= 0 or not place.group(1):
        return None
    return {'approval_no': approval.group(1), 'paid_at': paid_at, 'place': place.group(1)[:100], 'amount': value}


def _part_text(part):
    """메일 한 부분의 글자. 메일에 적힌 문자 인코딩이 틀렸거나 ks_c_5601처럼 파이썬이 모르는 이름이면 cp949로 읽음"""
    raw = part.get_payload(decode=True) or b''
    charset = part.get_content_charset() or 'utf-8'
    try:
        return raw.decode(charset)
    except (LookupError, UnicodeDecodeError):
        return raw.decode('cp949', 'replace')


def message_text(message):
    """본문 글자 (HTML이 있으면 태그를 뺀 글자, 없으면 일반 글자)"""
    plain = ''
    for part in message.walk():
        kind = part.get_content_type()
        if kind == 'text/html':
            soup = BeautifulSoup(_part_text(part), 'html.parser')
            for tag in soup(['script', 'style']):
                tag.decompose()
            return soup.get_text(' ')
        if kind == 'text/plain' and not plain:
            plain = _part_text(part)
    return plain


def _uid_list(result):
    typ, data = result
    if typ != 'OK' or not data or not data[0]:
        return []
    return [int(n) for n in data[0].split()]


def _fetched_bytes(result):
    typ, data = result
    if typ != 'OK':
        return b''
    for item in data or []:
        if isinstance(item, tuple):
            return item[1]
    return b''


def _response_number(conn, name):
    _, data = conn.response(name)
    try:
        return int(data[0])
    except (TypeError, ValueError, IndexError):
        return None


def collect(conn):
    """마지막으로 본 메일 이후를 읽어 등록. (읽지 못한 메일 수)를 돌려줌. 처음 실행하면 이번 달 메일부터 읽음"""
    typ, data = conn.select(f'"{CARD_MAIL_FOLDER}"', readonly=True)
    if typ != 'OK':
        raise imaplib.IMAP4.error(f'메일함을 열지 못했습니다: {data}')
    validity = _response_number(conn, 'UIDVALIDITY')
    uid_next = _response_number(conn, 'UIDNEXT')
    saved_validity, last = card_mail_position()
    if last is None or saved_validity != validity:
        first = date.today().replace(day=1)
        last = None
        found = _uid_list(conn.uid('SEARCH', None, 'SINCE', f'{first.day:02d}-{MONTHS[first.month - 1]}-{first.year}'))
    else:
        # 'n:*'는 n보다 큰 메일이 없어도 마지막 메일을 돌려주므로 아래에서 거름
        found = [u for u in _uid_list(conn.uid('SEARCH', None, 'UID', f'{last + 1}:*')) if u > last]
    unreadable = 0
    for uid in sorted(found):
        header = email.message_from_bytes(_fetched_bytes(conn.uid('FETCH', str(uid), '(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT)])')), policy=policy.default)
        if is_target(header['From'], header['Subject']):
            message = email.message_from_bytes(_fetched_bytes(conn.uid('FETCH', str(uid), '(BODY.PEEK[])')), policy=policy.default)
            payment = parse_payment(message_text(message))
            if payment is None:
                unreadable += 1
                log_msg(f"[메일] 결제 정보를 읽지 못한 메일 UID {uid} (취소 안내이거나 형식 변경)", "WARN")
            else:
                result = record_card_payment(**payment)
                log_msg(f"[메일] {payment['place']} {payment['amount']:,}원: {result}")
        last = uid
        if validity is not None:
            set_card_mail_position(validity, last)
    # 처음 실행 때 메일이 없었으면 이후 확인이 메일함 전체를 다시 찾지 않도록 현재 위치를 저장
    if last is None and uid_next and validity is not None:
        set_card_mail_position(validity, uid_next - 1)
    return unreadable


def wait_for_mail(conn):
    """새 메일 통보 또는 IDLE_SECONDS까지 기다림. 서버가 IDLE을 거부하면 False"""
    try:
        with conn.idle(duration=IDLE_SECONDS) as idler:
            for typ, _ in idler:
                if typ == 'EXISTS':
                    break
        return True
    except imaplib.IMAP4.abort:
        raise
    except imaplib.IMAP4.error as e:
        log_msg(f"[메일] IDLE을 쓸 수 없어 주기 확인으로 전환: {short_err(e)}", "WARN")
        return False


def watch(on_checked):
    """접속해 끊길 때까지 기다리기·확인을 반복. 끊기면 예외"""
    conn = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT, timeout=SOCKET_TIMEOUT_SECONDS)
    try:
        try:
            conn.login(NAVER_MAIL_USER, NAVER_MAIL_APP_PASSWORD)
        except imaplib.IMAP4.abort:
            raise
        except imaplib.IMAP4.error as e:
            raise LoginFailed(short_err(e)) from e
        use_idle = 'IDLE' in conn.capabilities
        log_msg(f"[메일] 접속 완료 ({'IDLE 대기' if use_idle else 'IDLE 미지원: 주기 확인'})")
        while True:
            unreadable = collect(conn)
            on_checked('idle' if use_idle else 'poll', unreadable)
            if use_idle:
                use_idle = wait_for_mail(conn)
            else:
                time.sleep(POLL_SECONDS)
    finally:
        try:
            conn.logout()
        except Exception:
            pass


def main():
    if not (NAVER_MAIL_USER and NAVER_MAIL_APP_PASSWORD):
        log_msg("[메일] NAVER_MAIL_USER·NAVER_MAIL_APP_PASSWORD가 없어 메일 확인을 하지 않습니다.")
        set_card_mail_status('off')
        while True:
            time.sleep(3600)
    delay = RETRY_MIN_SECONDS
    login_alerted = False
    unreadable_total = 0

    def on_checked(mode, unreadable):
        nonlocal delay, login_alerted, unreadable_total
        delay = RETRY_MIN_SECONDS
        login_alerted = False
        unreadable_total += unreadable
        set_card_mail_status('ok', mode=mode, message=f'읽지 못한 메일 {unreadable_total}건' if unreadable_total else '')

    while True:
        try:
            watch(on_checked)
        except LoginFailed as e:
            log_msg(f"[메일] 로그인 실패: {e}", "ERROR")
            set_card_mail_status('error', message='네이버 메일 로그인 실패 (애플리케이션 비밀번호·IMAP 설정 확인)')
            if not login_alerted:
                login_alerted = True
                send_telegram_message('⚠️ 네이버 메일 로그인에 실패해 카드 결제 메일을 읽지 못하고 있습니다. 애플리케이션 비밀번호와 IMAP 설정을 확인해 주세요.')
            time.sleep(LOGIN_RETRY_SECONDS)
        except (imaplib.IMAP4.error, OSError) as e:
            log_msg(f"[메일] 연결 끊김, {delay}초 뒤 다시 접속: {short_err(e)}", "WARN")
            set_card_mail_status('error', message='메일 서버에 다시 연결하는 중')
            time.sleep(delay)
            delay = min(delay * 2, RETRY_MAX_SECONDS)
        except Exception as e:
            log_msg(f"[메일] 처리 오류, {delay}초 뒤 다시 시도: {short_err(e)}", "ERROR")
            set_card_mail_status('error', message='메일 처리 중 오류')
            time.sleep(delay)
            delay = min(delay * 2, RETRY_MAX_SECONDS)


if __name__ == '__main__':
    main()
