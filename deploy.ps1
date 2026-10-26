# NAS 배포: 코드를 NAS 프로젝트 폴더로 보내고 deploy_remote.sh로 컨테이너를 재시작(필요하면 재빌드)
#   .\deploy.ps1            코드만 바뀌었으면 재시작만 (수 초)
#   .\deploy.ps1 -Rebuild   이미지를 강제로 재빌드 (NAS에서 10분 이상)
# 접속은 ~/.ssh/config의 'nas' 별칭과 SSH 키를 사용하므로 비밀번호를 묻지 않음
# (sudo 비밀번호까지 생략하려면 setup_nas_sudo.ps1을 최초 1회 실행)
param([switch]$Rebuild)

$ErrorActionPreference = 'Stop'
$NasProject = '/volume2/docker/fmkorea-scraper'
Set-Location $PSScriptRoot

# .env·output은 NAS에 있는 것을 그대로 사용하므로 보내지 않음
$files = @(Get-ChildItem -Name *.py) + @('static', 'Dockerfile', 'requirements.txt', 'docker-compose.yml', 'deploy_remote.sh')
Write-Host "[전송] $($files -join ', ')"
# PowerShell 5.1 파이프는 바이너리를 깨뜨리므로 tar 스트림은 cmd 파이프로 전달
cmd /c "tar -cf - $($files -join ' ') | ssh nas `"tar -xf - -C $NasProject`""
if ($LASTEXITCODE -ne 0) { throw "[오류] NAS로 파일 전송 실패" }

$arg = if ($Rebuild) { 'rebuild' } else { '' }
ssh -t nas "sh $NasProject/deploy_remote.sh $arg"
if ($LASTEXITCODE -ne 0) { throw "[오류] NAS 배포 스크립트 실패" }
