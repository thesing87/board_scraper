import os
import time
import sys
import threading
import traceback
from datetime import date, datetime
from selenium.webdriver import Chrome
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options

from config import (
    log_msg,
    short_err,
    CHECK_INTERVAL,
    DDNS_URL,
    MAX_DATA_PER_KEYWORD,
    RETENTION_DAYS,
    BACKUP_KEEP,
    BACKUP_DIR,
    CHROME_RESTART_CYCLES,
    IS_LINUX
)
from storage import (
    init_db,
    load_keywords,
    category_names,
    pending_categories,
    set_category_checked,
    load_alert_targets,
    load_keyword_ignores,
    recent_keyword_posts,
    save_keyword_post,
    update_post,
    update_list_stats,
    mark_post_deleted,
    fix_stored_x_embeds,
    replace_stored_x_cards,
    remove_stored_duplicate_instagram_placeholders,
    remove_stored_sns_videos,
    post_exists,
    backup_db,
    prune_old_posts,
    existing_post_ids,
    posts_with_blocked_imagecons,
    mark_blocked_imagecons_refetched,
    site_labels
)
from images import remove_orphan_image_dirs
from notifier import send_telegram_message, send_post_alert
from scraper import parse_count, BlockedError
# 목록·상세·게시판 확인은 카테고리(글)의 사이트에 맞는 수집기(에펨코리아·디시인사이드)로
from sites import (
    get_list_page_posts,
    scrape_post_detail,
    check_board,
    board_site,
    post_number,
    SITE_NAMES
)
from matching import keyword_in_post
from web_server import run_api_server
import runtime_status

# 변경이 없는 주기는 요약 로그를 남기지 않으므로, 살아있음을 알리는 상태 로그 간격
HEARTBEAT_SECONDS = 3600
# 목록에서 사라진 글(삭제 의심)을 키워드당 한 주기에 확인하는 최대 개수
DELETION_CHECKS_PER_KEYWORD = 3
# 차단이 의심되면 대기 시간을 주기 x 2, x 4, x 8 ... 로 늘리되 이 값을 넘기지 않음
BACKOFF_MAX_SECONDS = 3600

try:
    if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
        sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

# 이미지는 받지 않아 메모리·전송량을 아끼되, 디시 페이지에서만 받게 해서 디시 수집기가 크롬이 받은 본문 이미지 파일을
# 꺼내 저장할 수 있게 함 (images.py). 크롬의 사이트별 이미지 설정을 써서 다른 사이트의 이미지는 아예 요청하지 않음.
# (주소를 막는 방식은 이미지 '불러오기 실패'가 되어, 에펨코리아 페이지가 이미지콘을 '삭제된 이미지콘' 그림으로 바꿔 버림)
IMAGE_PREFS = {
    'profile.default_content_setting_values.images': 2,
    'profile.content_settings.exceptions.images': {'[*.]dcinside.com,*': {'setting': 1}},
}

def create_driver():
    options = Options()
    options.page_load_strategy = 'eager'
    options.add_experimental_option('prefs', IMAGE_PREFS)
    # 메모리를 덜 쓰도록 수집에 필요 없는 기능은 끔 (NAS 메모리가 1.8GB라 크롬이 커지면 스왑으로 전체가 느려짐)
    for arg in ('--disable-extensions', '--disable-background-networking', '--disable-component-update',
                '--disable-sync', '--disable-default-apps', '--mute-audio', '--renderer-process-limit=2',
                '--disable-features=Translate,OptimizationHints,MediaRouter,AutofillServerCommunication'):
        options.add_argument(arg)
    services = Service()
    if IS_LINUX:
        options.add_argument('--headless=new')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-gpu')

    driver = Chrome(options=options, service=services)
    # 크롬 개발자 도구(CDP): 받은 파일 꺼내기(Page.getResourceContent)에 씀
    driver.execute_cdp_cmd('Page.enable', {})
    runtime_status.update(chrome_started_at=runtime_status.now())
    log_msg(f"[시스템] 크롬 드라이버 준비 완료{' (headless)' if IS_LINUX else ''}")
    return driver

