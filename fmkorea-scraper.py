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
    IS_LINUX,
    HTML_OUTPUT_FILE,
    all_keywords_data,
    data_lock
)
from storage import (
    load_keywords_from_file,
    load_board_config,
    load_backup_data,
    save_backup_data
)
from notifier import send_telegram_message
from scraper import (
    get_list_page_posts,
    scrape_post_detail
)
from ui_builder import generate_multiboard_html
from web_server import run_api_server

try:
    if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
        sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

def main():
    global DDNS_URL
    log_msg("백그라운드 API 제어용 서버 스레드 분리 가동 개시 준비", "DEBUG")
    api_thread = threading.Thread(target=run_api_server, daemon=True)
    api_thread.start()

    options = Options()
    services = Service()
    if IS_LINUX:
        log_msg("리눅스(Linux) 환경 감지로 인한 Headless 플래그 및 보호 우회 속성 강제 주입", "INFO")
        options.add_argument('--headless=new')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-gpu')
    else:
        DDNS_URL = "127.0.0.1:8081"

    try:
        log_msg("Selenium 웹드라이버 시동 및 내부 크롬 프로세스 인스턴스 할당 시작", "DEBUG")
        driver = Chrome(options=options, service=services)
        log_msg("Selenium 크롬 웹 드라이버 정상 준비 완료", "INFO")
    except Exception as chrome_err:
        log_msg(f"❌ 크롬 웹 드라이버 엔진 실행 프로세스 도중 크리티컬 오류로 중단됨: {chrome_err}", "CRITICAL")
        sys.exit(1)

    backup_data = load_backup_data()
    with data_lock:
        config_data = load_keywords_from_file()
        for board, keywords in config_data.items():
            for keyword in keywords:
                combined_key = f"{board}::{keyword}"
                
                loaded_data = backup_data.get(combined_key, [])
                if len(loaded_data) > MAX_DATA_PER_KEYWORD:
                    loaded_data = loaded_data[:MAX_DATA_PER_KEYWORD]
                    
                all_keywords_data[combined_key] = loaded_data
                log_msg(f"메모리 캐시 변수 초기 데이터 매핑 완료: {combined_key} (수집 누적 글: {len(all_keywords_data[combined_key])}개)", "DEBUG")

    with data_lock:
        generate_multiboard_html(all_keywords_data, HTML_OUTPUT_FILE)

    log_msg("🎉 통합 미니 게시판 시스템 초기화 완료 (기존 백업 데이터로 대시보드 복원 성공)", "INFO")
    log_msg("📡 메인 백그라운드 실시간 모니터링 감시 무한 루프 엔진을 가동합니다.", "INFO")

    try:
        is_first_scan = {}
        is_initial_run = True

        while True:
            if not is_initial_run:
                log_msg(f"⏳ 다음 실시간 스캔 쿼리 탐색 주기까지 {CHECK_INTERVAL}초 대기 프로세스 진행", "DEBUG")
                time.sleep(CHECK_INTERVAL)
            
            is_initial_run = False

            with data_lock:
                config_data = load_keywords_from_file()
                board_alert_config = load_board_config()
                
            log_msg("🔍 실시간 주기적 크롤링 스캔 작업 세션 개시", "INFO")
            has_changes = False
            
            for board, keywords in config_data.items():
                board_name = BOARD_MAP.get(board, board)
                
                for keyword in keywords:
                    combined_key = f"{board}::{keyword}"
                    log_msg(f"   ▶ 순회 작업 진행 타겟 -> [{board_name}] - 키워드: {keyword}", "DEBUG")
                    
                    with data_lock:
                        if combined_key not in all_keywords_data:
                            all_keywords_data[combined_key] = []
                        board_data = all_keywords_data[combined_key]
                    
                    if board_data:
                        log_msg(f"      - 기존 캐시 데이터 갱신을 위한 상위 {MAX_POSTS_TO_SYNC_COMMENTS}개 타겟 딥 스캔 진입", "DEBUG")
                        posts_to_sync = board_data[:MAX_POSTS_TO_SYNC_COMMENTS]
                        posts_to_remove = []
                        
                        for idx, old_post in enumerate(posts_to_sync):
                            try:
                                log_msg(f"      [동기화 딥스캔] 글 ID: {old_post['id']} 상세 페이지 갱신 추적 시작", "DEBUG")
                                updated_post = scrape_post_detail(driver, old_post)
                                
                                if updated_post is None:
                                    log_msg(f"      [삭제 확정] 글 ID: {old_post['id']}가 원문에서 유실되었습니다. 대시보드 리스트에서 제거 조치합니다.", "INFO")
                                    posts_to_remove.append(old_post['id'])
                                    continue
                                
                                updated_post['is_new'] = old_post.get('is_new', False) 
                                
                                if (old_post['comment_count'] != updated_post['comment_count'] or 
                                    len(old_post['comments']) != len(updated_post['comments']) or
                                    old_post['votes'] != updated_post['votes']):
                                    
                                    log_msg(f"      [변경 사항 감지] 글 ID: {old_post['id']} 메타/댓글 데이터 변경됨. 캐시 즉시 업데이트.", "INFO")
                                    with data_lock:
                                        board_data[idx] = updated_post
                                    has_changes = True
                            except Exception as sync_ex:
                                log_msg(f"      ⚠️ 기존 글 ID {old_post['id']} 백그라운드 갱신 스킵 (예외 피드백): {sync_ex}", "WARN")
                        
                        if posts_to_remove:
                            with data_lock:
                                all_keywords_data[combined_key] = [p for p in board_data if p['id'] not in posts_to_remove]
                            has_changes = True
                    
                    try:
                        log_msg(f"      - 새 글 목록 모니터링 수집 쿼리 가동 중...", "DEBUG")
                        new_post_list = get_list_page_posts(driver, board, keyword, page=1)
                    except Exception as list_ex:
                        log_msg(f"      ⚠️ [{board_name} - {keyword}] 목록 파싱 실패로 이번 주기 패스 처리: {list_ex}", "WARN")
                        continue
                    
                    if combined_key not in is_first_scan:
                        is_first_scan[combined_key] = False if board_data else True

                    new_posts = []
                    if board_data:
                        existing_ids = {post['id'] for post in board_data}
                        for p in new_post_list:
                            if p['id'] in existing_ids: 
                                break
                            new_posts.append(p)
                    else:
                        if is_first_scan[combined_key]:
                            log_msg(f"   📦 [{board_name} - {keyword}] 최초 빌드: 리스트의 최신 글 1개만 베이스라인 데이터로 강제 적재합니다.", "INFO")
                            if new_post_list:
                                try:
                                    first_post_info = new_post_list[0]
                                    post_data = scrape_post_detail(driver, first_post_info)
                                    if post_data:
                                        post_data['is_new'] = False
                                        with data_lock:
                                            all_keywords_data[combined_key] = [post_data]
                                        log_msg(f"   📦 [{board_name} - {keyword}] 최초 기준점 빌드 매핑 성공", "INFO")
                                except Exception as e:
                                    log_msg(f"      ⚠️ 베이스라인 최신 글 1개 데이터 수집 실패 예외 로그: {e}", "ERROR")
                                    
                            is_first_scan[combined_key] = False
                            has_changes = True
                            continue
                        else:
                            new_posts = new_post_list
                    
                    if new_posts:
                        log_msg(f"   🆕 [{board_name}] 교차 검증을 거친 실시간 신규 새 글 {len(new_posts)}개 탐지 성공!", "INFO")
                            
                        for post_info in reversed(new_posts):
                            try:
                                log_msg(f"   🆕 신규 글 상세 딥 크롤링 프로세스 전개 -> ID: {post_info['id']}", "INFO")
                                post_data = scrape_post_detail(driver, post_info)
                                
                                if post_data is None:
                                    continue
                                    
                                post_data['is_new'] = True
                                
                                with data_lock:
                                    all_keywords_data[combined_key] = [post_data] + all_keywords_data[combined_key]
                                    
                                    if len(all_keywords_data[combined_key]) > MAX_DATA_PER_KEYWORD:
                                        all_keywords_data[combined_key] = all_keywords_data[combined_key][:MAX_DATA_PER_KEYWORD]
                                        
                                    generate_multiboard_html(all_keywords_data, HTML_OUTPUT_FILE)
                                save_backup_data(all_keywords_data)
                                
                                has_video = len(post_data.get('videos', [])) > 0
                                is_alert_enabled = board_alert_config.get(board, {}).get("alert", True)
                                
                                if is_alert_enabled or has_video:
                                    video_badge = " [🎬 동영상 포함 강제알림]" if (not is_alert_enabled and has_video) else ""
                                    log_msg(f"   🚀 텔레그램 연동 채널 알림 발송을 개시합니다. (게시글 ID: {post_data['id']})", "INFO")
                                    telegram_text = (
                                        f"🔔 *[{board_name} - {keyword}]{video_badge} 실시간 새 글!*\n\n"
                                        f"📌 *제목:* {post_data['title']}\n\n"
                                        f"📂 [게시판 확인]({DDNS_URL}#post-{post_data['id']})"
                                    )
                                    send_telegram_message(telegram_text)
                                else:
                                    log_msg(f"      🔕 [{board_name}] 알림 토글 비활성화 상태(동영상 요소 없음) - 텔레그램 발송을 안전하게 생략합니다.", "INFO")
                            except Exception as deep_ex:
                                log_msg(f"      ⚠️ 새 글 상세 크롤링 처리 도중 예외로 인한 패스 스킵 피드백: {deep_ex}", "ERROR")
                        has_changes = True
            
            if has_changes:
                log_msg("🔄 이번 주기 캐시 변경 내역 발생 확인 -> index.html 동적 렌더링 동기화 즉시 갱신 진행", "INFO")
                with data_lock:
                    generate_multiboard_html(all_keywords_data, HTML_OUTPUT_FILE)
                save_backup_data(all_keywords_data)
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