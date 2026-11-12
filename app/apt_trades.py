"""아파트 매매 실거래가 수집: 국토교통부 실거래가 공개 API(공공데이터포털)에서 관심 단지의 거래를 받아 저장하고,
새 거래가 올라오면 텔레그램으로 알림. 대시보드 웹서버 안에서 따로 도는 작업으로 실행 (web_server.run_api_server).

- API는 시군구(법정동 코드 앞 5자리)·계약 연월 단위로만 조회되므로, 받은 뒤 관심 단지의 거래만 골라 저장
- 처음 등록한 단지는 지난 APT_BACKFILL_MONTHS개월을 한 번 채우고(알림 없음), 그 뒤로는 최근 3개월을 다시 확인
  (신고 기한이 계약 후 30일이라 지난달 계약이 늦게 올라오고, 계약 해제(취소)도 나중에 표시됨)
- 인증키(.env의 APT_API_KEY)가 없으면 아무것도 하지 않음
"""
import time
import threading
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from urllib.parse import unquote

import requests
from config import log_msg, short_err, APT_API_KEY, APT_SYNC_HOURS, APT_BACKFILL_MONTHS, DDNS_URL
import apt_store

API_URL = 'https://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev'
ROWS_PER_PAGE = 1000
MAX_PAGES = 20
REQUEST_TIMEOUT = 30
# 요청 사이 간격(초): 한 번에 몰아 보내지 않게
REQUEST_GAP = 0.3
# 평소에 다시 확인하는 최근 개월 수 (이번 달 포함)
RECENT_MONTHS = 3
# 이보다 오래된 계약이 뒤늦게 올라오면 저장만 하고 알리지는 않음 (일)
ALERT_MAX_AGE_DAYS = 120
# 단지 찾기에서 훑어보는 최근 개월 수 (거래가 드문 단지도 잡히도록 넉넉히)
SEARCH_MONTHS = 12
SEARCH_LIMIT = 30

class AptApiError(Exception):
    """API가 오류를 돌려줌 (인증키 미등록·한도 초과 등)"""

_wake = threading.Event()

def configured():
    return bool(APT_API_KEY)

def _service_key():
    # 포털이 주는 '인코딩된 키'를 넣어도 한 번 더 인코딩되지 않게 원래 값으로
    return unquote(APT_API_KEY) if '%' in APT_API_KEY else APT_API_KEY

def month_list(count, today=None):
    """이번 달부터 거꾸로 count개월 ['202611', '202610', ...]"""
    today = today or date.today()
    year, month = today.year, today.month
    months = []
    for _ in range(count):
        months.append(f'{year}{month:02d}')
        month -= 1
        if month == 0:
            year, month = year - 1, 12
    return months

def _text(item, name):
    return (item.findtext(name) or '').strip()

def _int(value):
    digits = ''.join(ch for ch in str(value or '') if ch.isdigit())
    return int(digits) if digits else None

def parse_trades(xml_text, lawd_cd):
    """API 응답(XML)에서 (거래 목록, 전체 건수). 오류 응답이면 AptApiError.
    거래: lawd_cd, apt_seq(단지 일련번호, 없으면 '동|단지 이름'), apt_name, umd_name, area(전용면적 ㎡), floor,
    amount(만원), deal_date('YYYY-MM-DD'), build_year, canceled, cancel_date, dealing(거래 유형: 중개거래·직거래)"""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        raise AptApiError(f'응답을 읽을 수 없음: {short_err(e)}')
    # 인증키 오류 등은 다른 모양의 응답으로 옴
    if root.tag == 'OpenAPI_ServiceResponse':
        raise AptApiError(root.findtext('.//returnAuthMsg') or root.findtext('.//errMsg') or '알 수 없는 오류')
    code = (root.findtext('.//header/resultCode') or '').strip()
    if code not in ('000', '00'):
        raise AptApiError(f"{root.findtext('.//header/resultMsg') or '오류'} (코드 {code or '없음'})")
    trades = []
    for item in root.iter('item'):
        name, umd = _text(item, 'aptNm'), _text(item, 'umdNm')
        amount, year, month, day = (_int(_text(item, k)) for k in ('dealAmount', 'dealYear', 'dealMonth', 'dealDay'))
        try:
            area = round(float(_text(item, 'excluUseAr')), 2)
        except ValueError:
            area = None
        if not name or not amount or not year or not month or not day or area is None:
            continue
        trades.append({
            'lawd_cd': lawd_cd, 'apt_seq': _text(item, 'aptSeq') or f'{umd}|{name}', 'apt_name': name, 'umd_name': umd,
            'area': area, 'floor': _int(_text(item, 'floor')) or 0, 'amount': amount,
            'deal_date': f'{year:04d}-{month:02d}-{day:02d}', 'build_year': _int(_text(item, 'buildYear')),
            # 계약이 해제된 거래는 cdealType이 'O'
            'canceled': _text(item, 'cdealType').upper() == 'O', 'cancel_date': _text(item, 'cdealDay'),
            'dealing': _text(item, 'dealingGbn'),
        })
    return trades, _int(root.findtext('.//body/totalCount')) or 0

