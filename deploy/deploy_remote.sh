#!/bin/sh
# deploy.ps1이 배포할 때마다 함께 전송하여 NAS에서 실행하는 스크립트 (프로젝트 폴더 기준으로 동작)
set -e
cd "$(dirname "$0")/.."
if [ ! -f .env ]; then echo '[오류] NAS에 .env 파일이 없습니다.'; exit 1; fi

# 컨테이너는 uid 1200 비root 사용자로 실행되므로 출력 폴더 소유권을 맞춤 (이미 맞으면 sudo 생략)
if [ "$(stat -c %u output 2>/dev/null || echo 0)" != "1200" ]; then
    sudo mkdir -p output
    sudo chown -R 1200:1201 output
fi

# compose.env: docker-compose 자체 설정 (sudo는 환경변수를 넘기지 않으므로 파일로 전달). 컨테이너 환경변수는 .env
if sudo -n /usr/local/bin/docker-compose version >/dev/null 2>&1; then
    dc() { sudo /usr/local/bin/docker-compose --env-file compose.env "$@"; }
else
    echo '[안내] 비밀번호 없는 sudo가 설정되지 않아 sudo 비밀번호를 물어봅니다. (setup_nas_sudo.ps1 실행 시 생략)'
    dc() { sudo env PATH="$PATH:/usr/local/bin" /usr/local/bin/docker-compose --env-file compose.env "$@"; }
fi

dk() { sudo -n /usr/local/bin/docker "$@"; }

# 코드는 프로젝트 폴더를 컨테이너에 연결해 쓰므로, 이미지는 Dockerfile·requirements.txt가 바뀔 때만 재빌드
# (NAS가 느려 재빌드는 10분 이상 걸리지만 재시작은 수 초)
BUILD_HASH=$(cat Dockerfile requirements.txt | md5sum | cut -d' ' -f1)
OLD_HASH=$(cat .build_hash 2>/dev/null || true)
# 수집기·웹서버 컨테이너가 함께 쓰는 이미지 이름 (docker-compose.yml의 image)
IMAGE=fmkorea-scraper:local
# 컨테이너를 둘로 나누기 전에 docker-compose가 자동으로 붙인 이름으로 만든 이미지가 있으면 그대로 이어서 씀 (재빌드 없이)
if ! dk image inspect "$IMAGE" >/dev/null 2>&1 && dk image inspect fmkorea-scraper_fmkorea-scraper >/dev/null 2>&1; then
    dk tag fmkorea-scraper_fmkorea-scraper "$IMAGE"
    echo "[빌드] 기존 이미지를 $IMAGE 이름으로 이어서 사용 (재빌드 없음)"
fi
if [ "$1" = "rebuild" ]; then
    REASON='재빌드 요청(-Rebuild)'
elif ! dk image inspect "$IMAGE" >/dev/null 2>&1; then
    REASON='이미지 없음'
elif [ -n "$OLD_HASH" ] && [ "$OLD_HASH" != "$BUILD_HASH" ]; then
    REASON='Dockerfile·requirements.txt 변경'
else
    REASON=''
fi

if [ -n "$REASON" ]; then
    echo "[빌드] 이미지 재빌드: $REASON (NAS에서 10분 이상 걸릴 수 있음)"
    dc up -d --build
    # 재빌드마다 남는 이름 없는 옛 이미지 정리 (디스크 확보)
    dk image prune -f >/dev/null 2>&1 || true
else
    # 수집기·웹서버 컨테이너 ID를 비교해, 하나라도 새로 만들어졌으면 설정이 바뀐 것
    containers() { dk ps -q -f name='^fmkorea-scraper$'; dk ps -q -f name='^fmkorea-web$'; }
    BEFORE=$(containers)
    # docker-compose.yml이 바뀌었으면 여기서 컨테이너를 새로 만듦 (재빌드 없음)
    dc up -d
    if [ "$(containers)" = "$BEFORE" ]; then
        echo '[재시작] 코드만 바뀌어 이미지 재빌드 없이 컨테이너만 재시작'
        dc restart
    else
        echo '[재시작] 컨테이너 설정이 바뀌어 새로 만듦 (이미지 재빌드 없음)'
    fi
fi
echo "$BUILD_HASH" > .build_hash
# 컨테이너가 새 이름의 이미지로 바뀌었으므로 예전 이름은 뗌 (같은 이미지면 이름만 빠지고, 재빌드로 달라졌으면 옛 이미지가 지워짐)
dk image rm fmkorea-scraper_fmkorea-scraper >/dev/null 2>&1 || true

echo '--- 최근 로그 ---'
sleep 5
dc logs --tail 20