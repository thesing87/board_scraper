import os
import json
import tempfile
from datetime import datetime
from config import (
    log_msg,
    KEYWORDS_FILE,
    BOARD_CONFIG_FILE,
    JSON_BACKUP_FILE,
    BOARD_MAP
)

def atomic_write_text(path, text):
    """임시 파일에 먼저 쓴 뒤 교체하여, 쓰기 도중 중단되어도 기존 파일이 깨지지 않도록 보장"""
    dir_name = os.path.dirname(path) or '.'
    fd, tmp_path = tempfile.mkstemp(dir=dir_name, prefix='.tmp_', suffix=os.path.basename(path))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise

def atomic_write_json(path, data):
    atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=4))

def _preserve_corrupt_file(path):
    """손상된 파일을 덮어쓰기 전에 별도 이름으로 보존"""
    corrupt_path = f"{path}.corrupt-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    try:
        os.replace(path, corrupt_path)
        log_msg(f"손상된 파일을 보존했습니다: {corrupt_path}", "WARN")
    except OSError as e:
        log_msg(f"⚠️ 손상 파일 보존 실패: {e}", "ERROR")

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
        
        atomic_write_json(KEYWORDS_FILE, initial_config)
        log_msg("초기 키워드 설정 파일 생성이 완료되었습니다.", "INFO")
        return initial_config
    
    try:
        with open(KEYWORDS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            log_msg(f"키워드 설정 로드 성공 (등록된 게시판 데이터 세트: {len(data)})", "DEBUG")
            return data
    except Exception as e:
        log_msg(f"⚠️ 키워드 파일 로드 중 오류 발생: {e}", "ERROR")
        _preserve_corrupt_file(KEYWORDS_FILE)
        return {board: [] for board in BOARD_MAP.keys()}

def save_keywords_to_file(config_data):
    log_msg("키워드 파일 디스크 저장을 시도합니다.", "DEBUG")
    try:
        atomic_write_json(KEYWORDS_FILE, config_data)
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
        atomic_write_json(BOARD_CONFIG_FILE, initial_config)
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
        atomic_write_json(BOARD_CONFIG_FILE, config_data)
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
            _preserve_corrupt_file(JSON_BACKUP_FILE)
    else:
        log_msg("수집 백업 데이터 파일이 감지되지 않아 빈 상태로 시작합니다.", "INFO")
    return {}

def save_backup_data(all_keywords_data):
    log_msg("전체 데이터 캐시 -> 디스크 JSON 백업 쓰기 요청 수신", "DEBUG")
    try:
        atomic_write_json(JSON_BACKUP_FILE, all_keywords_data)
        log_msg("JSON 데이터 백업 디스크 저장 성공 완료", "DEBUG")
    except Exception as e:
        log_msg(f"⚠️ 데이터 백업 저장 실패: {e}", "ERROR")
