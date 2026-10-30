# 최초 1회만 실행: NAS 프로젝트 폴더를 git 저장소로 만들어, 이후 deploy.ps1이 NAS에서 git pull로 배포하게 함
# (미리 DSM 패키지 센터에서 Git Server 설치)
#   1번째 실행: NAS 전용 GitHub 키를 만들고 공개 키를 보여줌 → GitHub 저장소 Settings > Deploy keys에 등록
#   2번째 실행: 접속을 확인하고 폴더를 백업한 뒤 git 저장소로 전환 (.env·output은 그대로)
# 접속은 deploy.ps1과 같은 ~/.ssh/config의 'nas' 별칭 사용
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot)
# PowerShell 5.1 파이프는 줄바꿈·인코딩을 바꾸므로 스크립트는 cmd 리다이렉트로 그대로 전달
Write-Host "[NAS] git 설정 진행 중..."
cmd /c "ssh nas sh -s < deploy\setup_nas_git.sh"
if ($LASTEXITCODE -eq 2) {
    Write-Host "`n위 키를 등록한 뒤 이 스크립트를 다시 실행해 주세요." -ForegroundColor Yellow
} elseif ($LASTEXITCODE -ne 0) {
    throw "[오류] NAS git 설정 실패 (종료 코드 $LASTEXITCODE)"
} else {
    Write-Host "[NAS] git 설정 끝" -ForegroundColor Green
}
