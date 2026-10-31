import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT
import tempfile
os.environ.update(OUTPUT_DIR=tempfile.mkdtemp(), ADMIN_PASSWORD='Secr3t!', TELEGRAM_TOKEN='', LOG_LEVEL='WARN')
import config
# 로컬 .env의 KEYWORDS_* (config가 불러옴)가 새 DB에 같은 이름의 게시판을 미리 만들지 않게 비움
for name in [k for k in os.environ if k.startswith('KEYWORDS_')]:
    os.environ[name] = ''
from bs4 import BeautifulSoup
import storage, web_server, sites, dcinside

# --- 1) 사이트 구분: 카테고리 키·글 ID
assert sites.board_site('car') == 'fmkorea' and sites.board_site('dc:car_new1') == 'dcinside'
assert sites.post_site('10482627360') == 'fmkorea' and sites.post_site('dc-car_new1-11561402') == 'dcinside'
assert sites.dc_post_id('car_new1', '11561402') == 'dc-car_new1-11561402'
assert sites.post_number('dc-car_new1-11561402') == 11561402 and sites.post_number('10482627360') == 10482627360
assert sites.is_post_id('10482627360') and sites.is_post_id('dc-car_new1-11561402')
assert not any(sites.is_post_id(v) for v in ('', 'abc', 'dc-car_new1-', "1' OR 1=1", 'dc-Car-1', None))
print('SITES OK')

# --- 2) 관리 화면 입력 → 카테고리 키
key = web_server.board_key_from_input
assert key('https://gall.dcinside.com/board/lists/?id=car_new1') == 'dc:car_new1'
assert key('gall.dcinside.com/board/view/?id=car_new1&no=11561402&page=1') == 'dc:car_new1'
assert key('dc:Car_New1') == 'dc:car_new1'
assert key('https://gall.dcinside.com/mgallery/board/lists/?id=rezero') is None   # 마이너 갤러리는 아직 미지원
assert key('https://gall.dcinside.com/board/lists/') is None
assert key('https://www.fmkorea.com/hotdeal') == 'hotdeal' and key('car') == 'car'
assert key('https://example.com/board/lists/?id=car_new1') is None
print('INPUT OK')

# --- 3) 목록 표: 공지·광고 행은 빼고 글만, 제목의 검색어 강조 태그는 이어 붙임
LIST_HTML = """
<table class="gall_list"><tbody>
<tr class="ub-content us-post" data-no="1" data-type="icon_notice"><td class="gall_num">공지</td>
  <td class="gall_tit"><a href="/board/view/?id=car_new1&no=1">자동차 갤러리 이용 안내</a></td></tr>
<tr class="ub-content"><td class="gall_num">AD</td><td class="gall_tit"><a href="javascript:;">광고</a></td></tr>
<tr class="ub-content us-post" data-no="11561402" data-type="icon_txt"><td class="gall_num">11561402</td>
  <td class="gall_tit"><a href="/board/view/?id=car_new1&no=11561402">하도 <b>싼타페</b>랑 투싼 비교</a>
    <a class="reply_numbox" href="#"><span class="reply_num">[3/1]</span></a></td>
  <td class="gall_writer ub-writer" data-nick="차갤러" data-uid="" data-ip="175.117"></td>
  <td class="gall_date" title="2026-10-30 22:49:08">22:49</td><td class="gall_count">1,041</td><td class="gall_recommend">2</td></tr>
<tr class="ub-content us-post" data-no="11561149" data-type="icon_pic"><td class="gall_num">11561149</td>
  <td class="gall_tit"><a href="/board/view/?id=car_new1&no=11561149">6천선에서 추천좀</a></td>
  <td class="gall_writer ub-writer" data-nick="고닉" data-uid="someone" data-ip=""></td>
  <td class="gall_date" title="2026-10-30 18:14:33">18:14</td><td class="gall_count">7</td><td class="gall_recommend">0</td></tr>
</tbody></table>"""
rows = dcinside._parse_list_rows(BeautifulSoup(LIST_HTML, 'html.parser'), 'car_new1')
assert [r['id'] for r in rows] == ['dc-car_new1-11561402', 'dc-car_new1-11561149'], rows
first = rows[0]
assert first['title'] == '하도 싼타페랑 투싼 비교', first
assert first['link'] == 'https://gall.dcinside.com/board/view/?id=car_new1&no=11561402'
assert first['author'] == '차갤러(175.117)' and rows[1]['author'] == '고닉'
assert first['date'] == '2026-10-30 22:49:08'
assert (first['list_comment_count'], first['list_views'], first['list_votes']) == (3, '1041', '2'), first
assert rows[1]['list_comment_count'] == 0
assert dcinside.gallery_title('자동차 갤러리 - 커뮤니티 포털 디시인사이드') == '자동차 갤러리'
print('LIST OK')

