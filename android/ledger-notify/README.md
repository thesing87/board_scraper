# 가계부 알림 (안드로이드 앱)

휴대폰의 카드 결제 알림을 가계부의 **확인 대기함**으로 보내는 앱. 서버 쪽은 `app/ledger.py`의 연결 주소(`/api/ledger/hook/<키>`)를 그대로 씀.

- 결제 알림처럼 보이는 글(`O원` 금액 + 승인·결제·취소 같은 낱말)만 보냄 — 다른 알림은 휴대폰 밖으로 나가지 않음
- 인터넷이 안 되면 모아 두었다가 연결되면 다시 보냄 (휴대폰을 껐다 켜도)
- 같은 알림이 10분 안에 또 오면 한 번만
- 앱마다 끄기, 최근 보낸 알림과 서버의 답 보기, 시험 알림 보내기

## 배포 (가계부 페이지로)

빌드한 `app-release.apk`를 가계부의 관리자 칸 → '가계부 알림 앱 파일 (APK)'에서 올리면, 가계부를 쓰는 사람 모두가
'결제 알림 자동 기록' → **가계부 알림 앱 받기**로 받음 (`app/ledger_app.py`, 파일은 `output/ledger_app/`).
올릴 때 APK 안의 패키지 이름(`kr.home.ledgernotify`)과 버전을 확인하고, 지금 올라가 있는 것보다 낮은 버전은 거절함.

## 설치

1. 가계부에서 **가계부 알림 앱 받기** → 받은 파일 열기 → '출처를 알 수 없는 앱' 설치 허용
2. 앱을 열고 **알림 읽기 권한 열기** → '가계부 알림' 켜기
   - 회색이라 안 켜지면(안드로이드 13 이상): **앱 정보 열기** → 오른쪽 위 ⋮ → **제한된 설정 허용** → 다시 켜기
3. **배터리 사용 '제한 없음'으로**
4. 가계부 → '결제 알림 자동 기록' → '연결 주소 만들기' → 복사 → 앱에서 **붙여넣기**
5. **시험 알림 보내기** → 가계부 확인 대기함에 1,000원 시험 결제가 뜨면 끝

## 빌드 (Windows)

이 PC에는 `D:\android` 아래에 JDK 17·안드로이드 SDK 34·Gradle 8.7이 있음 (안드로이드 스튜디오 없이).

```powershell
$env:JAVA_HOME = 'D:\android\jdk17'
D:\android\gradle-8.7\bin\gradle.bat assembleRelease --no-daemon
# → app\build\outputs\apk\release\app-release.apk
```

- `local.properties`: `sdk.dir=D\:/android/sdk`
- 서명: `keystore.properties`가 있으면 그 키로 (원본은 `D:\android\keys`, git에 안 올림). 새 버전은 **같은 키**로 서명해야 지우지 않고 덮어 설치됨 — 키를 잃어버리면 앱을 지우고 다시 설치(설정도 다시)해야 하니 `D:\android\keys`를 백업해 둘 것
- 새 버전을 낼 때는 `app/build.gradle`의 `versionCode`를 올림
