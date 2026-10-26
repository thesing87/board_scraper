import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, DATA_DIR, LIVE_URL, shot_dir
import os, tempfile, sys
os.environ['OUTPUT_DIR'] = tempfile.mkdtemp()
import scraper

class D:
    def __init__(self, html): self.page_source = html
    def get(self, url): pass

scraper.WebDriverWait = lambda d, t: type('W', (), {'until': lambda self, c: True})()
scraper.time.sleep = lambda s: None
info = {'link': 'x', 'title': 't', 'author': 'a', 'date': 'd', 'id': '1'}
# 실제 삭제 글 페이지 문구
assert scraper.scrape_post_detail(D('<title>삭제된 글입니다. - 에펨코리아</title><body>해당 문서가 존재하지 않습니다.</body>'), info) is None
# 정상 글 본문에 같은 문구가 있어도 삭제로 보지 않음
assert scraper.scrape_post_detail(D('<div class="xe_content">이 기능은 존재하지 않습니다 삭제된 글입니다</div>'), info) is not None
print('DELETE DETECT OK')
