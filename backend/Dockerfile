FROM python:3.11-slim

# ffmpeg + 기본 빌드 도구 + Node.js(bgutil POT 토큰 서버용) 설치
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    ca-certificates \
    git \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# bgutil-ytdlp-pot-provider HTTP 서버 빌드
# YouTube가 서버 IP를 봇으로 판단해 요구하는 PO Token을 로컬에서 발급해 yt-dlp에 공급한다.
RUN git clone --single-branch --branch 1.3.1 --depth 1 \
    https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git /opt/bgutil-provider \
    && cd /opt/bgutil-provider/server \
    && npm ci \
    && npx tsc

# 의존성 먼저 설치 (requirements.txt 기반 + google-genai 명시)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir google-genai "yt-dlp>=2026.0.0"

# 앱 코드 복사
COPY main.py .
COPY app/ ./app/
COPY docker/start.sh /app/start.sh
RUN chmod +x /app/start.sh

# Cloud Run은 PORT 환경변수 사용
ENV PORT=8080
ENV APP_HOST=0.0.0.0
ENV APP_PORT=8080
ENV BGUTIL_POT_PORT=4416

EXPOSE 8080

CMD ["/app/start.sh"]
