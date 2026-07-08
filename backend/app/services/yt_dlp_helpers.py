"""Shared yt-dlp options for YouTube extraction."""

from __future__ import annotations

import base64
import logging
import os
import shutil
from typing import Any, Dict


def build_youtube_ydl_opts(
    base_opts: Dict[str, Any],
    *,
    tmp_dir: str,
    logger: logging.Logger,
) -> Dict[str, Any]:
    """Return yt-dlp options with Cloud Run anti-bot support."""
    opts = dict(base_opts)

    # Android/iOS 클라이언트로 봇 감지 우회 — Cloud Run 등 서버 IP에서 필수
    if "extractor_args" not in opts:
        opts["extractor_args"] = {"youtube": {"player_client": ["android", "ios"]}}
    opts.setdefault("updatetime", False)

    cookies_env = os.environ.get("YT_COOKIES_B64", "")
    if cookies_env:
        try:
            cookies_data = base64.b64decode(cookies_env).decode("utf-8")
            cookies_tmp = os.path.join(tmp_dir, "cookies.txt")
            with open(cookies_tmp, "w") as f:
                f.write(cookies_data)
            opts["cookiefile"] = cookies_tmp
            logger.info("쿠키 환경변수에서 로드됨")
            return opts
        except Exception as e:
            logger.warning("쿠키 환경변수 파싱 실패: %s", e)

    for cookies_path in ("/secrets/cookies.txt", "/tmp/cookies.txt"):
        if os.path.exists(cookies_path):
            cookies_tmp = os.path.join(tmp_dir, "cookies.txt")
            shutil.copyfile(cookies_path, cookies_tmp)
            opts["cookiefile"] = cookies_tmp
            logger.info("쿠키 파일 사용: %s", cookies_path)
            break

    return opts
