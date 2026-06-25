FROM python:3.11-slim

# ffmpeg + 기본 빌드 도구 설치
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 의존성 먼저 설치 (캐시 활용)
COPY requirements.txt .
RUN pip install --no-cache-dir \
    fastapi uvicorn[standard] pydantic pydantic-settings \
    supabase google-generativeai \
    youtube-transcript-api "yt-dlp>=2026.0.0" \
    python-multipart httpx PyJWT python-dotenv \
    faster-whisper

# 앱 코드 복사
COPY main.py .
COPY app/ ./app/

# Cloud Run은 PORT 환경변수 사용
ENV PORT=8080
ENV APP_HOST=0.0.0.0
ENV APP_PORT=8080

EXPOSE 8080

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT}"]