def ensure_driver_alive(driver):
    """크롬 프로세스가 죽었으면(OOM 등) 드라이버를 새로 생성하여 반환"""
    try:
        driver.execute_script("return 1")
        return driver
    except Exception as health_err:
        log_msg(f"[시스템] 크롬 응답 없음 → 재시작: {short_err(health_err)}", "WARN")
    runtime_status.increment('chrome_restarts')
    try:
        driver.quit()
    except Exception:
        pass
    return create_driver()

def sync_existing_posts(driver, target, list_posts, board_data, stats, verified_present):
    """목록 페이지 값과 저장된 값을 비교해, 댓글 수가 바뀐 글만 상세 페이지를 다시 열어 갱신하고
    목록에서 사라진 글은 삭제 여부를 확인. 상세 페이지 요청을 변화가 있을 때로만 줄이는 것이 목적"""
    stored = {p['id']: p for p in board_data}
    listed_ids = set()

    for item in list_posts:
        listed_ids.add(item['id'])
        old = stored.get(item['id'])
        if old is None or old.get('is_deleted'):
            continue
        prev = old.get('list_comment_count')
        if prev is None:
            # 목록 댓글 수가 아직 없는(이전 방식으로 저장된) 글은 상세 페이지 기준 댓글 수와 한 번 비교
            prev = parse_count(old.get('comment_count'))

        # 제목이 바뀌었으면 작성자가 글을 수정한 것 → 본문(교체된 이미지 등)도 다시 받음
        title_changed = bool(item['title']) and item['title'] != old.get('title')
        if item['list_comment_count'] != prev or title_changed:
            try:
                stats['details'] += 1
                updated = scrape_post_detail(driver, {**old, 'title': item['title'] or old.get('title')})
                if updated is None:
                    mark_post_deleted(old['id'])
                    stats['deleted'] += 1
                    log_msg(f"[삭제] {target} #{old['id']} 원문 삭제됨 (보존 처리)")
                    continue
                updated['list_comment_count'] = item['list_comment_count']
                update_post(updated)
                stats['updated'] += 1
                log_msg(f"[갱신] {target} #{old['id']} 댓글 {prev}→{item['list_comment_count']}, 추천 {updated['votes']}"
                        + (" (제목 수정됨)" if title_changed else ""), "DEBUG")
            except Exception as sync_ex:
                stats['errors'] += 1
                log_msg(f"[오류] {target} #{old['id']} 갱신 실패: {short_err(sync_ex)}", "WARN")
        elif (old.get('list_comment_count') is None or
              (item['list_views'] and item['list_views'] != old.get('views')) or
              (item['list_votes'] and item['list_votes'] != old.get('votes'))):
            # 댓글 변화가 없으면 조회·추천 수만 목록 값으로 반영 (상세 페이지 요청 없음)
            update_list_stats(item['id'], item['list_views'], item['list_votes'], item['list_comment_count'])

    # 목록에 있어야 할 범위(목록의 가장 오래된 글보다 최신)인데 목록에서 사라진 글은 삭제됐을 가능성이 있어 확인
    if not list_posts:
        return
    oldest_listed = min(post_number(item['id']) for item in list_posts)
    missing = [p for p in board_data
               if not p.get('is_deleted') and p['id'] not in listed_ids
               and post_number(p['id']) > oldest_listed and p['id'] not in verified_present]
    for old in missing[:DELETION_CHECKS_PER_KEYWORD]:
        try:
            stats['details'] += 1
            if scrape_post_detail(driver, old) is None:
                mark_post_deleted(old['id'])
                stats['deleted'] += 1
                log_msg(f"[삭제] {target} #{old['id']} 원문 삭제됨 (보존 처리)")
            else:
                # 제목·본문 수정으로 검색에서 빠진 글 등. 이번 실행 중에는 다시 확인하지 않음
                verified_present.add(old['id'])
                log_msg(f"[수집] {target} #{old['id']} 목록에서 빠졌지만 원문은 존재", "DEBUG")
        except Exception as check_ex:
            stats['errors'] += 1
            log_msg(f"[오류] {target} #{old['id']} 삭제 확인 실패: {short_err(check_ex)}", "WARN")

