import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT
import tempfile, imaplib
from email.message import EmailMessage
os.environ.update(OUTPUT_DIR=tempfile.mkdtemp(), LOG_LEVEL='CRITICAL', TELEGRAM_TOKEN='')
for name in [k for k in os.environ if k.startswith('KEYWORDS_')]:
    os.environ[name] = ''
sys.path.insert(0, os.path.join(ROOT, 'app'))
import storage, card_mail

# 실제 메일(PDF로 받은 예시)에서 나온 글자 순서: 칸 이름과 값이 붙어 있어도, 표로 나뉘어 있어도 읽혀야 함
BODY = ('임*범 회원님, 삼성카드를 이용해 주셔서 감사드립니다. 삼성카드 이용내역 결제일시{sep}2026.11.08 09:36 이용자임*범 님 '
        '이용가맹점{sep}{place} 결제금액{sep}{amount}원 승인번호{sep}{no} 결제유형일시불 전자상거래 바로알림서비스란? '
        '카드사 및 제휴사의 사정으로 변경·중단될 수 있습니다.')
def body(place='스타벅스_주문', amount='3,600', no='48968246', sep=''):
    return BODY.format(place=place, amount=amount, no=no, sep=sep)

expected = {'approval_no': '48968246', 'paid_at': '2026-11-08 09:36', 'place': '스타벅스_주문', 'amount': 3600}
assert card_mail.parse_payment(body()) == expected
assert card_mail.parse_payment(body(sep=' ')) == expected
assert card_mail.parse_payment(body(sep='\n : \n')) == expected
assert card_mail.parse_payment(body(place='투썸플레이스 강남점', amount='12,300'))['place'] == '투썸플레이스 강남점'
assert card_mail.parse_payment(body() + ' 승인취소') is None
assert card_mail.parse_payment('아무 내용') is None
assert card_mail.is_target('삼성카드 <cardweb@samsungcard.com>', '[삼성카드] 전자상거래 결제내역 안내')
assert not card_mail.is_target('가짜 <x@evil.test>', '[삼성카드] 전자상거래 결제내역 안내')   # 발신 주소가 달라도 표시 이름만 같으면 안 됨
assert not card_mail.is_target('cardweb@samsungcard.com', '이벤트 안내')
print('PARSE OK')

def mail(place, amount, no, sender='삼성카드 <cardweb@samsungcard.com>', subject='[삼성카드] 전자상거래 결제내역 안내', charset='euc-kr'):
    m = EmailMessage()
    m['From'] = sender
    m['Subject'] = subject
    m.set_content('<table><tr><td>결제일시</td><td>2026.11.08 09:36</td></tr><tr><td>이용가맹점</td><td>' + place
                  + '</td></tr><tr><td>결제금액</td><td>' + amount + '원</td></tr><tr><td>승인번호</td><td>' + no + '</td></tr></table>',
                  subtype='html', charset=charset)
    return m.as_bytes()

class FakeImap:
    """메일함을 흉내냄: 읽기 전용으로 열었는지, 본문을 읽음 표시 없이(PEEK) 가져오는지도 확인"""
    def __init__(self, mails, validity=7):
        self.mails, self.validity, self.searches = mails, validity, []
    def select(self, folder, readonly=False):
        assert readonly and folder == '"INBOX"'
        return 'OK', [b'1']
    def response(self, name):
        value = {'UIDVALIDITY': self.validity, 'UIDNEXT': (max(self.mails) + 1 if self.mails else 50)}[name]
        return name, [str(value).encode()]
    def uid(self, command, *args):
        if command == 'SEARCH':
            self.searches.append(args)
            if args[1] == 'SINCE':
                found = sorted(self.mails)
            else:
                start = int(args[2].split(':')[0])
                found = sorted(u for u in self.mails if u >= start) or sorted(self.mails)[-1:]   # n:*의 서버 동작
            return 'OK', [' '.join(map(str, found)).encode()]
        assert 'PEEK' in args[1], args
        return 'OK', [(b'head', self.mails[int(args[0])]), b')']

