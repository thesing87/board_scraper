import time
import sys
import threading
import traceback
from selenium.webdriver import Chrome
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options

from config import (
    log_msg,
    short_err,
    BOARD_MAP,
    CHECK_INTERVAL,
    MAX_POSTS_TO_SYNC_COMMENTS,
    DDNS_URL,
    MAX_DATA_PER_KEYWORD,
    IS_LINUX
)
from storage import (
    init_db,
    load_keywords,
    load_board_config,
    query_keyword_posts,
    save_keyword_post,
    update_post,
    mark_post_deleted
)
from notifier import send_telegram_message
from scraper import (
    get_list_page_posts,
    scrape_post_detail
)
from web_server import run_api_server

# 변경이 없는 주기는 요약 로그를 남기지 않으므로, 살아있음을 알리는 상태 로그 간격
HEARTBEAT_SECONDS = 3600

try:
    if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
        sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

def create_driver():
    options = Options()
    options.page_load_strategy = 'eager'
    options.add_argument('--blink-settings=imagesEnabled=false')
    options.add_argument('--disable-images')
    services = Service()
    if IS_LINUX:
        options.add_argument('--headless=new')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-gpu')

    driver = Chrome(options=options, service=services)
    log_msg(f"[시스템] 크롬 드라이버 준비 완료{' (headless)' if IS_LINUX else ''}")
    return driver

