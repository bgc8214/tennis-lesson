#!/bin/sh
set -e

# bgutil POT 토큰 서버를 백그라운드로 먼저 띄운다.
# yt-dlp는 기본값(http://127.0.0.1:4416)으로 이 서버를 자동 탐색한다.
node /opt/bgutil-provider/server/build/main.js --port "${BGUTIL_POT_PORT:-4416}" &

exec uvicorn main:app --host 0.0.0.0 --port "${PORT:-8080}"