def restart_driver(driver):
    """오래 띄워 둔 크롬은 메모리가 계속 불어나므로 주기적으로 새로 띄움"""
    try:
        driver.quit()
    except Exception:
        pass
    runtime_status.increment('chrome_restarts')
    log_msg(f"[시스템] 크롬 정기 재시작 ({CHROME_RESTART_CYCLES}주기마다, 메모리 정리)", "DEBUG")
    return create_driver()

def refetch_blocked_imagecon_posts(driver):
    """이미지 주소 차단 때문에 이미지콘이 '삭제됨' 그림으로 저장된 글을 다시 수집 (기동 시 1회, storage.posts_with_blocked_imagecons)"""
    posts = posts_with_blocked_imagecons()
    fixed = 0
    for old in posts:
        try:
            updated = scrape_post_detail(driver, old)
            if updated is None:
                continue
            updated['list_comment_count'] = old['list_comment_count']
            update_post(updated)
            fixed += 1
        except Exception as e:
            log_msg(f"[DB] #{old['id']} 이미지콘 복구 다시 수집 실패: {short_err(e)}", "WARN")
    mark_blocked_imagecons_refetched()
    if posts:
        log_msg(f"[DB] '삭제된 이미지콘'으로 저장된 글 다시 수집: {fixed}/{len(posts)}건")

def run_daily_maintenance():
    """하루 한 번 DB 백업과 오래된 글 정리. 실패해도 수집은 계속"""
    try:
        path = backup_db(BACKUP_DIR, BACKUP_KEEP)
        if path:
            runtime_status.update(last_backup={'at': runtime_status.now(), 'file': os.path.basename(path)})
            log_msg(f"[DB] 백업 완료: {path} (최근 {BACKUP_KEEP}개 보관)")
    except Exception as e:
        log_msg(f"[DB] 백업 실패: {short_err(e)}", "ERROR")
    try:
        deleted = prune_old_posts(RETENTION_DAYS, MAX_DATA_PER_KEYWORD)
        runtime_status.update(last_prune={'at': runtime_status.now(), 'deleted': deleted})
        if deleted:
            log_msg(f"[DB] {RETENTION_DAYS}일 지난 글 {deleted}건 정리")
    except Exception as e:
        log_msg(f"[DB] 오래된 글 정리 실패: {short_err(e)}", "ERROR")
    try:
        # 정리됐거나 키워드와 함께 지워진 글의 저장 이미지 폴더 삭제
        remove_orphan_image_dirs(existing_post_ids)
    except Exception as e:
        log_msg(f"[DB] 이미지 정리 실패: {short_err(e)}", "ERROR")

def verify_pending_categories(driver):
    """관리 화면에서 추가한 카테고리를 열어 보고 수집 가능(ok)·불가(invalid)를 기록. 수집은 다음 주기부터"""
    for board in pending_categories():
        try:
            ok, detail = check_board(driver, board)
        except Exception as e:
            log_msg(f"[카테고리] {board} 확인 실패, 다음 주기에 재시도: {short_err(e)}", "WARN")
            continue
        if ok:
            set_category_checked(board, True, page_name=detail)
            log_msg(f"[카테고리] {board} 확인 완료{f' ({detail})' if detail else ''} → 다음 주기부터 수집")
        else:
            set_category_checked(board, False, message=detail)
            log_msg(f"[카테고리] {board} 수집할 수 없는 게시판: {detail}", "WARN")

def short_title(title, limit=40):
    title = (title or '').strip()
    return title if len(title) <= limit else title[:limit] + '…'

