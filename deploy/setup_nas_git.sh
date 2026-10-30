#!/bin/sh
# setup_nas_git.ps1이 NAS에서 실행하는 최초 설정. 끝날 때까지 여러 번 실행해도 안전 (이미 된 단계는 건너뜀)
#   1) GitHub 전용 읽기 키(deploy key)를 만들고 공개 키를 보여줌 → GitHub 저장소에 등록 후 다시 실행
#   2) 키로 GitHub에 접속되면 프로젝트 폴더를 백업한 뒤 git 저장소로 전환 (.env·output은 그대로)
set -e
PROJECT=/volume2/docker/fmkorea-scraper
REPO=thesing87/board_scraper
BRANCH=main
KEY="$HOME/.ssh/board_scraper_deploy"
HOST_ALIAS=github-board-scraper

# 이 스크립트는 ssh로 표준 입력을 통해 전달되어 한 줄씩 읽히는데, 안에서 실행하는 ssh 등이 표준 입력을 읽으면
# 남은 줄을 삼켜 버림. 전체를 함수로 먼저 읽어 들인 뒤 마지막 줄에서 실행하고, 안쪽 ssh에는 /dev/null을 줌
main() {
    if ! command -v git >/dev/null 2>&1; then
        echo '[오류] NAS에 git이 없습니다. DSM 패키지 센터에서 Git Server를 설치한 뒤 다시 실행해 주세요.'
        exit 1
    fi

    # 1) 이 저장소 전용 SSH 키와 별칭 (개인 계정 키를 NAS에 두지 않도록 읽기 전용 deploy key 사용)
    mkdir -p "$HOME/.ssh" && chmod 700 "$HOME/.ssh"
    if [ ! -f "$KEY" ]; then
        ssh-keygen -q -t ed25519 -N '' -C "nas-deploy@$REPO" -f "$KEY" </dev/null
        echo '[키] GitHub 접속용 키를 만들었습니다.'
    fi
    if ! grep -q "^Host $HOST_ALIAS\$" "$HOME/.ssh/config" 2>/dev/null; then
        printf '\nHost %s\n    HostName github.com\n    User git\n    IdentityFile %s\n    IdentitiesOnly yes\n    StrictHostKeyChecking accept-new\n' \
            "$HOST_ALIAS" "$KEY" >> "$HOME/.ssh/config"
        chmod 600 "$HOME/.ssh/config"
    fi

    # GitHub은 셸을 주지 않아 성공해도 종료 코드가 1이므로 안내 문구로 판단
    if ! ssh -T "$HOST_ALIAS" </dev/null 2>&1 | grep -q 'successfully authenticated'; then
        echo
        echo '[등록 필요] 아래 공개 키를 GitHub에 등록한 뒤 이 설정을 다시 실행해 주세요.'
        echo "  https://github.com/$REPO/settings/keys → Add deploy key (Allow write access는 체크하지 않음)"
        echo
        cat "$KEY.pub"
        exit 2
    fi
    echo '[키] GitHub 접속 확인'

    # 2) 프로젝트 폴더를 git 저장소로 전환
    cd "$PROJECT"
    if [ -d .git ] && git rev-parse --verify -q HEAD >/dev/null; then
        echo "[완료] 이미 git 저장소입니다: $(git log -1 --format='%h %s')"
        exit 0
    fi
    # 혹시 모를 상황에 대비해 데이터(output)를 뺀 폴더 전체를 백업 (전환이 중간에 실패해 다시 실행할 때는 첫 백업을 유지)
    if [ ! -d .git ]; then
        backup="$PROJECT/../fmkorea-scraper-before-git-$(date +%Y%m%d%H%M%S).tar.gz"
        tar -czf "$backup" --exclude=./output --exclude=@eaDir .
        echo "[백업] $backup"
        git init -q
    fi
    git remote get-url origin >/dev/null 2>&1 || git remote add origin "$HOST_ALIAS:$REPO.git"
    git fetch -q origin "$BRANCH"
    # 코드 파일은 GitHub 버전으로 맞추고, git에 없는 파일(.env·output 등)은 건드리지 않음
    git checkout -q -f -B "$BRANCH" "origin/$BRANCH"
    git branch -q --set-upstream-to="origin/$BRANCH"
    echo "[완료] git 저장소로 전환: $(git log -1 --format='%h %s')"
    leftover=$(git status --porcelain)
    if [ -n "$leftover" ]; then
        echo '[안내] git에 없는 파일이 남아 있습니다 (예전 배포로 남은 파일이면 지워도 됨):'
        echo "$leftover"
    fi
    echo '이후 배포는 PC에서 deploy\deploy.ps1 (또는 NAS에서 sh deploy/update.sh)'
}

main "$@"