# --- 4) 댓글: 댓글 뒤 형제 li의 .reply_list가 답글, 광고(dory·파워링크)는 빼고 디시콘은 표시만
COMMENT_HTML = """
<ul class="cmt_list">
<li id="comment_li_1" class="ub-content"><div class="cmt_info">
  <span class="gall_writer ub-writer" data-nick="ㅇㅇ" data-ip="58.29"></span>
  <p class="usertxt ub-word">투싼 인스퍼레이션<br>살 바에는</p><span class="date_time">10.29 22:50:41</span></div></li>
<li><div class="reply"><ul class="reply_list">
  <li id="reply_li_2" class="ub-content"><div class="reply_info">
    <span class="gall_writer ub-writer" data-nick="차갤러1" data-ip="223.39"></span>
    <p class="usertxt ub-word">동의</p><span class="date_time">10.29 22:51:04</span></div></li>
</ul></div></li>
<li id="comment_li_0" class="ub-content dory"><div class="cmt_info">광고</div></li>
<li class="power_link cmt_power_link">파워링크</li>
<li id="comment_li_3" class="ub-content"><div class="cmt_info">
  <span class="gall_writer ub-writer" data-nick="고닉" data-ip=""></span>
  <img class="written_dccon" src="https://dcimg5.dcinside.com/dccon.php?no=1"><span class="date_time">10.29 23:05:49</span></div></li>
</ul>"""
comments = dcinside._parse_comments(BeautifulSoup(COMMENT_HTML, 'html.parser'))
assert [(c['author'], c['is_reply'], c['depth']) for c in comments] == [
    ('ㅇㅇ(58.29)', False, 0), ('차갤러1(223.39)', True, 1), ('고닉', False, 0)], comments
assert comments[0]['content'] == ['투싼 인스퍼레이션', '살 바에는'] and comments[0]['date'] == '10.29 22:50:41'
assert comments[2]['content'] == ['(디시콘)']
print('COMMENTS OK')

# --- 5) 게시판에는 한 사이트의 키워드만, 게시판 목록에 사이트 표시
storage.init_db()
storage.add_category('dc:car_new1')
storage.set_category_checked('dc:car_new1', True, page_name='자동차 갤러리')
assert next(c for c in storage.list_categories() if c['key'] == 'dc:car_new1')['site'] == 'dcinside'
try:
    storage.save_group(None, '섞인 게시판', [{'board': 'car', 'keyword': '싼타페'}, {'board': 'dc:car_new1', 'keyword': '싼타페'}])
    raise AssertionError('사이트가 섞인 게시판이 저장됨')
except ValueError as e:
    assert '한 사이트' in str(e), e
dc_id, _ = storage.save_group(None, '디시 싼타페', [{'board': 'dc:car_new1', 'keyword': '싼타페'}])
fm_id, _ = storage.save_group(None, '에펨 싼타페', [{'board': 'car', 'keyword': '싼타페'}])
sites_by_name = {g['name']: g['site'] for g in storage.list_groups()}
assert sites_by_name['디시 싼타페'] == 'dcinside' and sites_by_name['에펨 싼타페'] == 'fmkorea', sites_by_name
assert storage.load_keywords()['dc:car_new1'] == ['싼타페']

# 디시 글 저장·읽음·위치 찾기 (글 ID에 '-'가 들어가도 동작)
post = {'id': 'dc-car_new1-11561402', 'title': '싼타페 견적', 'author': '차갤러(175.117)', 'date': '2026-10-30 22:49:08',
        'views': '41', 'votes': '0', 'comment_count': '0', 'link': 'https://gall.dcinside.com/board/view/?id=car_new1&no=11561402',
        'content': ['<p>싼타페 견적 봤는데</p>'], 'videos': [], 'comments': []}