def fetch_month(lawd_cd, deal_ym, get=requests.get):
    """한 시군구의 한 달 거래 전체 (여러 페이지면 모두)"""
    trades = []
    for page in range(1, MAX_PAGES + 1):
        res = get(API_URL, params={'serviceKey': _service_key(), 'LAWD_CD': lawd_cd, 'DEAL_YMD': deal_ym,
                                   'pageNo': page, 'numOfRows': ROWS_PER_PAGE}, timeout=REQUEST_TIMEOUT)
        if res.status_code != 200:
            raise AptApiError(f'HTTP {res.status_code}')
        got, total = parse_trades(res.text, lawd_cd)
        trades += got
        if page * ROWS_PER_PAGE >= total or not got:
            break
        time.sleep(REQUEST_GAP)
    return trades

def search_complexes(lawd_cd, name, fetch=None):
    """관리 화면의 단지 찾기: 그 시군구에서 이름에 name이 들어간 단지 (최근 SEARCH_MONTHS개월 거래 기준).
    [{'apt_seq', 'name', 'umd', 'build_year', 'areas': [전용면적 ㎡ 반올림], 'count', 'last_amount', 'last_date'}]"""
    fetch = fetch or fetch_month
    needle = ''.join(name.split()).casefold()
    found = {}
    for ym in month_list(SEARCH_MONTHS):
        for t in fetch(lawd_cd, ym):
            if needle not in ''.join(t['apt_name'].split()).casefold() or t['canceled']:
                continue
            entry = found.setdefault(t['apt_seq'], {'apt_seq': t['apt_seq'], 'name': t['apt_name'], 'umd': t['umd_name'],
                                                    'build_year': t['build_year'], 'areas': set(), 'count': 0,
                                                    'last_amount': t['amount'], 'last_date': t['deal_date']})
            entry['areas'].add(int(round(t['area'])))
            entry['count'] += 1
            if t['deal_date'] > entry['last_date']:
                entry['last_amount'], entry['last_date'] = t['amount'], t['deal_date']
        time.sleep(REQUEST_GAP)
    results = sorted(found.values(), key=lambda e: (-e['count'], e['name']))[:SEARCH_LIMIT]
    return [{**e, 'areas': sorted(e['areas'])} for e in results]

def format_amount(manwon):
    """만원 단위 금액을 '12억 3,000'처럼 (억 미만은 '9,500만')"""
    eok, rest = divmod(int(manwon), 10000)
    if not eok:
        return f'{rest:,}만'
    return f'{eok}억 {rest:,}' if rest else f'{eok}억'

def build_alert(watch, trade, previous):
    """새 거래 알림 본문(HTML): 단지·면적 / 금액·층·계약일 / 직전 거래 대비"""
    import html
    area = int(round(trade['area']))
    lines = [f"🏠 <b>{html.escape(watch['apt_name'])}</b> {area}㎡ 새 실거래",
             "",
             f"<b>{format_amount(trade['amount'])}</b> · {trade['floor']}층 · {trade['deal_date'][5:7]}/{trade['deal_date'][8:10]} 계약"
             + (f" · {html.escape(trade['dealing'])}" if trade.get('dealing') else '')]
    if previous:
        diff = trade['amount'] - previous['amount']
        change = '변동 없음' if not diff else f"{'▲' if diff > 0 else '▼'} {format_amount(abs(diff))}"
        lines.append(f"직전 {format_amount(previous['amount'])} ({previous['deal_date'][5:7]}/{previous['deal_date'][8:10]}, "
                     f"{previous['floor']}층) 대비 {change}")
    return '\n'.join(lines)

