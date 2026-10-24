import time
import sys
import threading
from selenium.webdriver import Chrome
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options

from config import (
    log_msg,
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
        log_msg("리눅스(Linux) 환경 감지로 인한 Headless 플래그 및 보호 우회 속성 강제 주입", "INFO")
        options.add_argument('--headless=new')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-gpu')

    log_msg("Selenium 웹드라이버 시동 및 내부 크롬 프로세스 인스턴스 할당 시작", "DEBUG")
    driver = Chrome(options=options, service=services)
    log_msg("Selenium 크롬 웹 드라이버 정상 준비 완료", "INFO")
    return driver

def ensure_driver_alive(driver):
    """크롬 프로세스가 죽었으면(OOM 등) 드라이버를 새로 생성하여 반환"""
    try:
        driver.execute_script("return 1")
        return driver
    except Exception as health_err:
        log_msg(f"⚠️ 크롬 드라이버 응답 없음 감지 -> 재생성 시도: {health_err}", "WARN")
    try:
        driver.quit()
    except Exception:
        pass
    return create_driver()

def main():
    global DDNS_URL
    log_msg("백그라운드 API 제어용 서버 스레드 분리 가동 개시 준비", "DEBUG")
    api_thread = threading.Thread(target=run_api_server, daemon=True)
    api_thread.start()

    if not IS_LINUX:
        DDNS_URL = "http://127.0.0.1:8081"

    try:
        driver = create_driver()
    except Exception as chrome_err:
        log_msg(f"❌ 크롬 웹 드라이버 엔진 실행 프로세스 도중 크리티컬 오류로 중단됨: {chrome_err}", "CRITICAL")
        sys.exit(1)

    # DB 초기화(최초 1회 기존 JSON 데이터 이전 포함). 대시보드는 웹서버가 DB에서 직접 조회하여 제공
    init_db()

    log_msg("🎉 통합 미니 게시판 시스템 초기화 완료", "INFO")
    log_msg("📡 메인 백그라운드 실시간 모니터링 감시 무한 루프 엔진을 가동합니다.", "INFO")

    try:
        is_initial_run = True

        while True:
            if not is_initial_run:
                log_msg(f"⏳ 다음 실시간 스캔 쿼리 탐색 주기까지 {CHECK_INTERVAL}초 대기 프로세스 진행", "DEBUG")
                time.sleep(CHECK_INTERVAL)
            
            is_initial_run = False

            try:
                driver = ensure_driver_alive(driver)
            except Exception as restart_err:
                log_msg(f"❌ 크롬 드라이버 재생성 실패, 다음 주기에 재시도합니다: {restart_err}", "ERROR")
                continue

            config_data = load_keywords()
            board_alert_config = load_board_config()

            log_msg("🔍 실시간 주기적 크롤링 스캔 작업 세션 개시", "INFO")
            has_changes = False

            for board, keywords in config_data.items():
                board_name = BOARD_MAP.get(board, board)
                
                for keyword in keywords:
                    log_msg(f"   ▶ 순회 작업 진행 타겟 -> [{board_name}] - 키워드: {keyword}", "DEBUG")

                    # 새 글 판별 기준이 되는 최근 수집 글 (최신순)
                    _, board_data = query_keyword_posts(board, keyword, 0, MAX_DATA_PER_KEYWORD)

                    if board_data:
                        log_msg(f"      - 기존 캐시 데이터 갱신을 위한 상위 {MAX_POSTS_TO_SYNC_COMMENTS}개 타겟 딥 스캔 진입", "DEBUG")
                        posts_to_sync = board_data[:MAX_POSTS_TO_SYNC_COMMENTS]
                        
                        for old_post in posts_to_sync:
                            try:
                                if old_post.get('is_deleted', False):
                                    continue
                                    
                                log_msg(f"      [동기화 딥스캔] 글 ID: {old_post['id']} 상세 페이지 갱신 추적 시작", "DEBUG")
                                updated_post = scrape_post_detail(driver, old_post)
                                
                                if updated_post is None:
                                    log_msg(f"      [삭제 확정/보존] 글 ID: {old_post['id']}가 원문에서 유실되었습니다. 삭제하지 않고 보존 처리합니다.", "INFO")
                                    if not old_post.get('is_deleted', False):
                                        mark_post_deleted(old_post['id'])
                                        has_changes = True
                                    continue
                                
                                if (old_post['comment_count'] != updated_post['comment_count'] or 
                                    len(old_post['comments']) != len(updated_post['comments']) or
                                    old_post['votes'] != updated_post['votes']):
                                    
                                    log_msg(f"      [변경 사항 감지] 글 ID: {old_post['id']} 메타/댓글 데이터 변경됨. 캐시 즉시 업데이트.", "INFO")
                                    update_post(updated_post)
                                    has_changes = True
                            except Exception as sync_ex:
                                log_msg(f"      ⚠️ 기존 글 ID {old_post['id']} 백그라운드 갱신 스킵 (예외 피드백): {sync_ex}", "WARN")
                    
                    try:
                        log_msg("      - 새 글 목록 모니터링 수집 쿼리 가동 중...", "DEBUG")
                        new_post_list = get_list_page_posts(driver, board, keyword, page=1)
                    except Exception as list_ex:
                        log_msg(f"      ⚠️ [{board_name} - {keyword}] 목록 파싱 실패로 이번 주기 패스 처리: {list_ex}", "WARN")
                        continue
                    
                    new_posts = []
                    if board_data:
                        existing_ids = {post['id'] for post in board_data}
                        for p in new_post_list:
                            if p['id'] in existing_ids:
                                break
                            new_posts.append(p)
                    else:
                        # 기준점이 없으면 목록 전체를 새 글로 취급해 알림이 폭주하므로, 성공할 때까지 매 주기 베이스라인 적재만 시도
                        log_msg(f"   📦 [{board_name} - {keyword}] 최초 빌드: 리스트의 최신 글 1개만 베이스라인 데이터로 강제 적재합니다.", "INFO")
                        if new_post_list:
                            try:
                                first_post_info = new_post_list[0]
                                post_data = scrape_post_detail(driver, first_post_info)
                                if post_data:
                                    save_keyword_post(board, keyword, post_data, is_new=False)
                                    log_msg(f"   📦 [{board_name} - {keyword}] 최초 기준점 빌드 매핑 성공", "INFO")
                                    has_changes = True
                            except Exception as e:
                                log_msg(f"      ⚠️ 베이스라인 최신 글 1개 데이터 수집 실패 (다음 주기 재시도): {e}", "ERROR")
                        continue
                    
                    if new_posts:
                        log_msg(f"   🆕 [{board_name}] 교차 검증을 거친 실시간 신규 새 글 {len(new_posts)}개 탐지 성공!", "INFO")
                            
                        for post_info in reversed(new_posts):
                            try:
                                log_msg(f"   🆕 신규 글 상세 딥 크롤링 프로세스 전개 -> ID: {post_info['id']}", "INFO")
                                post_data = scrape_post_detail(driver, post_info)
                                
                                if post_data is None:
                                    continue
                                    
                                save_keyword_post(board, keyword, post_data, is_new=True)

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
                                
                                if should_send_alert:
                                    log_msg(f"   🚀 텔레그램 연동 채널 알림 발송을 개시합니다. (게시글 ID: {post_data['id']})", "INFO")

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
                                else:
                                    log_msg(f"      🔕 [{board_name}] 알림 조건 미충족 (일반알림: {is_alert_enabled}, 동영상알림: {is_video_alert_enabled}, 동영상유무: {has_video}) - 텔레그램 발송 생략", "INFO")
                            except Exception as deep_ex:
                                log_msg(f"      ⚠️ 새 글 상세 크롤링 처리 도중 예외로 인한 패스 스킵 피드백: {deep_ex}", "ERROR")
                        has_changes = True
            
            if has_changes:
                log_msg("🔄 이번 주기 수집 데이터 변경 사항이 DB에 반영되었습니다.", "INFO")
            else:
                log_msg("🔍 이번 턴 실시간 모니터링 감시 주기 종료: 변경 발생 데이터 없음", "DEBUG")

    except KeyboardInterrupt:
        log_msg("⛔ 사용자의 KeyboardInterrupt 입력을 감지하여 실시간 모니터링 엔진 시스템을 안전하게 중단합니다.", "WARN")
    except Exception as e:
        log_msg(f"🚨 크롤러 런타임 코어 루프 엔진 무너짐 치명적 시스템 에러 발생: {e}", "CRITICAL")
    finally:
        log_msg("최종 시스템 할당 리소스 및 메모리 웹 드라이버 인스턴스 반환 절차 개시", "INFO")
        try:
            driver.quit()
            log_msg("Selenium 웹드라이버 엔진 종료 정상 완료", "INFO")
        except Exception as ex:
            log_msg(f"드라이버 인스턴스 해제 시도 실패 또는 이미 프로세스가 꺼져 있습니다: {ex}", "DEBUG")

if __name__ == "__main__":
    main()