def ensure_driver_alive(driver):
    """크롬 프로세스가 죽었으면(OOM 등) 드라이버를 새로 생성하여 반환"""
    try:
        driver.execute_script("return 1")
        return driver
    except Exception as health_err:
        log_msg(f"[시스템] 크롬 응답 없음 → 재시작: {short_err(health_err)}", "WARN")
    try:
        driver.quit()
    except Exception:
        pass
    return create_driver()

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

    log_msg(f"[시스템] 모니터링 시작 (주기 {CHECK_INTERVAL}초)")

    try:
        is_initial_run = True
        heartbeat = {'since': time.time(), 'cycles': 0, 'new': 0, 'errors': 0}

        while True:
            if not is_initial_run:
                time.sleep(CHECK_INTERVAL)

            is_initial_run = False

            try:
                driver = ensure_driver_alive(driver)
            except Exception as restart_err:
                log_msg(f"[시스템] 크롬 재시작 실패, 다음 주기에 재시도: {short_err(restart_err)}", "ERROR")
                continue

            config_data = load_keywords()
            board_alert_config = load_board_config()

            cycle_started = time.time()
            stats = {'keywords': 0, 'new': 0, 'updated': 0, 'deleted': 0, 'errors': 0}

            for board, keywords in config_data.items():
                board_name = BOARD_MAP.get(board, board)

                for keyword in keywords:
                    stats['keywords'] += 1
                    target = f"{board_name}/{keyword}"
                    log_msg(f"[수집] {target} 확인 중", "DEBUG")

                    # 새 글 판별 기준이 되는 최근 수집 글 (최신순)
                    _, board_data = query_keyword_posts(board, keyword, 0, MAX_DATA_PER_KEYWORD)

                    # 상위 글은 매 주기 다시 열어 댓글·추천 수 변화와 원문 삭제 여부를 반영
                    for old_post in board_data[:MAX_POSTS_TO_SYNC_COMMENTS]:
                        if old_post.get('is_deleted', False):
                            continue
                        try:
                            updated_post = scrape_post_detail(driver, old_post)

                            if updated_post is None:
                                mark_post_deleted(old_post['id'])
                                stats['deleted'] += 1
                                log_msg(f"[삭제] {target} #{old_post['id']} 원문 삭제됨 (보존 처리)")
                                continue

                            if (old_post['comment_count'] != updated_post['comment_count'] or
                                len(old_post['comments']) != len(updated_post['comments']) or
                                old_post['votes'] != updated_post['votes']):
                                update_post(updated_post)
                                stats['updated'] += 1
                                log_msg(f"[갱신] {target} #{old_post['id']} 댓글 {updated_post['comment_count']}, 추천 {updated_post['votes']}", "DEBUG")
                        except Exception as sync_ex:
                            stats['errors'] += 1
                            log_msg(f"[오류] {target} #{old_post['id']} 갱신 실패: {short_err(sync_ex)}", "WARN")

                    try:
                        new_post_list = get_list_page_posts(driver, board, keyword, page=1)
                    except Exception as list_ex:
                        stats['errors'] += 1
                        log_msg(f"[오류] {target} 목록 조회 실패: {short_err(list_ex)}", "WARN")
                        continue

                    if not board_data:
                        # 기준점이 없으면 목록 전체를 새 글로 취급해 알림이 폭주하므로, 성공할 때까지 매 주기 최신 글 1개만 기준점으로 저장
                        if new_post_list:
                            try:
                                post_data = scrape_post_detail(driver, new_post_list[0])
                                if post_data:
                                    save_keyword_post(board, keyword, post_data, is_new=False)
                                    log_msg(f"[기준점] {target} #{post_data['id']} 저장 (이후 새 글부터 알림)")
                            except Exception as e:
                                stats['errors'] += 1
                                log_msg(f"[오류] {target} 기준점 수집 실패, 다음 주기 재시도: {short_err(e)}", "WARN")
                        continue

                    existing_ids = {post['id'] for post in board_data}
                    new_posts = []
                    for p in new_post_list:
                        if p['id'] in existing_ids:
                            break
                        new_posts.append(p)

                    for post_info in reversed(new_posts):
                        try:
                            post_data = scrape_post_detail(driver, post_info)
                            if post_data is None:
                                continue

                            save_keyword_post(board, keyword, post_data, is_new=True)
                            stats['new'] += 1

                            has_video = len(post_data.get('videos', [])) > 0
                            board_cfg = board_alert_config.get(board, {})
                            is_alert_enabled = board_cfg.get("alert", True)
                            is_video_alert_enabled = board_cfg.get("video_alert", True)

                            should_send_alert = False
                            video_badge = ""

                            if has_video:
                                if is_video_alert_enabled:
                                    should_send_alert = True
                                    if not is_alert_enabled:
                                        video_badge = " [🎬 동영상 알림]"
                                elif is_alert_enabled:
                                    should_send_alert = True
                            else:
                                if is_alert_enabled:
                                    should_send_alert = True

                            alert_result = "알림 발송" if should_send_alert else "알림 꺼짐"
                            log_msg(f"[새 글] {target} #{post_data['id']} {short_title(post_data['title'])}{' (동영상)' if has_video else ''} → {alert_result}")

                            if should_send_alert:
                                base_url = (DDNS_URL or "").strip()
                                if base_url and not base_url.startswith(("http://", "https://")):
                                    base_url = f"http://{base_url}"

                                board_post_url = f"{base_url}#post-{post_data['id']}" if base_url else ""
                                original_post_url = (post_data.get('link') or "").strip()
                                if original_post_url and not original_post_url.startswith(("http://", "https://")):
                                    original_post_url = f"https://www.fmkorea.com{original_post_url if original_post_url.startswith('/') else '/' + original_post_url}"

                                # 모바일 화면에서 누르기 편한 큼직한 인라인 키보드 버튼 구성
                                keyboard = []
                                if board_post_url.startswith(("http://", "https://")):
                                    keyboard.append([{"text": "📱 게시판에서 확인하기", "url": board_post_url}])
                                if original_post_url.startswith(("http://", "https://")):
                                    keyboard.append([{"text": "🔗 원본글 보기 (에펨코리아)", "url": original_post_url}])

                                reply_markup = {"inline_keyboard": keyboard} if keyboard else None

                                telegram_text = (
                                    f"🔔 *[{board_name} - {keyword}]{video_badge} 실시간 새 글!*\n\n"
                                    f"📌 *제목:* {post_data['title']}"
                                )
                                send_telegram_message(telegram_text, reply_markup=reply_markup)
                        except Exception as deep_ex:
                            stats['errors'] += 1
                            log_msg(f"[오류] {target} #{post_info['id']} 새 글 수집 실패: {short_err(deep_ex)}", "WARN")

            # 주기 요약: 변화나 오류가 있을 때만 INFO로 남기고, 조용한 주기는 1시간마다 상태 로그로 묶어서 보고
            elapsed = time.time() - cycle_started
            summary = (f"키워드 {stats['keywords']}개, 새 글 {stats['new']}, 갱신 {stats['updated']}, "
                       f"삭제 {stats['deleted']}, 오류 {stats['errors']} ({elapsed:.0f}초)")
            has_events = stats['new'] or stats['deleted'] or stats['errors']
            log_msg(f"[수집] 주기 완료: {summary}", "INFO" if has_events else "DEBUG")

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