def _watch_url(watch_id):
    import re
    base = re.sub(r'/[^/]*\.html?$', '', (DDNS_URL or '').strip().split('#')[0].split('?')[0]).rstrip('/')
    return f'{base}/apt/#w-{watch_id}' if base.startswith(('http://', 'https://')) else ''

def send_alerts(watches, added):
    """새로 저장한 거래 중 알림을 켠 관심 단지(면적까지 맞는 것)의 거래를 알림. 보낸 수 반환"""
    from notifier import _send_html, _configured
    if not _configured():
        return 0
    oldest = (datetime.now() - timedelta(days=ALERT_MAX_AGE_DAYS)).strftime('%Y-%m-%d')
    sent = 0
    for trade in sorted(added, key=lambda t: t['deal_date']):
        if trade['canceled'] or trade['deal_date'] < oldest:
            continue
        area = int(round(trade['area']))
        watch = next((w for w in watches if w['alert'] and w['synced_at'] and w['lawd_cd'] == trade['lawd_cd']
                      and w['apt_seq'] == trade['apt_seq'] and w['area'] in (None, area)), None)
        if not watch:
            continue
        previous = apt_store.previous_trade(trade['lawd_cd'], trade['apt_seq'], trade['area'], trade['deal_date'])
        url = _watch_url(watch['id'])
        base = {"parse_mode": "HTML"}
        if url:
            base["reply_markup"] = {"inline_keyboard": [[{"text": "📈 실거래가 보기", "url": url}]]}
        _send_html(base, build_alert(watch, trade, previous), "실거래 알림")
        sent += 1
    return sent

def sync_once(fetch=None, alert=None):
    """관심 단지의 거래를 한 번 받아 저장하고 새 거래를 알림. (새로 저장한 거래 수, 알림 수) 반환.
    처음 채우는 단지(synced_at 없음)가 있는 시군구는 지난 APT_BACKFILL_MONTHS개월, 아니면 최근 RECENT_MONTHS개월"""
    fetch, alert = fetch or fetch_month, alert or send_alerts
    watches = apt_store.list_watches()
    if not watches:
        return 0, 0
    total_added, to_alert = 0, []
    for lawd_cd in sorted({w['lawd_cd'] for w in watches}):
        here = [w for w in watches if w['lawd_cd'] == lawd_cd]
        fresh = {w['apt_seq'] for w in here if not w['synced_at']}
        seqs = {w['apt_seq'] for w in here}
        for ym in month_list(APT_BACKFILL_MONTHS if fresh else RECENT_MONTHS):
            recent = ym in month_list(RECENT_MONTHS)
            trades = [t for t in fetch(lawd_cd, ym) if t['apt_seq'] in (seqs if recent else fresh)]
            # 처음 채우는 단지의 거래는 지난 거래로 저장 (새 거래 표시·알림 없음)
            added = apt_store.save_trades([t for t in trades if t['apt_seq'] in fresh], backfill=True)
            added_new = apt_store.save_trades([t for t in trades if t['apt_seq'] not in fresh], backfill=False)
            total_added += len(added) + len(added_new)
            to_alert += added_new
            time.sleep(REQUEST_GAP)
        apt_store.mark_watches_synced([w['id'] for w in here if not w['synced_at']])
    sent = alert(watches, to_alert) if to_alert else 0
    return total_added, sent

def request_sync():
    """관심 단지를 새로 등록했을 때 기다리지 않고 바로 받아 오게 함"""
    _wake.set()

def _run():
    while True:
        try:
            added, sent = sync_once()
            apt_store.set_sync_status(True)
            if added:
                log_msg(f"[실거래] 새로 저장한 거래 {added}건, 알림 {sent}건")
        except Exception as e:
            log_msg(f"[실거래] 수집 실패: {short_err(e)}", "WARN")
            try:
                apt_store.set_sync_status(False, short_err(e))
            except Exception:
                pass
        _wake.wait(APT_SYNC_HOURS * 3600)
        _wake.clear()

def start():
    """수집 작업 시작 (인증키가 있을 때만)"""
    if not configured():
        log_msg("[실거래] APT_API_KEY 미설정 - 실거래가 수집 안 함", "DEBUG")
        return False
    threading.Thread(target=_run, daemon=True).start()
    log_msg(f"[실거래] 실거래가 수집 시작 ({APT_SYNC_HOURS}시간마다)")
    return True
