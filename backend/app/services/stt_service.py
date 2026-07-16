"""STT 서비스 (레거시 진입점).

실제 전사는 stt_providers(STT_PROVIDER: local | groq)에 위임한다.
환청(hallucination) 필터가 적용된 세그먼트만 반환된다.
"""

from __future__ import annotations

import logging
import os
import tempfile

from app.config import get_settings
from app.services.stt_filters import segments_to_transcript_text
from app.services.yt_dlp_helpers import build_youtube_ydl_opts

logger = logging.getLogger(__name__)


def _download_audio(url: str, tmp_dir: str) -> str:
    import yt_dlp

    settings = get_settings()
    out_template = os.path.join(tmp_dir, "audio.%(ext)s")

    ydl_opts = build_youtube_ydl_opts(
        {
            "format": "bestaudio/best",
            "outtmpl": out_template,
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "64",
            }],
            "match_filter": yt_dlp.utils.match_filter_func(
                f"duration <=? {settings.YTDLP_MAX_DURATION_SEC}"
            ),
        },
        tmp_dir=tmp_dir,
        logger=logger,
    )

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])

    for name in os.listdir(tmp_dir):
        if name.lower().endswith(".mp3"):
            return os.path.join(tmp_dir, name)

    raise RuntimeError("yt-dlp did not produce an mp3 file")


def transcribe_from_url(url: str) -> str:
    """YouTube URL → 오디오 다운로드 → STT 전사 텍스트 반환."""
    from app.services import stt_providers

    with tempfile.TemporaryDirectory(prefix="tennis-stt-") as tmp_dir:
        try:
            audio_path = _download_audio(url, tmp_dir)
        except Exception as e:
            logger.warning("audio download failed: %s", e)
            raise RuntimeError(f"audio_download_failed: {e}") from e

        try:
            segments, stats = stt_providers.transcribe_audio(audio_path)
            logger.info("stt stats: %s", stats)
            text = segments_to_transcript_text(segments)
        except Exception as e:
            logger.warning("stt transcribe failed: %s", e)
            raise RuntimeError(f"whisper_transcribe_failed: {e}") from e

        return text.strip()
