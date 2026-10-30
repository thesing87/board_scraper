#!/bin/sh
# NAS에서 GitHub의 main 최신 코드를 받아(git pull) 배포. deploy.ps1이 ssh로 실행하며, NAS에서 직접 실행해도 됨
#   sh deploy/update.sh            새 커밋이 있으면 받고 재시작 (Dockerfile·requirements.txt가 바뀌었으면 재빌드)
#   sh deploy/update.sh restart    새 커밋이 없어도 재시작
#   sh deploy/update.sh rebuild    최신 코드를 받고 이미지를 강제로 재빌드
# 처음 한 번은 setup_nas_git.ps1로 NAS 프로젝트 폴더를 git 저장소로 만들어야 함
set -e
BRANCH=main

# git pull이 이 파일 자체를 바꿀 수 있으므로, 전체를 함수로 읽어 들인 뒤 마지막 줄에서 실행
main() {
    cd "$(dirname "$0")/.."
    if [ ! -d .git ]; then
        echo '[오류] NAS 프로젝트 폴더가 아직 git 저장소가 아닙니다. PC에서 deploy\setup_nas_git.ps1을 먼저 실행해 주세요.'
        exit 1
    fi
    # NAS에서 코드 파일을 직접 고쳤거나 예전 방식(deploy.ps1 -Upload)으로 덮어쓴 경우: 덮어쓰지 않고 멈춤
    if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
        echo '[오류] NAS의 코드 파일이 GitHub 버전과 다르게 바뀌어 있어 받지 않았습니다:'
        git status --short --untracked-files=no
        echo '       NAS의 변경을 버리고 GitHub 버전으로 맞추려면 NAS에서: git checkout -- . 후 다시 실행'
        exit 1
    fi

    before=$(git rev-parse HEAD)
    git fetch --quiet origin "$BRANCH"
    git merge --ff-only --quiet "origin/$BRANCH"
    after=$(git rev-parse HEAD)

    if [ "$before" = "$after" ]; then
        if [ -z "$1" ]; then
            echo "[업데이트] 이미 최신입니다 ($(git log -1 --format='%h %s')). 재시작하지 않음 (강제로 하려면 restart)"
            exit 0
        fi
        echo "[업데이트] 새 커밋 없음 ($(git log -1 --format='%h %s'))"
    else
        echo '[업데이트] 받은 커밋:'
        git log --format='  %h %s' "$before..$after"
    fi
    # 받은 뒤의 배포 스크립트로 재시작(필요하면 재빌드)
    sh deploy/deploy_remote.sh "$1"
}

main "$@"
