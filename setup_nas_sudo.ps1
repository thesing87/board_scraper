# 최초 1회만 실행: NAS에서 docker·docker-compose를 sudo 비밀번호 없이 실행하도록 등록
# (deploy.ps1이 매번 비밀번호를 묻지 않게 하기 위함. 실행 중 NAS 비밀번호를 한 번 입력)
# DSM 업데이트로 설정이 지워지면 다시 실행
# 계정 이름은 NAS에서 직접 읽음(id -un). PowerShell 5.1은 외부 명령 인자의 큰따옴표를 깨뜨리므로 작은따옴표만 사용
$remote = "printf '%s ALL=(root) NOPASSWD: /usr/local/bin/docker-compose, /usr/local/bin/docker\n' `$(id -un) > /tmp/board-scraper-sudo" +
    " && sudo install -m 440 -o root -g root /tmp/board-scraper-sudo /etc/sudoers.d/board-scraper-docker; rm -f /tmp/board-scraper-sudo;" +
    " sudo -n /usr/local/bin/docker-compose version >/dev/null 2>&1 && echo SUDO_OK || echo SUDO_FAILED"
Write-Host "NAS sudo password (input is hidden):" -ForegroundColor Yellow
ssh -t nas $remote
