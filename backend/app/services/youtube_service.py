"""YouTube 자막/메타 추출 서비스.

- get_transcript: youtube-transcript-api 우선, 실패 시 (None, "stt") 반환
- extract_video_id: 다양한 형식의 YouTube URL에서 11자리 video_id 추출
- get_video_metadata: yt-dlp로 영상 제목/길이/썸네일 메타 조회
"""

from __future__ import annotations

import logging
import re
import tempfile
from typing import Optional, Tuple
from urllib.parse import parse_qs, urlparse

from app.config import get_settings
from app.services.yt_dlp_helpers import build_youtube_ydl_opts

logger = logging.getLogger(__name__)


# 11자리 YouTube video id 정규식
_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")


def extract_video_id(url: str) -> str:
    """YouTube URL에서 11자리 video_id를 추출한다.

    지원 형식:
      - https://www.youtube.com/watch?v=VIDEO_ID
      - https://youtu.be/VIDEO_ID
      - https://www.youtube.com/shorts/VIDEO_ID
      - https://www.youtube.com/embed/VIDEO_ID
      - https://m.youtube.com/watch?v=VIDEO_ID

    Raises:
        ValueError: 추출 실패 시.
    """
    if not url:
        raise ValueError("YouTube URL is empty")

    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()

    # youtu.be/<id>
    if host == "youtu.be":
        candidate = parsed.path.lstrip("/").split("/")[0]
        if _VIDEO_ID_RE.match(candidate):
            return candidate

    # youtube.com/...
    if "youtube.com" in host:
        # /watch?v=<id>
        if parsed.path == "/watch":
            qs = parse_qs(parsed.query)
            v = qs.get("v", [None])[0]
            if v and _VIDEO_ID_RE.match(v):
                return v

        # /shorts/<id>, /embed/<id>, /v/<id>
        for prefix in ("/shorts/", "/embed/", "/v/"):
            if parsed.path.startswith(prefix):
                candidate = parsed.path[len(prefix):].split("/")[0]
                if _VIDEO_ID_RE.match(candidate):
                    return candidate

    # 마지막 폴백: URL 어딘가에 11자 video id 패턴
    fallback = re.search(r"([A-Za-z0-9_-]{11})", url)
    if fallback:
        return fallback.group(1)

    raise ValueError(f"Cannot extract YouTube video_id from URL: {url}")


def get_transcript(video_url: str) -> Tuple[Optional[str], str]:
    """한글(우선) → 영어 → 자동생성 순으로 자막을 시도한다.

    Returns:
        (transcript_text, source)
          - 성공: ("[12.3s] 텍스트\\n[14.1s] ...", "subtitle")
          - 실패: (None, "stt")  ← stt_service로 폴백 신호
    """
    try:
        from youtube_transcript_api import (  # type: ignore
            YouTubeTranscriptApi,
        )
        try:
            from youtube_transcript_api import (  # type: ignore
                NoTranscriptFound,
                TranscriptsDisabled,
            )
        except ImportError:  # 구버전 호환
            from youtube_transcript_api._errors import (  # type: ignore
                NoTranscriptFound,
                TranscriptsDisabled,
            )
    except Exception as e:  # pragma: no cover
        logger.error("youtube-transcript-api import failed: %s", e)
        return None, "stt"

    try:
        video_id = extract_video_id(video_url)
    except ValueError as e:
        logger.warning("extract_video_id failed: %s", e)
        return None, "stt"

    settings = get_settings()
    preferred = settings.transcript_languages or ["ko", "ko-KR", "en"]

    try:
        # youtube-transcript-api 1.x: 인스턴스 메서드
        api = YouTubeTranscriptApi()

        # 한국어/영어 순으로 직접 fetch 시도
        fetched = None
        for lang in preferred:
            try:
                fetched = api.fetch(video_id, languages=[lang])
                break
            except Exception:
                continue

        # 언어 지정 없이 폴백
        if fetched is None:
            try:
                fetched = api.fetch(video_id)
            except Exception:
                pass

        if not fetched:
            logger.info("No transcript found for video_id=%s", video_id)
            return None, "stt"

        lines = []
        for e in fetched:
            try:
                start = float(e.start) if hasattr(e, 'start') else float(e.get('start', 0))
                text = e.text if hasattr(e, 'text') else e.get('text', '')
            except Exception:
                continue
            if text and str(text).strip():
                lines.append(f"[{start:.1f}s] {str(text).strip()}")

        result = "\n".join(lines)
        return (result or None), "subtitle"

    except Exception as e:
        logger.warning("get_transcript failed for %s: %s", video_id, e)
        return None, "stt"


def get_video_metadata(video_id: str) -> dict:
    """yt-dlp로 영상 메타데이터를 조회한다.

    Returns:
        {
          "title": str | None,
          "duration_sec": int | None,
          "thumbnail_url": str | None,
        }
    """
    if not _VIDEO_ID_RE.match(video_id or ""):
        raise ValueError(f"Invalid video_id: {video_id}")

    url = f"https://www.youtube.com/watch?v={video_id}"

    # 기본 폴백 썸네일 (ytimg)
    fallback_thumb = f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"

    try:
        import yt_dlp  # type: ignore

        with tempfile.TemporaryDirectory(prefix="tennis-ytdlp-meta-") as tmp_dir:
            ydl_opts = build_youtube_ydl_opts({
                "quiet": True,
                "no_warnings": True,
                "skip_download": True,
                "noplaylist": True,
            }, tmp_dir=tmp_dir, logger=logger)
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
    except Exception as e:
        logger.warning("yt-dlp metadata fetch failed for %s: %s", video_id, e)
        return {
            "title": None,
            "duration_sec": None,
            "thumbnail_url": fallback_thumb,
        }

    title = info.get("title") if isinstance(info, dict) else None
    duration = info.get("duration") if isinstance(info, dict) else None
    # yt-dlp는 thumbnails 리스트 또는 단일 thumbnail 키 제공
    thumbnail_url: Optional[str] = None
    if isinstance(info, dict):
        thumbnail_url = info.get("thumbnail")
        if not thumbnail_url and isinstance(info.get("thumbnails"), list) and info["thumbnails"]:
            # 가장 마지막(보통 최고 해상도)에서 url 추출
            last = info["thumbnails"][-1]
            if isinstance(last, dict):
                thumbnail_url = last.get("url")

    # upload_date: YYYYMMDD → YYYY-MM-DD
    upload_date: Optional[str] = None
    raw_date = info.get("upload_date") if isinstance(info, dict) else None
    if isinstance(raw_date, str) and len(raw_date) == 8:
        upload_date = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:]}"

    return {
        "title": title,
        "duration_sec": int(duration) if isinstance(duration, (int, float)) else None,
        "thumbnail_url": thumbnail_url or fallback_thumb,
        "upload_date": upload_date,
    }