storage.save_keyword_post('dc:car_new1', '싼타페', post, is_new=True)
assert storage.post_exists('dc-car_new1-11561402')
assert storage.recent_keyword_posts('dc:car_new1', '싼타페', 10)[0]['id'] == 'dc-car_new1-11561402'
assert storage.query_posts_by_ids(['dc-car_new1-11561402'])[0]['title'] == '싼타페 견적'
assert storage.mark_posts_read(['dc-car_new1-11561402', "x' OR 1=1"]) == 1
assert storage.locate_post('dc-car_new1-11561402') is not None
print('STORAGE OK')

# --- 6) 텔레그램 새 글 알림: 첫 줄 맨 앞에 사이트 표시 ([DC]·[FM])
import notifier
dc_alert = notifier.build_post_alert(post, ['디시 싼타페'], '싼타페', '자동차 갤러리')
fm_alert = notifier.build_post_alert({**post, 'id': '10482627360', 'videos': ['v']}, ['싼타페'], '싼타페', '자동차')
assert dc_alert.startswith('🔔 [DC] <b>디시 싼타페</b> · '), dc_alert
assert fm_alert.startswith('🎬 [FM] <b>싼타페</b> · 동영상 · '), fm_alert
print('ALERT OK')

# --- 7) 사이트 이름·짧은 표시 편집: 저장한 값이 화면 상태와 알림에 쓰이고, 없는 사이트는 거부
assert storage.site_labels()['dcinside'] == {'name': '디시인사이드', 'short': 'DC'}
storage.set_site_label('dcinside', '디시', 'DCI')
assert storage.site_labels()['dcinside'] == {'name': '디시', 'short': 'DCI'}
assert storage.site_labels()['fmkorea'] == {'name': '에펨코리아', 'short': 'FM'}
assert web_server.build_state()['sites']['dcinside']['short'] == 'DCI'
assert notifier.build_post_alert(post, ['디시 싼타페'], '싼타페', '자동차 갤러리').startswith('🔔 [DCI] ')
try:
    storage.set_site_label('naver', '네이버', 'NV')
    raise AssertionError('없는 사이트 이름이 저장됨')
except ValueError:
    pass
print('SITE LABELS OK')

# --- 8) 게시판 이름은 사이트 안에서만 겹치지 않으면 됨 (FM 싼타페·DC 싼타페)
storage.set_site_label('dcinside', '디시인사이드', 'DC')
fm_santafe, _ = storage.save_group(None, '싼타페', [{'board': 'car', 'keyword': '싼타페'}])
storage.save_group(dc_id, '싼타페', [{'board': 'dc:car_new1', 'keyword': '싼타페'}])   # DC 게시판 이름을 FM과 같게 수정
same = sorted((g['site'], g['id']) for g in storage.list_groups() if g['name'] == '싼타페')
assert same == sorted([('fmkorea', fm_santafe), ('dcinside', dc_id)]), same
for group_id, members, message in [
        (None, [{'board': 'dc:car_new1', 'keyword': '투싼'}], '디시인사이드에 같은 이름'),       # 같은 사이트 안에서는 중복 불가
        (dc_id, [{'board': 'car', 'keyword': '싼타페'}], '다른 사이트의 키워드로')]:            # 게시판의 사이트는 바꿀 수 없음
    try:
        storage.save_group(group_id, '싼타페', members)
        raise AssertionError(f'저장되면 안 됨: {message}')
    except ValueError as e:
        assert message in str(e), e

