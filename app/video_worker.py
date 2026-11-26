"""
동영상 변환 작업기 (fmkorea-convert 컨테이너에서 실행): video_jobs의 작업을 꺼내 video_convert.run_job으로 처리

줄 둘을 따로 돌림
- 빠른 줄: 화면은 복사하고 포장·소리만 바꾸는 작업(remux). 재생 버튼을 누른 사람이 기다리므로 늘 바로
- 느린 줄: 화면까지 다시 부호화(transcode)·자동 변환(auto)
자동 변환(VIDEO_AUTO_CONVERT, 기본 켬): 자동 변환 시간(VIDEO_AUTO_HOURS, 기본 새벽 2~8시)에만.
그 시간이 되면 하루 한 번 동영상 폴더 전체를 훑어 변환이 필요한 영상을 넣고 차례로 변환, 끝나는 시각에 도는 자동 변환도 멈춤.
직접 누른 '지금 변환'은 시간과 관계없이 늘 먼저
미리 고치기: 시간과 관계없이 쉬는 때(최근 VIDEO_IDLE_AFTER_PLAY초 안에 아무도 영상을 재생하지 않음)에 표시 순서표가 빠진
MP4(video_fix)를 최근 것부터 미리 고쳐 둠 (처음 열 때 수십 초 기다리지 않게). 누가 보기 시작하면 멈추고 다음에 이어서
(한 번 본 영상은 기억해 두므로 다시 보지 않음). 파일에서 필요한 몇십 바이트씩만 읽어 변환보다 훨씬 가벼움
썸네일 미리 만들기: THUMB_SCAN_SECONDS마다 동영상 폴더를 훑어 썸네일이 없는 영상(새로 들어온 것부터)을 미리 만들어 둠
(목록을 처음 열 때 기다리지 않게). 쓰지 않게 된 썸네일은 정리 때 지움
"""
import threading
import time

from datetime import date

from config import VIDEO_AUTO_CONVERT, log_msg, short_err
import storage
import video_convert
import video_fix
import videos

POLL_SECONDS = 3
# 대시보드 'NAS 상태'가 이 작업기가 살아 있는지 보도록 남기는 기록 간격 (system_status.CONVERT_HEARTBEAT_META)
HEARTBEAT_SECONDS = 60
CLEANUP_EVERY = 6 * 3600
SCAN_CHECK_SECONDS = 300
FIX_CHECK_SECONDS = 120
# 썸네일 없는 영상을 찾는 간격, 한 번에 만드는 시간 (넘으면 다시 훑어 그사이 새로 들어온 영상부터)
THUMB_SCAN_SECONDS = 60
THUMB_BATCH_SECONDS = 120


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


def auto_scanner():
    """자동 변환 시간에 하루 한 번 폴더 전체를 훑음 (시간이 끝나면 멈춤. 조사 결과는 기억해 두어 다음에는 새 영상만 조사)"""
    last_day = None
    while True:
        try:
            if video_convert.auto_time() and last_day != date.today():
                last_day = date.today()
                started = time.time()
                seen, added = video_convert.scan_library(video_convert.auto_time)
                log_msg(f"[변환] 자동 변환: 영상 {seen}개 훑어 {added}개 넣음 ({time.time() - started:.0f}초)")
        except Exception as e:  # noqa: BLE001
            log_msg(f"[변환] 자동 변환 오류: {short_err(e)}", 'WARN')
        time.sleep(SCAN_CHECK_SECONDS)


def fix_preparer():
    """쉬는 때 표시 순서표를 아직 안 본 MP4를 최근 것부터 미리 봐 두고 고칠 것은 고쳐 둠"""
    while True:
        try:
            if not video_convert.recently_played():
                started = time.time()
                count = 0
                for full in video_convert.unprepared_mp4s():
                    if video_convert.recently_played():
                        break
                    video_fix.layout(full)
                    count += 1
                if count:
                    log_msg(f"[미리 고치기] 영상 {count}개 미리 봄 ({time.time() - started:.0f}초)")
        except Exception as e:  # noqa: BLE001
            log_msg(f"[미리 고치기] 오류: {short_err(e)}", 'WARN')
        time.sleep(FIX_CHECK_SECONDS)


def thumb_filler():
    """썸네일이 없는 영상을 찾아 미리 만듦. 뽑지 못한 영상은 이 작업기가 다시 시작하거나 영상이 바뀔 때까지 다시 하지 않음"""
    failed = set()
    while True:
        try:
            started = time.time()
            made = 0
            for full, path in video_convert.missing_thumbnails(failed):
                if videos.make_thumbnail(full):
                    made += 1
                else:
                    failed.add(path)
                if time.time() - started > THUMB_BATCH_SECONDS:
                    break
            if made:
                log_msg(f"[썸네일] {made}개 미리 만듦 ({time.time() - started:.0f}초)")
        except Exception as e:  # noqa: BLE001
            log_msg(f"[썸네일] 오류: {short_err(e)}", 'WARN')
        time.sleep(THUMB_SCAN_SECONDS)


def heartbeat():
    while True:
        try:
            storage.set_meta('convert_heartbeat', storage._now())
        except Exception as e:  # noqa: BLE001 - 기록을 못 해도 변환은 계속
            log_msg(f"[변환] 상태 기록 실패: {short_err(e)}", 'DEBUG')
        time.sleep(HEARTBEAT_SECONDS)


def main():
    storage.init_db()
    threading.Thread(target=heartbeat, name='convert-heartbeat', daemon=True).start()
    video_convert.recover()
    log_msg('[변환] 작업기 시작')
    for name in ('fast', 'slow'):
        threading.Thread(target=lane, args=(name,), name=f'convert-{name}', daemon=True).start()
    if VIDEO_AUTO_CONVERT:
        threading.Thread(target=auto_scanner, name='convert-auto-scan', daemon=True).start()
        log_msg(f'[변환] 자동 변환 켬 (매일 {video_convert.AUTO_START}시~{video_convert.AUTO_END}시)')
    threading.Thread(target=fix_preparer, name='fix-preparer', daemon=True).start()
    threading.Thread(target=thumb_filler, name='thumb-filler', daemon=True).start()
    while True:
        try:
            removed = video_convert.cleanup()
            if removed:
                log_msg(f"[변환] 원본이 바뀌거나 없어진 변환본 {removed}개 지움")
            removed = video_convert.cleanup_thumbnails()
            if removed:
                log_msg(f"[썸네일] 영상이 바뀌거나 없어진 썸네일 {removed}개 지움")
        except Exception as e:  # noqa: BLE001
            log_msg(f"[변환] 정리 오류: {short_err(e)}", 'WARN')
        time.sleep(CLEANUP_EVERY)


if __name__ == '__main__':
    main()
