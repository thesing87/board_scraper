"""
동영상 변환 작업기 (fmkorea-convert 컨테이너에서 실행): video_jobs의 작업을 꺼내 video_convert.run_job으로 처리

줄 둘을 따로 돌림
- 빠른 줄: 화면은 복사하고 포장·소리만 바꾸는 작업(remux). 재생 버튼을 누른 사람이 기다리므로 늘 바로
- 느린 줄: 화면까지 다시 부호화(transcode)·폴더 예약(auto). 밤 예약은 1~7시에만 시작
"""
import threading
import time

from config import log_msg, short_err
import storage
import video_convert

POLL_SECONDS = 3
CLEANUP_EVERY = 6 * 3600


def lane(name):
    while True:
        try:
            found = video_convert.next_job(name)
            if not found:
                time.sleep(POLL_SECONDS)
                continue
            rel, kind = found
            if not video_convert._claim(rel):
                continue
            log_msg(f"[변환] 시작 ({name}): {rel}")
            started = time.time()
            result = video_convert.run_job(rel, kind)
            level = 'WARN' if result == 'failed' else 'INFO'
            log_msg(f"[변환] {result} ({time.time() - started:.0f}초): {rel}", level)
        except Exception as e:  # noqa: BLE001 - 한 작업이 실패해도 줄은 계속
            log_msg(f"[변환] 오류: {short_err(e)}", 'ERROR')
            time.sleep(POLL_SECONDS * 5)


def main():
    storage.init_db()
    video_convert.recover()
    log_msg('[변환] 작업기 시작')
    for name in ('fast', 'slow'):
        threading.Thread(target=lane, args=(name,), name=f'convert-{name}', daemon=True).start()
    while True:
        try:
            removed = video_convert.cleanup()
            if removed:
                log_msg(f"[변환] 원본이 바뀌거나 없어진 변환본 {removed}개 지움")
        except Exception as e:  # noqa: BLE001
            log_msg(f"[변환] 정리 오류: {short_err(e)}", 'WARN')
        time.sleep(CLEANUP_EVERY)


if __name__ == '__main__':
    main()
