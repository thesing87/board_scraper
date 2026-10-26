# NAS 배포: 코드를 NAS 프로젝트 폴더로 보내고 deploy_remote.sh로 컨테이너를 재시작(필요하면 재빌드)
#   .\deploy.ps1            코드만 바뀌었으면 재시작만 (수 초)
#   .\deploy.ps1 -Rebuild   이미지를 강제로 재빌드 (NAS에서 10분 이상)
#   .\deploy.ps1 -External  내부망 확인 없이 외부망(DDNS)으로 접속
# 접속은 ~/.ssh/config의 'nas'(내부망)·'nas-ext'(외부망, 공유기 DDNS) 별칭과 SSH 키를 사용하므로 비밀번호를 묻지 않음.
# 내부망 NAS에 바로 연결되면 nas, 아니면(집 밖) nas-ext로 자동 전환
# (sudo 비밀번호까지 생략하려면 setup_nas_sudo.ps1을 최초 1회 실행)
param([switch]$Rebuild, [switch]$External)

$ErrorActionPreference = 'Stop'
$NasProject = '/volume2/docker/fmkorea-scraper'
Set-Location $PSScriptRoot

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

# .env·output은 NAS에 있는 것을 그대로 사용하므로 보내지 않음
$files = @(Get-ChildItem -Name *.py) + @('static', 'Dockerfile', 'requirements.txt', 'docker-compose.yml', 'deploy_remote.sh', 'compose.env', '.dockerignore')
Write-Host "[전송] $($files -join ', ')"
# PowerShell 5.1 파이프는 바이너리를 깨뜨리므로 tar 스트림은 cmd 파이프로 전달
cmd /c "tar -cf - $($files -join ' ') | ssh $Nas `"tar -xf - -C $NasProject`""
if ($LASTEXITCODE -ne 0) { throw "[오류] NAS로 파일 전송 실패" }

$arg = if ($Rebuild) { 'rebuild' } else { '' }
ssh -t $Nas "sh $NasProject/deploy_remote.sh $arg"
if ($LASTEXITCODE -ne 0) { throw "[오류] NAS 배포 스크립트 실패" }
