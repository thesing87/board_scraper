"""배포할 때 YeYe홈 앱(APK)을 서버에 올림 (deploy.ps1이 웹 컨테이너 안에서 실행: docker exec -i fmkorea-web python /app/deploy/app_apk.py ...)

  python app_apk.py info          올라가 있는 앱 정보 (없으면 null)
  python app_apk.py save < x.apk  표준 입력의 APK를 웹의 관리자 올리기와 같은 확인(패키지·낮은 버전 거절)을 거쳐 바꿔 끼움
                                  → {ok, versionName, versionCode, ...} 또는 {error}

답은 모두 JSON 한 줄 (한글은 이스케이프해 PC 쪽 콘솔 글자표와 상관없이 읽히게).
서명 확인은 PC의 deploy.ps1이 apksigner로 먼저 함 (원래 키가 아니면 여기까지 오지 않음)
"""
import json
import sys

sys.path.insert(0, '/app/app')
import ledger_app  # noqa: E402


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ''
    if cmd == 'info':
        print(json.dumps(ledger_app.info()))
    elif cmd == 'save':
        try:
            new = ledger_app.save(sys.stdin.buffer.read(), '배포(PC)')
        except ledger_app.AppFileError as e:
            print(json.dumps({'error': str(e)}))
            sys.exit(2)
        print(json.dumps({'ok': True, **new}))
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == '__main__':
    main()