# 예전 DB(게시판 이름이 전체에서 UNIQUE, 사이트 칸 없음)를 열면 표를 새로 만들어 옮기고, 키워드·알림 설정은 그대로
import sqlite3
legacy_dir = tempfile.mkdtemp()
legacy = sqlite3.connect(os.path.join(legacy_dir, 'board.db'))
legacy.executescript("""
    CREATE TABLE keyword_groups (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL,
                                 alert INTEGER NOT NULL DEFAULT 1, video_alert INTEGER NOT NULL DEFAULT 1);
    CREATE TABLE keyword_group_members (group_id INTEGER NOT NULL REFERENCES keyword_groups(id) ON DELETE CASCADE,
                                        board TEXT NOT NULL, keyword TEXT NOT NULL, PRIMARY KEY (group_id, board, keyword));
    INSERT INTO keyword_groups(id, name, created_at, alert, video_alert) VALUES (1, '싼타페', 't', 0, 1), (2, 'DC 싼타페', 't', 1, 0);
    INSERT INTO keyword_group_members VALUES (1, 'car', '싼타페'), (2, 'dc:car_new1', '싼타페');
""")
legacy.commit()
legacy.close()
conn = sqlite3.connect(os.path.join(legacy_dir, 'board.db'))
conn.row_factory = sqlite3.Row
conn.execute("PRAGMA foreign_keys = ON")
storage._add_group_site(conn)
rows = [tuple(r) for r in conn.execute("SELECT id, site, name, alert, video_alert FROM keyword_groups ORDER BY id")]
assert rows == [(1, 'fmkorea', '싼타페', 0, 1), (2, 'dcinside', 'DC 싼타페', 1, 0)], rows
assert conn.execute("SELECT COUNT(*) FROM keyword_group_members").fetchone()[0] == 2
conn.execute("UPDATE keyword_groups SET name = '싼타페' WHERE id = 2")     # 옮긴 뒤에는 사이트가 다르면 같은 이름 가능
conn.commit()
print('SAME NAME OK')

# --- 9) 사이트 전체 게시판: 그 사이트의 모든 게시판 글만, 사이트끼리 겹치지 않으므로 합이 전체와 같음
storage.save_keyword_post('dc:car_new1', '싼타페', {**post, 'id': 'dc-car_new1-11561500', 'title': '싼타페 새 글'}, is_new=True)
per_site = storage.site_feed_summaries()
assert set(per_site) == {'fmkorea', 'dcinside'} and 'dc-car_new1-11561500' in per_site['dcinside']['unread_ids'], per_site
assert all(not i.startswith('dc-') for i in per_site['fmkorea']['unread_ids'])
for field in ('total', 'unread_count'):
    assert sum(v[field] for v in per_site.values()) == storage.feed_summary()[field], field
assert web_server.build_state()['site_feeds']['dcinside']['unread_count'] == per_site['dcinside']['unread_count']
total, rows = storage.query_all_posts(0, 50, site='dcinside')
assert total == per_site['dcinside']['total'] and rows and all(r['id'].startswith('dc-') for r in rows), (total, rows)
page = web_server.build_posts_page(1, False, site='dcinside')
assert page['total'] == total and all(p['id'].startswith('dc-') for p in page['posts'])
print('SITE FEED OK')

# --- 10) 저장한 디시 이미지: 형식 판별, 저장 주소, 웹서버 경로 검사, 정리된 글의 폴더 삭제
import images
jpg = bytes([0xFF, 0xD8, 0xFF, 0xE0]) + b'0' * 100
assert images.image_ext(jpg) == 'jpg' and images.image_ext(b'<html>') is None
url = images.save_post_image('dc-car_new1-11561402', 0, jpg)
assert url and url.startswith('/images/dc-car_new1-11561402/0-') and url.endswith('.jpg'), url
assert images.save_post_image('dc-car_new1-11561402', 1, b'<html>not image</html>') is None
path, ctype = images.image_file(url[len('/images/'):])
assert ctype == 'image/jpeg' and open(path, 'rb').read() == jpg
for bad in ('../board.db', 'dc-car_new1-11561402/../../board.db', 'dc-car_new1-11561402/0.jpg', 'x/0-0123456789.exe'):
    assert images.image_file(bad) is None, bad
images.save_post_image('dc-car_new1-99999999', 0, jpg)          # DB에 없는 글
assert images.remove_orphan_image_dirs(storage.existing_post_ids) == 1
assert images.image_file(url[len('/images/'):]) is not None      # DB에 있는 글의 이미지는 남음
print('IMAGES OK')

# --- 11) 텔레그램 새 글 알림: 디시 글은 NAS에 저장된 본문 이미지를 파일로 올려 사진 알림, 미리보기에서 원문 링크 문구는 뺌
calls = []
class FakeRes:
    status_code = 200
    text = 'ok'
