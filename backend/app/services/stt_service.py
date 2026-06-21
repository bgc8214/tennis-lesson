"""faster-whisper 기반 STT 서비스.

자막이 없을 때만 사용된다. yt-dlp로 오디오만 다운로드하고
faster-whisper로 한국어 텍스트로 변환한다.
"""

from __future__ import annotations

import logging
import os
import tempfile
from functools import lru_cache
from typing import Any

from app.config import get_settings

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _load_model() -> Any:
    from faster_whisper import WhisperModel
    settings = get_settings()
    model_size = settings.WHISPER_MODEL_SIZE or "base"
    logger.info("Loading faster-whisper model: %s", model_size)
    # cpu + int8 — 가장 가볍고 안정적
    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    return model


def _download_audio(url: str, tmp_dir: str) -> str:
    import yt_dlp
    settings = get_settings()
    out_template = os.path.join(tmp_dir, "audio.%(ext)s")

    ydl_opts = {
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
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])

    for name in os.listdir(tmp_dir):
        if name.lower().endswith(".mp3"):
            return os.path.join(tmp_dir, name)

    raise RuntimeError("yt-dlp did not produce an mp3 file")


def transcribe_from_url(url: str) -> str:
    with tempfile.TemporaryDirectory(prefix="tennis-stt-") as tmp_dir:
        try:
            audio_path = _download_audio(url, tmp_dir)
        except Exception as e:
            logger.warning("audio download failed: %s", e)
            raise RuntimeError(f"audio_download_failed: {e}") from e

        try:
            model = _load_model()
            segments, _ = model.transcribe(
                audio_path,
                language="ko",
                beam_size=5,
            )
            lines = []
            for seg in segments:
                lines.append(f"[{seg.start:.1f}s] {seg.text.strip()}")
            text = "\n".join(lines)
        except Exception as e:
            logger.warning("faster-whisper transcribe failed: %s", e)
            raise RuntimeError(f"whisper_transcribe_failed: {e}") from e

        return text.strip()