month = '2026-11'
assert card_mail.card_mail_position() == (None, None)
fake = FakeImap({
    11: mail('스타벅스_주문', '3,600', '1001'),
    12: mail('쿠팡', '28,900', '1002'),
    13: mail('스타벅스_주문', '3,600', '1003', sender='x@evil.test'),                # 다른 발신자
    14: mail('투썸플레이스 강남점', '5,800', '1004', charset='utf-8'),
})
assert card_mail.collect(fake) == 0
data = storage.card_benefits(month)
assert sorted(x['place'] for x in data['items']) == ['스타벅스_주문', '투썸플레이스 강남점'] and all(x['from_mail'] for x in data['items']), data
assert sum(x['amount'] for x in data['items']) == 9400
assert [x['place'] for x in data['others']] == ['쿠팡'] and data['recent'] == []    # 메일 건은 직접 입력의 최근 목록에 넣지 않음
assert fake.searches[0][1] == 'SINCE' and card_mail.card_mail_position() == (7, 14)

# 새 메일이 없으면 다시 처리하지 않음, 같은 승인번호는 한 번만, 재시작해도 이어서
assert card_mail.collect(fake) == 0 and len(storage.card_benefits(month)['items']) == 2
fake.mails[15] = mail('스타벅스_주문', '3,600', '1001')
assert fake.searches[-1][2] == '15:*'
assert card_mail.collect(fake) == 0 and len(storage.card_benefits(month)['items']) == 2 and card_mail.card_mail_position() == (7, 15)
print('COLLECT OK')

# 형식이 다른 메일은 건너뛰고 세며 위치는 넘어감
m = EmailMessage(); m['From'] = 'cardweb@samsungcard.com'; m['Subject'] = '[삼성카드] 전자상거래 결제내역 안내'; m.set_content('승인취소 안내', charset='utf-8')
fake.mails[16] = m.as_bytes()
assert card_mail.collect(fake) == 1 and card_mail.card_mail_position() == (7, 16)

# 메일함이 바뀌면(UIDVALIDITY) 이번 달부터 다시 찾지만 승인번호로 중복은 없음
fake.validity = 8
assert card_mail.collect(fake) == 1 and fake.searches[-1][1] == 'SINCE' and len(storage.card_benefits(month)['items']) == 2

# 처음 실행했는데 메일이 없으면 현재 위치만 저장
with storage._db() as conn, conn:
    conn.execute("DELETE FROM meta WHERE key IN ('card_mail_uid', 'card_mail_uidvalidity')")
assert card_mail.collect(FakeImap({})) == 0 and card_mail.card_mail_position() == (7, 49)
print('STATE OK')

# 가게 추가: 찾아 둔 결제도 차감. 가게 삭제: 이미 차감한 내역은 그대로, 앞으로만. 지운 메일 건은 다시 들어오지 않음
assert storage.add_card_keyword('쿠팡') == 1
data = storage.card_benefits(month)
assert sum(x['amount'] for x in data['items']) == 38300 and data['others'] == []
assert storage.delete_card_keyword('쿠팡') and not storage.delete_card_keyword('쿠팡')
assert sum(x['amount'] for x in storage.card_benefits(month)['items']) == 38300
assert storage.record_card_payment('2001', '2026-11-08 10:00', '쿠팡', 100) == 'other'
assert storage.record_card_payment('2001', '2026-11-08 10:00', '쿠팡', 100) == 'duplicate'
assert storage.record_card_payment('2002', '2026-11-08 10:00', 'STARBUCKS 스타벅스', 100) == 'matched'
bid = [x for x in storage.card_benefits(month)['items'] if x['place'].startswith('STARBUCKS')][0]['id']
assert storage.delete_card_benefit(bid)
assert storage.record_card_payment('2002', '2026-11-08 10:00', 'STARBUCKS 스타벅스', 100) == 'duplicate'
assert [x['place'] for x in storage.card_benefits(month)['others']].count('STARBUCKS 스타벅스') == 1
print('RULES OK')
