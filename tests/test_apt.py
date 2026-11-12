"""아파트 실거래가: API 응답 읽기, 관심 단지의 거래만 저장, 처음 채우기는 알림 없이, 그 뒤 새 거래만 알림,
요약(직전 대비·최고가 대비)·상세 조회, 관리 요청"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT
import tempfile, threading, json, socket, urllib.request, urllib.error
from datetime import date, timedelta
os.environ.update(OUTPUT_DIR=tempfile.mkdtemp(), LOG_LEVEL='CRITICAL', ADMIN_PASSWORD='Secr3t!', TELEGRAM_TOKEN='',
                  APT_API_KEY='abc%2Bdef%3D%3D', APT_BACKFILL_MONTHS='6')
for name in [k for k in os.environ if k.startswith('KEYWORDS_')]:
    os.environ[name] = ''
import storage, apt_store, apt_trades, web_server

apt_trades.time.sleep = lambda s: None
assert apt_trades._service_key() == 'abc+def=='          # 인코딩된 키를 넣어도 원래 값으로

def item(name, seq, area, floor, amount, y, m, d, cancel=''):
    return (f"<item><aptNm>{name}</aptNm><aptSeq>{seq}</aptSeq><umdNm>역삼동</umdNm><excluUseAr>{area}</excluUseAr>"
            f"<floor>{floor}</floor><dealAmount>{amount}</dealAmount><dealYear>{y}</dealYear><dealMonth>{m}</dealMonth>"
            f"<dealDay>{d}</dealDay><buildYear>2005</buildYear><cdealType>{cancel}</cdealType><cdealDay></cdealDay>"
            f"<dealingGbn>중개거래</dealingGbn></item>")
def response(items, total=None):
    return ("<response><header><resultCode>000</resultCode><resultMsg>OK</resultMsg></header><body><items>"
            + ''.join(items) + f"</items><numOfRows>1000</numOfRows><pageNo>1</pageNo><totalCount>{len(items) if total is None else total}"
            "</totalCount></body></response>")

# --- 1) 응답 읽기
trades, total = apt_trades.parse_trades(response([item('예시아파트', '11680-1', '84.97', '12', ' 123,000', 2026, 11, 3),
                                                  item('예시아파트', '11680-1', '59.5', '3', '90,000', 2026, 10, 9, 'O'),
                                                  '<item><aptNm></aptNm></item>']), '11680')
assert total == 3 and len(trades) == 2, (total, trades)
assert trades[0] == {'lawd_cd': '11680', 'apt_seq': '11680-1', 'apt_name': '예시아파트', 'umd_name': '역삼동', 'area': 84.97, 'floor': 12,
                     'amount': 123000, 'deal_date': '2026-11-03', 'build_year': 2005, 'canceled': False, 'cancel_date': '',
                     'dealing': '중개거래'}, trades[0]
assert trades[1]['canceled'] and trades[1]['amount'] == 90000
for bad, expect in [("<OpenAPI_ServiceResponse><cmmMsgHeader><errMsg>SERVICE ERROR</errMsg><returnAuthMsg>등록되지 않은 서비스키"
                     "</returnAuthMsg></cmmMsgHeader></OpenAPI_ServiceResponse>", '등록되지 않은 서비스키'),
                    ("<response><header><resultCode>22</resultCode><resultMsg>LIMITED</resultMsg></header></response>", 'LIMITED'),
                    ("<html>점검 중", '읽을 수 없음')]:
    try:
        apt_trades.parse_trades(bad, '11680'); raise SystemExit('no error')
    except apt_trades.AptApiError as e:
        assert expect in str(e), e
assert apt_trades.month_list(3, date(2026, 1, 15)) == ['202601', '202512', '202511']
assert [apt_trades.format_amount(v) for v in (123000, 120000, 9500, 100500)] == ['12억 3,000', '12억', '9,500만', '10억 500']
# 여러 페이지면 모두 받음
class Res:
    status_code = 200
    def __init__(self, text): self.text = text
pages = []
def fake_get(url, params, timeout):
    pages.append(params['pageNo'])
    return Res(response([item('예시아파트', '11680-1', '84.97', str(params['pageNo']), '100,000', 2026, 11, 1)], total=2500))
assert len(apt_trades.fetch_month('11680', '202611', get=fake_get)) == 3 and pages == [1, 2, 3]
print('APT PARSE OK')

# --- 2) 수집: 처음 채우기는 알림 없이, 그 뒤 새 거래만 알림 (면적이 맞는 관심 단지만)
storage.init_db()
today = date.today()
def ym(months_ago):
    return apt_trades.month_list(months_ago + 1)[-1]
def day(months_ago, d=5):
    m = ym(months_ago)
    return f'{m[:4]}-{m[4:]}-{d:02d}'
def T(seq, area, floor, amount, deal_date, name='예시아파트', canceled=False):
    return {'lawd_cd': '11680', 'apt_seq': seq, 'apt_name': name, 'umd_name': '역삼동', 'area': area, 'floor': floor, 'amount': amount,
            'deal_date': deal_date, 'build_year': 2005, 'canceled': canceled, 'cancel_date': '', 'dealing': '중개거래'}
book = {ym(5): [T('11680-1', 84.97, 3, 110000, day(5))],
        ym(2): [T('11680-1', 84.97, 7, 118000, day(2)), T('11680-1', 59.5, 2, 90000, day(2)), T('11680-9', 84.0, 1, 50000, day(2), '다른단지')],
        ym(1): [T('11680-1', 84.97, 9, 120000, day(1))]}
calls = []
def fake_fetch(lawd_cd, deal_ym):
    calls.append(deal_ym)
    return [dict(t) for t in book.get(deal_ym, [])]
alerts = []
def fake_alert(watches, added):
    alerts.extend(added)
    return len(added)
w1 = apt_store.add_watch('11680', '11680-1', '예시아파트', '역삼동', 85)
try:
    apt_store.add_watch('11680', '11680-1', '예시아파트', '역삼동', 85); raise SystemExit('duplicate allowed')
except ValueError:
    pass
added, sent = apt_trades.sync_once(fake_fetch, fake_alert)
assert added == 4 and sent == 0 and alerts == [] and len(calls) == 6, (added, sent, calls)      # 관심 단지만 저장 (다른단지 제외)
assert apt_store.list_watches()[0]['synced_at']
# 새 거래 2건(84㎡·59㎡)과 지난 거래의 취소: 최근 3개월만 다시 확인
calls.clear()
book[ym(0)] = [T('11680-1', 84.97, 15, 123000, day(0, 1)), T('11680-1', 59.5, 4, 92000, day(0, 1))]
book[ym(2)][0]['canceled'] = True
added, sent = apt_trades.sync_once(fake_fetch, fake_alert)
assert added == 2 and len(calls) == 3 and len(alerts) == 2, (added, calls, alerts)
assert apt_trades.sync_once(fake_fetch, fake_alert) == (0, 0)                                   # 같은 거래는 다시 저장·알림 안 함
print('APT SYNC OK')

# --- 3) 알림 대상(면적·알림 설정)과 문구
sent_texts = []
import notifier
notifier._configured = lambda: True
notifier._send_html = lambda base, text, what: sent_texts.append((base, text, what))
watches = apt_store.list_watches()
assert apt_trades.send_alerts(watches, alerts) == 1                    # 관심 면적(85㎡)만, 59㎡는 제외
base, text, what = sent_texts[0]
assert what == '실거래 알림' and '예시아파트' in text and '85㎡' in text and '12억 3,000' in text and '15층' in text, text
assert '직전 12억' in text and '▲ 3,000만' in text, text             # 취소된 거래(11억 8,000)는 건너뛰고 그 다음 거래와 비교
assert text.startswith('🔥') and '신고가' in text and '이전 최고 12억' in text, text   # 이전 최고 12억보다 비싸면 신고가
plain = apt_trades.build_alert({'apt_name': '예시아파트'}, T('11680-1', 84.97, 3, 115000, day(0, 2)), None, {'amount': 123000, 'deal_date': day(0, 1), 'floor': 15})
assert plain.startswith('🏠') and '신고가' not in plain, plain
apt_store.set_watch_alert(w1, False)
assert apt_trades.send_alerts(apt_store.list_watches(), alerts) == 0   # 알림을 끄면 안 보냄
apt_store.set_watch_alert(w1, True)
print('APT ALERT OK')

# --- 4) 요약·상세
s = apt_store.watch_summaries()[0]
assert s['latest']['amount'] == 123000 and s['latest']['is_new'] and s['diff'] == 3000 and s['peak'] == 123000 and s['peak_ratio'] == 0
assert s['low'] == 110000 and s['avg'] == 117667 and s['avg_count'] == 3, s   # 최저·1년 평균 (취소된 거래 제외)
assert s['record'] and s['record_gain'] == 3000, s   # 신고가: 같은 면적의 이전 최고 12억보다 3,000만 높음
assert s['trade_count'] == 3 and [p['amount'] for p in s['spark']] == [110000, 120000, 123000], s   # 취소 거래·다른 면적 제외
d = apt_store.watch_detail(w1)
assert d['areas'] == [{'area': 60, 'count': 2}, {'area': 85, 'count': 4}] and len(d['trades']) == 6 and d['build_year'] == 2005
assert [t['canceled'] for t in d['trades']].count(True) == 1 and d['trades'][0]['date'] == day(0, 1)
assert apt_store.watch_detail(999) is None
print('APT SUMMARY OK')

# --- 5) 요청: 조회는 누구나, 관리는 암호 필요
with socket.socket() as sock:
    sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
srv = web_server.ThreadedHTTPServer(('127.0.0.1', port), web_server.KeywordAPIServer)
threading.Thread(target=srv.serve_forever, daemon=True).start()
def get(path):
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}{path}') as r:
            return r.status, json.load(r) if path.startswith('/api/') else r.read()
    except urllib.error.HTTPError as e:
        return e.code, json.load(e)
def post(body):
    req = urllib.request.Request(f'http://127.0.0.1:{port}/api/apt', data=json.dumps(body).encode(), method='POST',
                                 headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, json.load(e)
code, data = get('/api/apt')
assert code == 200 and data['configured'] and data['watches'][0]['name'] == '예시아파트'
assert get(f'/api/apt/detail?id={w1}')[1]['name'] == '예시아파트' and get('/api/apt/detail?id=999')[0] == 404
for path in ('/apt/', '/apt.js', '/apt.css'):
    assert get(path)[0] == 200, path
P = {'password': 'Secr3t!'}
assert post({'action': 'add', 'lawd_cd': '11680', 'apt_seq': 'x', 'name': '새단지', 'password': 'no'})[0] == 401
for bad in ({'action': 'add', 'lawd_cd': '1168', 'apt_seq': 'x', 'name': '새단지'}, {'action': 'add', 'lawd_cd': '11680', 'apt_seq': 'x', 'name': ''},
            {'action': 'add', 'lawd_cd': '11680', 'apt_seq': 'x', 'name': '새단지', 'area': 5}, {'action': 'delete', 'id': '1'},
            {'action': 'alert', 'id': w1}, {'action': 'search', 'lawd_cd': '11680', 'name': ''}, {'action': 'what', 'id': w1}):
    assert post({**bad, **P})[0] == 400, bad
apt_trades.fetch_month = fake_fetch
found = apt_trades.search_complexes('11680', '예시 아파트', fetch=fake_fetch)
assert len(found) == 1 and found[0]['apt_seq'] == '11680-1' and found[0]['areas'] == [60, 85] and found[0]['count'] == 5, found
code, body = post({'action': 'search', 'lawd_cd': '11680', 'name': '다른', **P})
assert code == 200 and [r['name'] for r in body['results']] == ['다른단지'], body
# 지역의 모든 단지 (단지 고르기 목록): 이름 순, 한 번 받으면 다시 받지 않음
# 1년 넘게 거래가 없던 단지(새로 지어 매매가 드문 단지 등)도 목록에 나와야 함 (3년)
book[ym(20)] = [T('11680-7', 84.9, 3, 70000, day(20), '드문단지')]
calls.clear()
code, body = post({'action': 'complexes', 'lawd_cd': '11680', **P})
assert code == 200 and [r['name'] for r in body['results']] == ['다른단지', '드문단지', '예시아파트'] and len(calls) == apt_trades.SEARCH_MONTHS == 36, (body, len(calls))
assert post({'action': 'complexes', 'lawd_cd': '11680', **P})[0] == 200 and len(calls) == 36   # 받아 둔 목록을 다시 씀
assert post({'action': 'complexes', 'lawd_cd': '116', **P})[0] == 400
# 화면의 지역 목록: 코드 5자리, 바뀐 지역 코드 반영
regions = open(os.path.join(ROOT, 'app', 'static', 'apt-regions.js'), encoding='utf-8').read()
import re
codes = re.findall(r"\['(\d{5})', '([^']+)', '([^']*)'\]", regions)
assert len(codes) > 240 and len({c for c, _, _ in codes}) == len(codes)
assert ('11680', '서울특별시', '강남구') in codes and ('51110', '강원특별자치도', '춘천시') in codes and ('41597', '경기도', '화성시 동탄구') in codes
assert not any(c.startswith(('42', '45')) or c in ('41590', '28110', '41130') or '출장' in n for c, _, n in codes)
woke = []
apt_trades.request_sync = lambda: woke.append(1)
code, body = post({'action': 'add', 'lawd_cd': '11680', 'apt_seq': '11680-9', 'name': '다른단지', 'umd': '역삼동', 'area': None, **P})
assert code == 200 and body['id'] and woke == [1], (code, body)
assert post({'action': 'add', 'lawd_cd': '11680', 'apt_seq': '11680-9', 'name': '다른단지', 'umd': '역삼동', 'area': None, **P})[0] == 400
assert post({'action': 'alert', 'id': body['id'], 'enabled': False, **P})[1]['success']
assert [w['alert'] for w in apt_store.watch_summaries()] == [True, False]
assert post({'action': 'delete', 'id': w1, **P})[1]['success'] and post({'action': 'delete', 'id': w1, **P})[0] == 400
with storage._db() as conn:
    assert conn.execute("SELECT COUNT(*) FROM apt_trades WHERE apt_seq = '11680-1'").fetchone()[0] == 0   # 단지를 지우면 거래도
print('APT OK')