def main():
    global DDNS_URL
    api_thread = threading.Thread(target=run_api_server, daemon=True)
    api_thread.start()

    if not IS_LINUX:
        DDNS_URL = "http://127.0.0.1:8081"

    try:
        driver = create_driver()
    except Exception as chrome_err:
        log_msg(f"[시스템] 크롬 드라이버 시작 실패로 종료: {short_err(chrome_err)}", "CRITICAL")
        sys.exit(1)

    # DB 초기화(최초 1회 기존 JSON 데이터 이전 포함). 대시보드는 웹서버가 DB에서 직접 조회하여 제공
    init_db()
    try:
        fix_stored_x_embeds()
        replace_stored_x_cards()
        remove_stored_duplicate_instagram_placeholders()
        remove_stored_sns_videos()
    except Exception as fix_err:
        log_msg(f"[DB] 저장된 글의 X·인스타그램 정리 실패 (다음 기동 시 재시도): {short_err(fix_err)}", "WARN")
    try:
        refetch_blocked_imagecon_posts(driver)
    except Exception as fix_err:
        log_msg(f"[DB] 이미지콘 복구 실패: {short_err(fix_err)}", "WARN")

    log_msg(f"[시스템] 모니터링 시작 (주기 {CHECK_INTERVAL}초)")

    try:
        is_initial_run = True
        heartbeat = {'since': time.time(), 'cycles': 0, 'new': 0, 'errors': 0}
        # 목록에서 빠졌지만 원문이 남아 있다고 확인된 글 (매 주기 다시 열지 않도록 기억)
        verified_present = set()
        # 검색에는 걸렸지만 키워드가 그대로 들어 있지 않아 거른 글 {(board, keyword, id)} (매 주기 다시 열지 않도록 기억)
        rejected = set()
        # 키워드별 무시할 표현. 관리 화면에서 바뀌면 거른 글 기억을 비워 새 기준으로 다시 확인
        keyword_ignores = {}
        # 차단 의심이 연속된 횟수와 그에 따른 다음 주기까지의 대기 시간
        block_streak = 0
        next_wait = CHECK_INTERVAL
        # 차단이 의심된 사이트 이름 (알림 문구용, 예: '에펨코리아')
        blocked_label = ''
        # 크롬을 마지막으로 띄운 뒤 지난 주기 수, 유지 관리(백업·정리)를 마지막으로 한 날짜
        cycles_since_chrome = 0
        maintenance_date = None

        while True:
            if not is_initial_run:
                time.sleep(next_wait)

            is_initial_run = False

            try:
                if CHROME_RESTART_CYCLES and cycles_since_chrome >= CHROME_RESTART_CYCLES:
                    driver = restart_driver(driver)
                    cycles_since_chrome = 0
                driver = ensure_driver_alive(driver)
            except Exception as restart_err:
                log_msg(f"[시스템] 크롬 재시작 실패, 다음 주기에 재시도: {short_err(restart_err)}", "ERROR")
                continue

            config_data = load_keywords()
            board_names = category_names()
            alert_targets = load_alert_targets()
            latest_ignores = load_keyword_ignores()
            if latest_ignores != keyword_ignores:
                keyword_ignores = latest_ignores
                rejected.clear()

            cycle_started = time.time()
            stats = {'keywords': 0, 'new': 0, 'updated': 0, 'deleted': 0, 'errors': 0, 'details': 0,
                     'list_ok': 0, 'list_failed': 0}
            blocked_reason = None
            # 차단이 의심된 사이트는 이번 주기의 남은 요청을 멈춤 (다른 사이트는 계속 수집)
            blocked_sites = set()

            for board, keywords in config_data.items():
                board_name = board_names.get(board, board)
                if board_site(board) in blocked_sites:
                    continue

                for keyword in keywords:
                    stats['keywords'] += 1
                    target = f"{board_name}/{keyword}"
                    ignores = keyword_ignores.get((board, keyword), [])
                    log_msg(f"[수집] {target} 확인 중", "DEBUG")

                    # 새 글 판별 기준이 되는 최근 수집 글 (최신순)
                    board_data = recent_keyword_posts(board, keyword, MAX_DATA_PER_KEYWORD)

                    # 목록을 먼저 읽어 새 글 알림을 가장 먼저 처리하고, 기존 글 갱신은 목록 값 비교로 변화가 있을 때만 수행
                    try:
                        new_post_list = get_list_page_posts(driver, board, keyword, page=1)
                        stats['list_ok'] += 1
                    except BlockedError as block_ex:
                        # 차단이 의심되면 그 사이트의 남은 키워드까지 요청을 이어가지 않고 이번 주기에는 멈춤
                        stats['errors'] += 1
                        blocked_sites.add(board_site(board))
                        blocked_reason = blocked_reason or f"{site_labels()[board_site(board)]['name']} {target} {block_ex}"
                        break
                    except Exception as list_ex:
                        stats['errors'] += 1
                        stats['list_failed'] += 1
                        log_msg(f"[오류] {target} 목록 조회 실패: {short_err(list_ex)}", "WARN")
                        continue

                    if not board_data:
                        # 기준점이 없으면 목록 전체를 새 글로 취급해 알림이 폭주하므로, 성공할 때까지 매 주기
                        # 키워드가 그대로 들어 있는 가장 최신 글 1개만 기준점으로 저장
                        for candidate in new_post_list:
                            if (board, keyword, candidate['id']) in rejected:
                                continue
                            try:
                                stats['details'] += 1
                                post_data = scrape_post_detail(driver, candidate)
                                if not post_data:
                                    continue
                                if not keyword_in_post(keyword, post_data['title'], post_data.get('content'), ignores):
                                    rejected.add((board, keyword, candidate['id']))
                                    continue
                                post_data['list_comment_count'] = candidate['list_comment_count']
                                save_keyword_post(board, keyword, post_data, is_new=False)
                                log_msg(f"[기준점] {target} #{post_data['id']} 저장 (이후 새 글부터 알림)")
                            except Exception as e:
                                stats['errors'] += 1
                                log_msg(f"[오류] {target} 기준점 수집 실패, 다음 주기 재시도: {short_err(e)}", "WARN")
                            break
                        continue

                    existing_ids = {post['id'] for post in board_data}
                    new_posts = []
                    for p in new_post_list:
                        if p['id'] in existing_ids:
                            break
                        if (board, keyword, p['id']) not in rejected:
                            new_posts.append(p)

                    for post_info in reversed(new_posts):
                        try:
                            stats['details'] += 1
                            post_data = scrape_post_detail(driver, post_info)
                            if post_data is None:
                                continue
                            if not keyword_in_post(keyword, post_data['title'], post_data.get('content'), ignores):
                                rejected.add((board, keyword, post_info['id']))
                                log_msg(f"[제외] {target} #{post_info['id']} 키워드가 그대로 없음 (띄어쓰기 무시 검색 또는 무시할 표현) "
                                        f"{short_title(post_data['title'])}", "DEBUG")
                                continue

                            post_data['list_comment_count'] = post_info['list_comment_count']
                            # 같은 글이 여러 키워드(예: 싼타페·싼하)에 걸리면 처음 수집한 키워드에서만 알림
                            already_collected = post_exists(post_data['id'])
                            save_keyword_post(board, keyword, post_data, is_new=True)
                            if already_collected:
                                log_msg(f"[새 글] {target} #{post_data['id']} 다른 키워드로 이미 수집된 글 → 알림 생략", "DEBUG")
                                continue
                            stats['new'] += 1

                            has_video = len(post_data.get('videos', [])) > 0
                            # 키워드가 등록된 게시판 중 하나라도 이 글의 알림을 원하면 발송
                            # (전체 알림이 켜져 있거나, 동영상 글이고 동영상 알림이 켜져 있으면)
                            targets = alert_targets.get((board, keyword), [])
                            full_alert = [t['name'] for t in targets if t['alert']]
                            video_only = [t['name'] for t in targets if has_video and t['video_alert'] and not t['alert']]
                            alert_boards = full_alert + video_only
                            should_send_alert = bool(alert_boards)

                            alert_result = "알림 발송" if should_send_alert else "알림 꺼짐"
                            log_msg(f"[새 글] {target} #{post_data['id']} {short_title(post_data['title'])}{' (동영상)' if has_video else ''} → {alert_result}")

                            if should_send_alert:
                                base_url = (DDNS_URL or "").strip()
                                if base_url and not base_url.startswith(("http://", "https://")):
                                    base_url = f"http://{base_url}"

                                board_post_url = f"{base_url}#post-{post_data['id']}" if base_url else ""
                                original_post_url = (post_data.get('link') or "").strip()
                                # 디시 글 주소는 수집할 때부터 전체 주소. 에펨코리아는 상대 주소일 수 있어 보정
                                if original_post_url and not original_post_url.startswith(("http://", "https://")):
                                    original_post_url = f"https://www.fmkorea.com{original_post_url if original_post_url.startswith('/') else '/' + original_post_url}"

                                send_post_alert(post_data, alert_boards, keyword, board_name, board_post_url, original_post_url)
                        except Exception as deep_ex:
                            stats['errors'] += 1
                            log_msg(f"[오류] {target} #{post_info['id']} 새 글 수집 실패: {short_err(deep_ex)}", "WARN")

                    sync_existing_posts(driver, target, new_post_list, board_data, stats, verified_present)

            # 주기 요약: 변화나 오류가 있을 때만 INFO로 남기고, 조용한 주기는 1시간마다 상태 로그로 묶어서 보고
            elapsed = time.time() - cycle_started
            summary = (f"키워드 {stats['keywords']}개, 새 글 {stats['new']}, 갱신 {stats['updated']}, "
                       f"삭제 {stats['deleted']}, 오류 {stats['errors']}, 상세 조회 {stats['details']}회 ({elapsed:.0f}초)")
            has_events = stats['new'] or stats['deleted'] or stats['errors']
            log_msg(f"[수집] 주기 완료: {summary}", "INFO" if has_events else "DEBUG")

            # 차단 의심(정상 게시판이 아닌 응답, 또는 모든 목록 요청 실패) 시 대기 시간을 늘려 요청을 줄이고, 정상 응답이 오면 원래 주기로 복귀
            if not blocked_reason and stats['list_failed'] and not stats['list_ok']:
                blocked_reason = f"이번 주기의 목록 요청 {stats['list_failed']}건이 모두 실패"
                blocked_sites = {board_site(board) for board in config_data}
            if blocked_reason:
                block_streak += 1
                next_wait = min(CHECK_INTERVAL * (2 ** block_streak), BACKOFF_MAX_SECONDS)
                log_msg(f"[차단 의심] {blocked_reason} → {next_wait // 60}분 {next_wait % 60}초 후 다시 확인 (연속 {block_streak}회)", "WARN")
                if block_streak == 1:
                    labels = site_labels()
                    blocked_label = '·'.join(labels[site]['name'] for site in SITE_NAMES if site in blocked_sites)
                    send_telegram_message(
                        f"⚠️ {blocked_label} 접속 차단 의심\n\n{blocked_reason}\n\n"
                        f"요청을 줄이기 위해 대기 시간을 늘립니다. 정상으로 돌아오면 다시 알려드립니다."
                    )
            elif block_streak:
                log_msg(f"[복구] 정상 응답 확인 (차단 의심 {block_streak}회 후) → 원래 주기 {CHECK_INTERVAL}초로 복귀")
                send_telegram_message(f"✅ {blocked_label} 접속이 정상으로 돌아왔습니다. (차단 의심 {block_streak}회 후 복구)")
                block_streak = 0
                next_wait = CHECK_INTERVAL

            # 새로 추가한 카테고리는 차단 의심이 없는 주기에만 확인 (차단 화면을 잘못된 게시판으로 오판하지 않도록)
            if not blocked_reason:
                verify_pending_categories(driver)

            cycles_since_chrome += 1
            runtime_status.increment('cycles')
            runtime_status.update(
                last_cycle={'finished_at': runtime_status.now(), 'seconds': round(elapsed), 'new': stats['new'],
                            'updated': stats['updated'], 'deleted': stats['deleted'], 'errors': stats['errors']},
                block_streak=block_streak,
                next_check_at=datetime.fromtimestamp(time.time() + next_wait).strftime('%Y-%m-%d %H:%M:%S'))
            if maintenance_date != date.today():
                maintenance_date = date.today()
                run_daily_maintenance()

            heartbeat['cycles'] += 1
            heartbeat['new'] += stats['new']
            heartbeat['errors'] += stats['errors']
            if time.time() - heartbeat['since'] >= HEARTBEAT_SECONDS:
                log_msg(f"[상태] 최근 1시간 정상 동작: 주기 {heartbeat['cycles']}회, 새 글 {heartbeat['new']}, 오류 {heartbeat['errors']}")
                heartbeat = {'since': time.time(), 'cycles': 0, 'new': 0, 'errors': 0}

    except KeyboardInterrupt:
        log_msg("[시스템] 사용자 중단(Ctrl+C)으로 종료합니다.", "WARN")
    except Exception as e:
        log_msg(f"[시스템] 메인 루프 비정상 종료: {short_err(e)}\n{traceback.format_exc()}", "CRITICAL")
    finally:
        try:
            driver.quit()
        except Exception:
            pass
        log_msg("[시스템] 종료 완료")

if __name__ == "__main__":
    main()
