# 베이스 이미지를 Selenium 공식 이미지로 변경
FROM selenium/standalone-chrome:latest

# 2. apt-get 명령을 실행하기 전, 반드시 root 권한으로 전환
USER root

# Chromium 브라우저 및 한글 폰트 설치
RUN apt-get update && apt-get install -y \
    fonts-nanum \
    && rm -rf /var/lib/apt/lists/*

# 출력 디렉토리 생성
RUN mkdir -p /output

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY *.py ./

# 보안을 위해 이미지 기본 비특권 사용자(seluser, uid 1200 / gid 1201)로 실행
# 호스트에 마운트하는 출력 폴더도 이 사용자에게 쓰기 권한이 있어야 함:
#   sudo chown -R 1200:1201 /volume2/docker/fmkorea-scraper/output
RUN chown -R seluser:seluser /output /app
USER seluser

# 실시간 로그 출력을 위해 -u (unbuffered) 옵션 사용
CMD ["python", "-u", "fmkorea-scraper.py"]
