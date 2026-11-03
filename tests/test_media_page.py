import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT
import tempfile, sqlite3
os.environ.update(OUTPUT_DIR=tempfile.mkdtemp(), LOG_LEVEL='CRITICAL', TELEGRAM_TOKEN='')
for name in [k for k in os.environ if k.startswith('KEYWORDS_')]:
    os.environ[name] = ''
import storage, web_server, config

storage.init_db()
storage.save_group(None, '싼타페', [{'board': 'car', 'keyword': '싼타페'}])
img = lambda n: f'<img alt="" src="https://image.fmkorea.com/files/attach/new5/{n}.jpg" width="800"/>'
def save(pid, content, videos=()):
    storage.save_keyword_post('car', '싼타페', {'id': pid, 'title': f'글 {pid}', 'author': 'a', 'date': 'd', 'views': '1', 'votes': '0',
                                                'comment_count': '0', 'link': f'/{pid}', 'content': content,
                                                'videos': list(videos), 'comments': []}, is_new=True)

# --- 1) 모아보기용 이미지: 첨부·저장한 디시 이미지만, 중복·이모티콘 제외. 동영상은 유튜브·파일·그 밖으로
assert storage.post_images([img('a'), img('a'), '<img src="https://www.fmkorea.com/modules/emoticon/x.gif">',
                            '<img src="/images/dc-x-1/0-0123456789.jpg">', '<img src="//image.fmkorea.com/files/attach/b.png?x=1&amp;y=2">']) == [
    'https://image.fmkorea.com/files/attach/new5/a.jpg', '/images/dc-x-1/0-0123456789.jpg', 'https://image.fmkorea.com/files/attach/b.png?x=1&y=2']
assert [v['type'] for v in storage.post_videos(['https://www.youtube.com/embed/_MUk-aKNZbQ?x=1', 'https://m.fmkorea.com/v.mp4',
                                                 'https://gall.dcinside.com/player?no=1', '/relative'])] == ['youtube', 'file', 'embed']
print('MEDIA PARSE OK')

# --- 2) 페이지는 글이 아니라 이미지 개수로: 5장·0장·3장·4장 글 → 12장, 5장씩 나누면 5·5·2 (글 경계와 무관)
save('901', [img(f'a{i}') for i in range(5)])
save('902', ['<p>글만</p>'])
save('903', [img(f'b{i}') for i in range(3)], ['https://m.fmkorea.com/v.mp4'])
save('904', [img(f'c{i}') for i in range(4)])
pages = [web_server.build_media_page(p, 'image', 5) for p in (1, 2, 3)]
assert [p['total'] for p in pages] == [12] * 3 and pages[0]['total_pages'] == 3
assert [len(p['items']) for p in pages] == [5, 5, 2]
flat = [(i['post']['id'], i['index'], i['of']) for p in pages for i in p['items']]
assert flat == [('904', 1, 4), ('904', 2, 4), ('904', 3, 4), ('904', 4, 4), ('903', 1, 3),
                ('903', 2, 3), ('903', 3, 3), ('901', 1, 5), ('901', 2, 5), ('901', 3, 5), ('901', 4, 5), ('901', 5, 5)], flat
assert pages[0]['items'][0]['post']['keywords'] == [{'board': 'car', 'keyword': '싼타페', 'board_name': '자동차'}]
video = web_server.build_media_page(9, 'video', 6)
assert video['total'] == 1 and video['page'] == 1 and video['items'][0]['type'] == 'file'
print('MEDIA PAGE OK')

# --- 3) 기존 DB: 개수 칸이 없던 글은 처음 한 번 본문에서 계산
with sqlite3.connect(config.DB_FILE) as db:
    db.execute("UPDATE posts SET image_count = 0, video_count = 0")
    db.execute("DELETE FROM meta WHERE key = 'media_counts_backfilled'")
storage._initialized = False
storage.init_db()
with sqlite3.connect(config.DB_FILE) as db:
    assert dict(db.execute("SELECT id, image_count FROM posts")) == {'901': 5, '902': 0, '903': 3, '904': 4}
    assert db.execute("SELECT video_count FROM posts WHERE id = '903'").fetchone()[0] == 1
print('BACKFILL OK')
