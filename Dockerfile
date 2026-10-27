# Selenium 공식 이미지 (크롬·크롬드라이버 포함). latest는 재빌드할 때마다 크롬이 바뀌어 수집이 갑자기 깨질 수 있어
# 지금 NAS에서 검증된 이미지로 고정: 2026-10-14 빌드, Google Chrome 155.0.8059.79, Python 3.14
# 올릴 때는 새 이미지로 시험한 뒤 아래 digest를 바꿀 것
FROM selenium/standalone-chrome@sha256:d6843a37cd2852fac7f33099709a203769f864dcf260e740a34e9605055c1dd5

# apt-get은 root 권한이 필요
USER root

# 한글 폰트 설치
RUN apt-get update && apt-get install -y \
    fonts-nanum \
    && rm -rf /var/lib/apt/lists/*

# 출력 디렉토리 생성
RUN mkdir -p /output

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# 보안을 위해 이미지 기본 비특권 사용자(seluser, uid 1200 / gid 1201)로 실행
# 호스트에 마운트하는 출력 폴더도 이 사용자에게 쓰기 권한이 있어야 함:
#   sudo chown -R 1200:1201 /volume2/docker/fmkorea-scraper/output
RUN chown -R seluser:seluser /output /app
USER seluser

# 실시간 로그 출력을 위해 -u (unbuffered) 옵션 사용
CMD ["python", "-u", "app/fmkorea-scraper.py"]