def fake_post(url, json=None, data=None, files=None, timeout=None):
    calls.append({'method': url.rsplit('/', 1)[1], 'json': json, 'data': data,
                  'file': (files['photo'][0], files['photo'][1].read(), files['photo'][2]) if files else None})
    return FakeRes()
notifier.requests.post = fake_post
notifier.TELEGRAM_TOKEN, notifier.TELEGRAM_CHAT_ID = 'TEST', '1'
dc_post = {**post, 'content': ['<p>견적 받아봄</p>', f'<img alt="첨부이미지" src="{url}"/>',
                               '<a href="https://gall.dcinside.com/x">[이미지 2 · 원문에서 보기]</a>']}
notifier.send_post_alert(dc_post, ['싼타페'], '싼타페', '자동차 갤러리', 'http://x/#post-1', dc_post['link'])
assert [c['method'] for c in calls] == ['sendPhoto'] and calls[0]['file'][1] == jpg and calls[0]['file'][2] == 'image/jpeg', calls
caption = calls[0]['data']['caption']
assert caption.startswith('🔔 [DC] ') and '견적 받아봄' in caption and '원문에서 보기' not in caption, caption
assert '대시보드' in calls[0]['data']['reply_markup'] and calls[0]['data']['parse_mode'] == 'HTML'
# 저장 이미지가 없는 디시 글은 글자 알림
calls.clear()
notifier.send_post_alert({**post, 'content': ['<p>글만 있음</p>']}, ['싼타페'], '싼타페', '자동차 갤러리')
assert [c['method'] for c in calls] == ['sendMessage'] and calls[0]['file'] is None, calls
print('ALERT PHOTO OK')

# --- 12) 이미지 보기: 첨부 이미지(에펨코리아 /files/attach/, 저장한 디시 /images/dc-)가 있는 글만, 이모티콘·링크 그림만 있는 글은 제외
def img_post(pid, content):
    return {**post, 'id': pid, 'title': '이미지 시험 ' + pid, 'content': content}
storage.save_keyword_post('car', '싼타페', img_post('20000000001', ['<img src="https://image.fmkorea.com/files/attach/new5/a.jpg"/>']), is_new=True)
storage.save_keyword_post('dc:car_new1', '싼타페', img_post('dc-car_new1-20000002', [f'<img src="{url}"/>']), is_new=True)
storage.save_keyword_post('car', '싼타페', img_post('20000000003', ['<img src="https://image.fmkorea.com/emoticon/smile.gif"/>']), is_new=True)
storage.save_keyword_post('car', '싼타페', img_post('20000000004', ['<p>글만</p>']), is_new=True)
total, rows = storage.query_all_posts(0, 100, image_only=True)
ids = {r['id'] for r in rows}
assert {'20000000001', 'dc-car_new1-20000002'} <= ids and not ids & {'20000000003', '20000000004'}, ids
assert storage.feed_summary()['image_count'] == total
assert storage.site_feed_summaries()['dcinside']['image_count'] >= 1
assert web_server.build_posts_page(1, False, image_only=True)['total'] == total
print('IMAGE FILTER OK')

# --- 13) 이미지 주소 차단 때문에 '삭제된 이미지콘' 그림으로 저장된 글은 기동 시 1회 다시 수집할 목록에 오름
storage.save_keyword_post('car', '싼타페', img_post('20000000005', [
    '<img class="imagecon" src="https://www.fmkorea.com/modules/imagecon/tpl/img/imagecon_deleted.svg"/>']), is_new=True)
# 댓글에만 '삭제된 이미지콘'이 있는 글도 대상
storage.save_keyword_post('car', '싼타페', {**img_post('20000000006', ['<p>본문</p>']), 'comments': [
    {'author': 'a', 'date': 'd', 'votes': '0', 'content': ['<img src="https://www.fmkorea.com/modules/imagecon/tpl/img/imagecon_deleted.svg"/>'],
     'is_reply': False}]}, is_new=True)
targets = storage.posts_with_blocked_imagecons()
assert sorted(t['id'] for t in targets) == ['20000000005', '20000000006'] and targets[0]['link'], targets
storage.mark_blocked_imagecons_refetched()
assert storage.posts_with_blocked_imagecons() == []
print('IMAGECON REFETCH OK')
print('DCINSIDE OK')
