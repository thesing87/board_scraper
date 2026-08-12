import os
import json
from config import (
    log_msg,
    KEYWORDS_FILE,
    BOARD_CONFIG_FILE,
    JSON_BACKUP_FILE,
    BOARD_MAP
)

def load_keywords_from_file():
    log_msg(f"키워드 파일 로드 시도: {KEYWORDS_FILE}", "DEBUG")
    if not os.path.exists(KEYWORDS_FILE):
        log_msg("키워드 설정 파일이 존재하지 않아 환경변수 기반으로 신규 생성을 진행합니다.", "INFO")
        initial_config = {}
        for board in BOARD_MAP.keys():
            env_str = os.environ.get(f'KEYWORDS_{board.upper()}', '')
            if board == 'car' and not env_str:
                env_str = os.environ.get('KEYWORDS', '')
            initial_config[board] = [k.strip() for k in env_str.split(',') if k.strip()]
        
        with open(KEYWORDS_FILE, 'w', encoding='utf-8') as f:
            json.dump(initial_config, f, ensure_ascii=False, indent=4)
        log_msg("초기 키워드 설정 파일 생성이 완료되었습니다.", "INFO")
        return initial_config
    
    try:
        with open(KEYWORDS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            log_msg(f"키워드 설정 로드 성공 (등록된 게시판 데이터 세트: {len(data)})", "DEBUG")
            return data
    except Exception as e:
        log_msg(f"⚠️ 키워드 파일 로드 중 오류 발생: {e}", "ERROR")
        return {board: [] for board in BOARD_MAP.keys()}

def save_keywords_to_file(config_data):
    log_msg("키워드 파일 디스크 저장을 시도합니다.", "DEBUG")
    try:
        with open(KEYWORDS_FILE, 'w', encoding='utf-8') as f:
            json.dump(config_data, f, ensure_ascii=False, indent=4)
        log_msg("키워드 설정 데이터 변경사항이 성공적으로 저장되었습니다.", "INFO")
        return True
    except Exception as e:
        log_msg(f"⚠️ 키워드 파일 저장 중 오류 발생: {e}", "ERROR")
        return False

def load_board_config():
    log_msg(f"게시판 알림 설정 파일 로드 시도: {BOARD_CONFIG_FILE}", "DEBUG")
    if not os.path.exists(BOARD_CONFIG_FILE):
        log_msg("게시판 알림 설정 파일이 존재하지 않아 초기화를 진행합니다.", "INFO")
        initial_config = {board: {"alert": True, "video_alert": True} for board in BOARD_MAP.keys()}
        with open(BOARD_CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(initial_config, f, ensure_ascii=False, indent=4)
        return initial_config
    try:
        with open(BOARD_CONFIG_FILE, 'r', encoding='utf-8') as f:
            config = json.load(f)
            for board in BOARD_MAP.keys():
                if board not in config:
                    config[board] = {"alert": True, "video_alert": True}
                else:
                    if "alert" not in config[board]:
                        config[board]["alert"] = True
                    if "video_alert" not in config[board]:
                        config[board]["video_alert"] = True
            log_msg("게시판 알림 구성 정보 로드 성공", "DEBUG")
            return config
    except Exception as e:
        log_msg(f"⚠️ 게시판 설정 파일 로드 중 오류 발생: {e}", "ERROR")
        return {board: {"alert": True, "video_alert": True} for board in BOARD_MAP.keys()}

def save_board_config(config_data):
    log_msg("게시판 알림 환경 설정 파일 디스크 쓰기를 시도합니다.", "DEBUG")
    try:
        with open(BOARD_CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config_data, f, ensure_ascii=False, indent=4)
        log_msg("게시판 알림 토글 설정이 디스크에 성공적으로 저장되었습니다.", "INFO")
        return True
    except Exception as e:
        log_msg(f"⚠️ 게시판 설정 파일 저장 중 오류 발생: {e}", "ERROR")
        return False

def load_backup_data():
    log_msg(f"디스크 백업 JSON 데이터 복원 로드 시도: {JSON_BACKUP_FILE}", "DEBUG")
    if os.path.exists(JSON_BACKUP_FILE):
        try:
            with open(JSON_BACKUP_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                log_msg(f"기존 백업 복원 성공 (총 키워드 조합 데이터 개수: {len(data)})", "INFO")
                return data
        except Exception as e:
            log_msg(f"⚠️ 백업 데이터 로드 실패 (파일 손상 가능성): {e}", "ERROR")
    else:
        log_msg("수집 백업 데이터 파일이 감지되지 않아 빈 상태로 시작합니다.", "INFO")
    return {}

def save_backup_data(all_keywords_data):
    log_msg("전체 데이터 캐시 -> 디스크 JSON 백업 쓰기 요청 수신", "DEBUG")
    try:
        with open(JSON_BACKUP_FILE, 'w', encoding='utf-8') as f:
            json.dump(all_keywords_data, f, ensure_ascii=False, indent=4)
        log_msg("JSON 데이터 백업 디스크 저장 성공 완료", "DEBUG")
    except Exception as e:
        log_msg(f"⚠️ 데이터 백업 저장 실패: {e}", "ERROR")
