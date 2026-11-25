"""휴대폰 결제 알림 글 읽기 (가계부 자동 기록, ledger.py가 씀). DB·네트워크 없이 글만 봄

카드사마다 알림 모양이 다르므로 정해진 틀 대신 조각을 찾아 읽음:
- 금액: '13,900원' (여럿이면 '누적·잔액·한도' 앞이 아닌 첫 금액)
- 승인인지 취소인지: '취소'가 들어 있으면 취소. '승인·결제·사용·출금·체크' 등 결제 낱말이나 금액이 없으면 결제 알림이 아님
- 날짜·시각: '11/24 21:03' (없으면 받은 때)
- 카드: '[삼성카드]', 'KB국민카드1234', '신한카드(1234)' 같은 카드사 이름
- 가게: 위 조각들과 이름(임*범)·할부·누적 등을 뺀 나머지에서 가장 그럴듯한 줄
"""
import re
from datetime import date, datetime

CARD_NAMES = ['삼성', 'KB국민', '국민', '신한', '현대', '롯데', '우리', '하나', 'NH농협', '농협', 'BC', '비씨', '씨티', 'IBK기업', '기업',
              '카카오뱅크', '카카오페이', '토스', '케이뱅크', 'SC제일', '수협', '광주', '전북', '제주', '부산', '대구', '경남']
AMOUNT_RE = re.compile(r'(?<![\d,])(\d{1,3}(?:,\d{3})+|\d+)\s*원')
DATE_TIME_RE = re.compile(r'(?<!\d)(\d{1,2})[/.-](\d{1,2})(?:\s*\([월화수목금토일]\))?\s*(\d{1,2}):(\d{2})(?!\d)')
DATE_RE = re.compile(r'(?<!\d)(\d{1,2})/(\d{1,2})(?!\d)')
TIME_RE = re.compile(r'(?<!\d)(\d{1,2}):(\d{2})(?!\d)')
PAY_WORDS = ('승인', '결제', '사용', '출금', '체크', '일시불', '할부', '이용')
CANCEL_WORDS = ('취소', '환불')
# 금액 바로 앞에 이 낱말이 있으면 결제 금액이 아님 (누적 사용액 등)
NOT_PAY_BEFORE = ('누적', '잔액', '한도', '잔여', '총', '합계', '포인트', '캐시백', '할인')
# 가게가 아닌 조각
NOISE_RE = re.compile(
    r'\[[^\]]*\]|\([^)]*\d[^)]*\)|(?:승인|결제|사용|입출금|출금|취소|환불|체크|일시불|이용|안내|알림|완료|해외|국내|온라인|체크카드|신용카드|Web발신)'
    r'|\d+\s*개월|할부\s*\d*\s*(?:개월)?|누적\s*[\d,]+\s*원?|잔액\s*[\d,]+\s*원?|한도\s*[\d,]+\s*원?|[￦₩]?\s*[\d,]+\s*원|[￦₩]'
    r'|\d{1,2}[/.-]\d{1,2}(?:\s*\([월화수목금토일]\))?|\d{1,2}:\d{2}|[가-힣]\*[가-힣*]*\s*님?|님')
# '사용처 지자체세입금' · '이용처 : 스타벅스' 처럼 이름표가 붙은 가게 (하나카드 등)
LABEL_RE = re.compile(r'(?:사용처|이용처|가맹점명?|상호명?)\s*[:：]?\s*([^\n]+)')
# '주식회사 케이에프씨코리아에서 결제했어요' (삼성월렛·페이 알림)
WHERE_RE = re.compile(r'([^\s,.]+(?:\s[^\s,.]+)?)에서\s*(?:결제|사용|이용|승인)')
COMPANY_RE = re.compile(r'^\s*(?:\(주\)|㈜|주식회사)\s*|\s*(?:\(주\)|㈜|주식회사)\s*$')


def _card(text):
    for name in CARD_NAMES:
        m = re.search(re.escape(name) + r'\s*(?:카드|체크카드|페이|뱅크)?', text)
        if m:
            label = name if name not in ('국민', '농협', '비씨', '기업') else {'국민': 'KB국민', '농협': 'NH농협', '비씨': 'BC', '기업': 'IBK기업'}[name]
            return label + ('카드' if '카드' not in label and '페이' not in m.group(0) and '뱅크' not in m.group(0) else '')
    return ''


