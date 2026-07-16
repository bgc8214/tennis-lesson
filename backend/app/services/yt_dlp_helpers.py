"""Shared yt-dlp options for YouTube extraction."""

from __future__ import annotations

import base64
import logging
import os
import shutil
from typing import Any, Dict


def _redact_proxy(proxy_url: str) -> str:
    """로그용 프록시 URL — 자격증명(user:pass) 마스킹."""
    if "@" in proxy_url:
        scheme_sep = proxy_url.find("://")
        prefix = proxy_url[: scheme_sep + 3] if scheme_sep != -1 else ""
        return prefix + "***@" + proxy_url.rsplit("@", 1)[1]
    return proxy_url


def build_youtube_ydl_opts(
    base_opts: Dict[str, Any],
    *,
    tmp_dir: str,
    logger: logging.Logger,
) -> Dict[str, Any]:
    """Return yt-dlp options with Cloud Run anti-bot support."""
    opts = dict(base_opts)

    # bgutil PO Token 프로바이더는 web/mweb 클라이언트에 토큰을 공급한다.
    # android/ios로 고정하면 PO Token 경로 자체가 적용되지 않으므로 web 계열을 사용한다.
    if "extractor_args" not in opts:
        opts["extractor_args"] = {"youtube": {"player_client": ["web", "mweb"]}}
    opts.setdefault("updatetime", False)

    # 데이터센터 IP 봇 감지 우회: YTDLP_PROXY 설정 시 모든 YouTube 트래픽을
    # 해당 프록시(주로 residential proxy)로 라우팅한다. 오디오 전용 다운로드라
    # 회당 트래픽이 작아(1시간 영상 ≈ 30MB) 프록시 비용 부담이 적다.
    from app.config import get_settings

    proxy = (get_settings().YTDLP_PROXY or "").strip()
    if proxy:
        opts.setdefault("proxy", proxy)
        logger.info("yt-dlp 프록시 사용: %s", _redact_proxy(proxy))

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
