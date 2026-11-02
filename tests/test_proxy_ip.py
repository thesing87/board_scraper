import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT
import tempfile, threading, json, socket, urllib.request, urllib.error
os.environ.update(OUTPUT_DIR=tempfile.mkdtemp(), LOG_LEVEL='CRITICAL', ADMIN_PASSWORD='Secr3t!', TELEGRAM_TOKEN='',
                  TRUST_PROXY_HEADERS='1')
for name in [k for k in os.environ if k.startswith('KEYWORDS_')]:
    os.environ[name] = ''
import web_server
from web_server import client_ip

# --- 1) 접속자 IP 판별: 프록시(내부 주소)가 넘겨 준 실제 IP, 꾸민 앞쪽 값은 무시
assert client_ip('172.18.0.1', {'X-Real-IP': '203.0.113.7'}) == '203.0.113.7'
assert client_ip('172.18.0.1', {'X-Forwarded-For': '1.1.1.1, 203.0.113.7'}) == '203.0.113.7'
assert client_ip('172.18.0.1', {}) == '172.18.0.1'
assert client_ip('172.18.0.1', {'X-Real-IP': 'not-an-ip'}) == '172.18.0.1'
# 인터넷 주소에서 바로 온 요청은 헤더를 믿지 않음, 설정을 끄면 항상 연결 주소
assert client_ip('8.8.8.8', {'X-Real-IP': '203.0.113.7'}) == '8.8.8.8'
assert client_ip('172.18.0.1', {'X-Real-IP': '203.0.113.7'}, trust_proxy=False) == '172.18.0.1'
print('CLIENT IP OK')

# --- 2) 한 접속자가 암호를 5번 틀려 잠겨도 다른 접속자는 관리 기능을 그대로 씀
with socket.socket() as s:
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
srv = web_server.ThreadedHTTPServer(('127.0.0.1', port), web_server.KeywordAPIServer)
threading.Thread(target=srv.serve_forever, daemon=True).start()

def toggle(password, real_ip):
    body = json.dumps({'group': 999, 'type': 'alert', 'enabled': True, 'password': password}).encode()
    req = urllib.request.Request(f'http://127.0.0.1:{port}/api/toggle-alert', data=body, method='POST',
                                 headers={'Content-Type': 'application/json', 'X-Real-IP': real_ip})
    try:
        with urllib.request.urlopen(req) as res:
            return res.status
    except urllib.error.HTTPError as e:
        return e.code

codes = [toggle('wrong', '203.0.113.7') for _ in range(5)]
assert codes == [401] * 5, codes
assert toggle('Secr3t!', '203.0.113.7') == 429          # 틀린 사람은 맞는 암호도 잠시 거부
assert toggle('Secr3t!', '198.51.100.20') == 400        # 다른 사람은 인증 통과 (없는 게시판이라 400)
srv.shutdown()
print('PROXY LOCKOUT OK')