def _amount(text):
    for m in AMOUNT_RE.finditer(text):
        before = text[max(0, m.start() - 6):m.start()]
        if any(w in before for w in NOT_PAY_BEFORE):
            continue
        value = int(m.group(1).replace(',', ''))
        if value > 0:
            return value
    return None


def _when(text, now):
    m = DATE_TIME_RE.search(text)
    month = day = None
    hhmm = ''
    if m:
        month, day = int(m.group(1)), int(m.group(2))
        hhmm = f'{int(m.group(3)):02d}:{m.group(4)}'
    else:
        d = DATE_RE.search(text)
        if d:
            month, day = int(d.group(1)), int(d.group(2))
        t = TIME_RE.search(text)
        if t:
            hhmm = f'{int(t.group(1)):02d}:{t.group(2)}'
    used_on = now.date()
    if month and day:
        # 알림에는 해가 없음: 오늘보다 뒤 날짜면 지난해 (1월 초에 받은 12월 결제)
        for year in (now.year, now.year - 1):
            try:
                cand = date(year, month, day)
            except ValueError:
                continue
            if cand <= now.date():
                used_on = cand
                break
    return used_on.isoformat(), hhmm or now.strftime('%H:%M')


def _company(name):
    """앞뒤의 '주식회사·(주)'를 뺌 (빼고 두 글자 넘게 남을 때만)"""
    rest = COMPANY_RE.sub('', name).strip()
    return rest if len(rest) >= 2 else name


def _merchant(text, card):
    # 이름표가 붙었거나 'OO에서 결제'면 그 자리를 그대로 (군더더기를 지우다 '사용처'의 '사용'까지 지우던 것)
    for regex in (LABEL_RE, WHERE_RE):
        m = regex.search(text)
        if m:
            name = re.sub(r'\s+', ' ', m.group(1)).strip(' -·:,.')
            if len(re.findall(r'[가-힣A-Za-z]', name)) >= 2:
                return _company(name)[:40]
    return _company(_merchant_pieces(text, card) or card)


def _merchant_pieces(text, card):
    # 줄·세로줄로 나눔 ('/'는 날짜 11/25에도 쓰여 나누지 않음)
    pieces = [p.strip() for p in re.split(r'[\n|│]+', text) if p.strip()]
    cands = []
    for p in pieces:
        rest = p
        if card:
            rest = re.sub(re.escape(card.replace('카드', '')) + r'\s*(?:카드|체크카드)?\s*\d*', ' ', rest)
        rest = NOISE_RE.sub(' ', rest)
        rest = re.sub(r'\(\s*\)', ' ', rest)   # '(일시불)'에서 낱말만 빠지고 남은 괄호
        rest = re.sub(r'\s+', ' ', rest).strip(' -·:,')
        if rest and not re.fullmatch(r'[\d\s*,.()-]+', rest):
            cands.append(rest)
    if not cands:
        return ''
    # 글자(한글·영문)가 두 개 이상인 조각 중 가장 긴 것
    return max(cands, key=lambda c: (len(re.findall(r'[가-힣A-Za-z]', c)) >= 2, len(c)))[:40]


def parse(text, now=None):
    """결제 알림 글 → {amount, merchant, card, used_on, time, cancel} 또는 결제 알림이 아니면 None"""
    now = now or datetime.now()
    text = (text or '').replace('\r', '\n').strip()[:2000]
    if not text:
        return None
    amount = _amount(text)
    if not amount or not any(w in text for w in PAY_WORDS + CANCEL_WORDS):
        return None
    card = _card(text)
    used_on, hhmm = _when(text, now)
    return {'amount': amount, 'merchant': _merchant(text, card), 'card': card, 'used_on': used_on, 'time': hhmm,
            'cancel': any(w in text for w in CANCEL_WORDS)}


def rule_key(merchant):
    """가게 이름 비교용 (띄어쓰기·(주) 등을 빼고 소문자)"""
    return re.sub(r'\(주\)|㈜|주식회사|\s+', '', merchant or '').casefold()


def suggest_pattern(merchant):
    """'이 가게는 늘 ○○로' 규칙의 글자: 지점 이름을 빼고 앞 낱말 (스타벅스 강남점 → 스타벅스)"""
    name = re.sub(r'\(주\)|㈜|주식회사', '', merchant or '').strip()
    words = name.split()
    if len(words) >= 2 and re.search(r'(점|지점|역점|센터)$', words[-1]):
        words = words[:-1]
    return (words[0] if words and len(words[0]) >= 2 else name)[:20]
