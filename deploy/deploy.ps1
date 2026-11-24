# NAS 배포: NAS 프로젝트 폴더에서 GitHub main의 최신 코드를 받고(deploy/update.sh) 컨테이너를 재시작(필요하면 재빌드)
#   .\deploy\deploy.ps1            새 커밋이 있으면 받고 재시작 (코드만 바뀌었으면 수 초)
#   .\deploy\deploy.ps1 -Restart   새 커밋이 없어도 재시작
#   .\deploy\deploy.ps1 -Rebuild   이미지를 강제로 재빌드 (NAS에서 10분 이상)
#   .\deploy\deploy.ps1 -External  내부망 확인 없이 외부망(DDNS)으로 접속
#   .\deploy\deploy.ps1 -Upload    예전 방식: 이 PC의 파일(커밋 전 코드 포함)을 그대로 보내 재시작 (시험용)
# 배포 끝에 이 PC에 빌드한 정식 앱 APK(원래 키 서명)가 서버 것보다 새 버전이면 함께 올림 (맨 아래 'YeYe홈 앱' 참고)
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

# ---- YeYe홈 앱(APK): 이 PC에 새로 빌드한 정식 APK(assembleRelease)가 있고 서버에 올라간 것보다 버전이 높으면 함께 올림
#   - 서명이 원래 키(CN=Ledger Notify, 아래 지문)가 아니면 올리지 않음 (임시 시험 키로 서명한 것은 절대 안 됨)
#   - 서버에서는 웹의 관리자 올리기와 같은 확인(패키지·낮은 버전 거절)을 거침 (deploy/app_apk.py)
#   - 안드로이드 도구는 C:\android(회사 PC) 또는 D:\android(집 노트북)에서 찾음. 웹에서 올리는 방법도 그대로
$ReleaseCert = 'ddb6e2c7a013a2c3e4ee8b2b7e169eb3a74768e16a1029c1aef612222918eea8'
$Apk = Join-Path (Get-Location) 'android\ledger-notify\app\build\outputs\apk\release\app-release.apk'
function Find-AndroidTool([string]$Name) {
    foreach ($root in 'C:\android', 'D:\android') {
        $f = Get-ChildItem "$root\sdk\build-tools\*\$Name" -ErrorAction SilentlyContinue | Sort-Object FullName -Descending | Select-Object -First 1
        if ($f) { return $f.FullName }
    }
    return $null
}
if (-not (Test-Path $Apk)) { Write-Host '[앱] 이 PC에 빌드한 정식 APK가 없어 앱은 그대로'; return }
$ErrorActionPreference = 'Continue'
$aapt = Find-AndroidTool 'aapt.exe'
$signer = Find-AndroidTool 'apksigner.bat'
if (-not $aapt -or -not $signer) { Write-Host '[앱] 안드로이드 도구(C:\android 또는 D:\android)가 없어 앱은 그대로' -ForegroundColor Yellow; return }
$jdk = 'C:\android\jdk17', 'D:\android\jdk17' | Where-Object { Test-Path "$_\bin\java.exe" } | Select-Object -First 1
if ($jdk) { $env:JAVA_HOME = $jdk }

$badge = (& $aapt dump badging $Apk 2>$null | Select-String '^package:' | Select-Object -First 1).Line
if ($badge -notmatch "name='kr\.home\.ledgernotify'" -or $badge -notmatch "versionCode='(\d+)'") {
    Write-Host '[앱] 빌드한 APK가 YeYe홈 정식 앱이 아니어서 올리지 않음' -ForegroundColor Yellow; return
}
$localCode = [int]$Matches[1]
$localName = if ($badge -match "versionName='([^']*)'") { $Matches[1] } else { "$localCode" }
$certs = @(& $signer verify --print-certs $Apk 2>$null | Select-String 'certificate SHA-256 digest: ([0-9a-f]+)' | ForEach-Object { $_.Matches[0].Groups[1].Value })
if ($LASTEXITCODE -ne 0 -or $certs.Count -ne 1 -or $certs[0] -ne $ReleaseCert) {
    Write-Host "[앱] $localName($localCode) APK의 서명이 원래 키가 아니어서 올리지 않음" -ForegroundColor Red; return
}

$srvJson = ssh $Nas 'sudo -n /usr/local/bin/docker exec fmkorea-web python /app/deploy/app_apk.py info' 2>$null | Select-Object -Last 1
try { $srv = $srvJson | ConvertFrom-Json } catch { Write-Host '[앱] 서버의 앱 정보를 읽지 못해 앱은 그대로' -ForegroundColor Yellow; return }
$srvCode = if ($srv) { [int]$srv.versionCode } else { 0 }
if ($localCode -le $srvCode) { Write-Host "[앱] 서버에 이미 $($srv.versionName)($srvCode) - 앱은 그대로"; return }

# PowerShell 5.1 파이프는 바이너리를 깨뜨리므로 cmd의 < 로 보냄
$out = cmd /c "ssh $Nas `"sudo -n /usr/local/bin/docker exec -i fmkorea-web python /app/deploy/app_apk.py save`" < `"$Apk`" 2>nul" | Select-Object -Last 1
try { $res = $out | ConvertFrom-Json } catch { $res = $null }
if ($res -and $res.ok) { Write-Host "[앱] $($res.versionName)($($res.versionCode)) 올림 - 휴대폰 앱이 새 버전을 받아 설치 화면을 띄움" -ForegroundColor Green }
elseif ($res -and $res.error) { Write-Host "[앱] 올리지 않음: $($res.error)" -ForegroundColor Yellow }
else { Write-Host '[앱] 서버에 올리지 못함 (웹의 전체 설정 > 앱 파일에서 직접 올려 주세요)' -ForegroundColor Yellow }
