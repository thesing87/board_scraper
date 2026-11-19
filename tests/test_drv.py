"""수집 연결: 크롬 없이 HTTP 요청(dcinside.DcClient). 예전 크롬 관리 함수 자리는 그대로 두되 하는 일만 바뀜"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT
import tempfile, importlib.util
os.environ['OUTPUT_DIR'] = tempfile.mkdtemp()
spec = importlib.util.spec_from_file_location('m', os.path.join(ROOT, 'app', 'fmkorea-scraper.py'))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
import dcinside

client = m.create_driver()
assert isinstance(client, dcinside.DcClient)
assert 'Chrome/' in client.session.headers['User-Agent'] and client.session.headers['Accept-Language'].startswith('ko')
# 연결은 멈추거나 죽지 않으므로 그대로 씀, 쉬는 동안 정리할 메모리도 없음
assert m.ensure_driver_alive(client) is client and m.restart_if_hung(client) is client
assert m.release_chrome_memory(client) is None
# 정기 갱신: 예전 연결은 닫고 새 연결
closed = []
client.close = lambda: closed.append(1)
fresh = m.restart_driver(client)
assert closed == [1] and isinstance(fresh, dcinside.DcClient) and fresh is not client
# 수집기는 셀레늄을 불러오지 않음
src = open(os.path.join(ROOT, 'app', 'fmkorea-scraper.py'), encoding='utf-8').read() + open(os.path.join(ROOT, 'app', 'dcinside.py'), encoding='utf-8').read()
assert 'selenium' not in src
print('DRIVER OK')
