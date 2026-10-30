# NAS 배포: NAS 프로젝트 폴더에서 GitHub main의 최신 코드를 받고(deploy/update.sh) 컨테이너를 재시작(필요하면 재빌드)
#   .\deploy\deploy.ps1            새 커밋이 있으면 받고 재시작 (코드만 바뀌었으면 수 초)
#   .\deploy\deploy.ps1 -Restart   새 커밋이 없어도 재시작
#   .\deploy\deploy.ps1 -Rebuild   이미지를 강제로 재빌드 (NAS에서 10분 이상)
#   .\deploy\deploy.ps1 -External  내부망 확인 없이 외부망(DDNS)으로 접속
#   .\deploy\deploy.ps1 -Upload    예전 방식: 이 PC의 파일(커밋 전 코드 포함)을 그대로 보내 재시작 (시험용)
# NAS는 GitHub main만 받으므로, 바꾼 코드는 커밋·푸시하고 main에 머지한 뒤 배포
# 처음 한 번은 setup_nas_git.ps1로 NAS 프로젝트 폴더를 git 저장소로 만들어야 함
# 접속은 ~/.ssh/config의 'nas'(내부망)·'nas-ext'(외부망, 공유기 DDNS) 별칭과 SSH 키를 사용하므로 비밀번호를 묻지 않음.
# 내부망 NAS에 바로 연결되면 nas, 아니면(집 밖) nas-ext로 자동 전환
# (sudo 비밀번호까지 생략하려면 setup_nas_sudo.ps1을 최초 1회 실행)
param([switch]$Rebuild, [switch]$Restart, [switch]$External, [switch]$Upload)

$ErrorActionPreference = 'Stop'
$NasProject = '/volume2/docker/fmkorea-scraper'
Set-Location (Split-Path $PSScriptRoot)

function Test-SshAlias([string]$Alias, [int]$TimeoutMs = 1500) {
    # 별칭의 실제 주소·포트를 ssh 설정에서 읽어 TCP 연결만 짧게 시도 (주소를 이 스크립트에 따로 적지 않기 위함)
    $cfg = ssh -G $Alias
    $hostName = ($cfg | Where-Object { $_ -like 'hostname *' }) -replace '^hostname ', ''
    $port = [int](($cfg | Where-Object { $_ -like 'port *' }) -replace '^port ', '')
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        return ($client.ConnectAsync($hostName, $port).Wait($TimeoutMs) -and $client.Connected)
    } catch {
        return $false
    } finally {
        $client.Close()
    }
}

$Nas = if (-not $External -and (Test-SshAlias 'nas')) { 'nas' } else { 'nas-ext' }
Write-Host "[연결] $(if ($Nas -eq 'nas') { '내부망' } else { '외부망(DDNS)' }) 경로 사용: $Nas"

if ($Upload) {
    # .env·output은 NAS에 있는 것을 그대로 사용하므로 보내지 않음
    $files = @('app', 'deploy', 'Dockerfile', 'requirements.txt', 'docker-compose.yml', 'compose.env', '.dockerignore')
    Write-Host "[전송] $($files -join ', ')"
    Write-Host "[안내] NAS의 코드가 GitHub 버전과 달라지므로, 다음 일반 배포 전에 NAS 프로젝트 폴더에서 'git checkout -- . && git clean -fd'로 되돌려야 합니다 (.env·output은 남음)." -ForegroundColor Yellow
    # PowerShell 5.1 파이프는 바이너리를 깨뜨리므로 tar 스트림은 cmd 파이프로 전달
    cmd /c "tar -cf - $($files -join ' ') | ssh $Nas `"tar -xf - -C $NasProject`""
    if ($LASTEXITCODE -ne 0) { throw "[오류] NAS로 파일 전송 실패" }
    $arg = if ($Rebuild) { 'rebuild' } else { '' }
    ssh -t $Nas "sh $NasProject/deploy/deploy_remote.sh $arg"
    if ($LASTEXITCODE -ne 0) { throw "[오류] NAS 배포 스크립트 실패" }
    return
}

# NAS는 GitHub main을 받으므로, 이 PC에만 있는 변경은 반영되지 않는다는 것을 미리 알려 줌.
# 안내일 뿐이라 git 확인이 실패해도(네트워크 등) 조용히 넘어가고 배포는 그대로 진행
try {
    $ErrorActionPreference = 'Continue'
    git fetch --quiet origin main 2>$null
    if ($LASTEXITCODE -eq 0) {
        $notInMain = git rev-list --count origin/main..HEAD 2>$null
        if ($LASTEXITCODE -eq 0 -and [int]$notInMain -gt 0) {
            Write-Host "[안내] 이 PC의 커밋 $notInMain개가 GitHub main에 없어 이번 배포에 포함되지 않습니다 (푸시·머지 후 다시 배포)." -ForegroundColor Yellow
        }
        $dirty = git status --porcelain --untracked-files=no 2>$null
        if ($LASTEXITCODE -eq 0 -and $dirty) {
            Write-Host "[안내] 커밋하지 않은 변경은 배포되지 않습니다 (시험하려면 -Upload)." -ForegroundColor Yellow
        }
    }
} catch {
} finally {
    $ErrorActionPreference = 'Stop'
}

# NAS 폴더가 아직 git 저장소가 아니면(setup_nas_git.ps1 전) update.sh도 없으므로 먼저 안내
$arg = if ($Rebuild) { 'rebuild' } elseif ($Restart) { 'restart' } else { '' }
ssh -t $Nas "if [ -d $NasProject/.git ] && [ -f $NasProject/deploy/update.sh ]; then sh $NasProject/deploy/update.sh $arg; else exit 3; fi"
if ($LASTEXITCODE -eq 3) {
    Write-Host "[오류] NAS 프로젝트 폴더가 아직 git 저장소가 아닙니다." -ForegroundColor Red
    Write-Host "       처음 한 번 .\deploy\setup_nas_git.ps1로 전환한 뒤 다시 배포해 주세요. (전환 전에 급히 배포하려면 -Upload)" -ForegroundColor Yellow
    exit 1
}
if ($LASTEXITCODE -ne 0) { throw "[오류] NAS 배포 실패" }
