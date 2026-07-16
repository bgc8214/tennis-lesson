"""STT 프로바이더 추상화 (STT_PROVIDER: local | groq).

  - local: faster-whisper (VAD + 환청 억제 파라미터 적용). 무료지만 CPU에서 느림.
  - groq : Groq 호스티드 whisper-large-v3-turbo ($0.04/오디오시간, 무료 티어 있음).
           Cloud Run처럼 CPU가 약한 환경에서 1시간 영상도 수십 초에 전사.

두 경로 모두 SttSegment 리스트를 반환하고, 공통 환청 필터
(stt_filters.filter_hallucinated_segments)를 통과시킨다.
"""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from typing import Any, Callable, Dict, List, Optional, Tuple

from app.config import get_settings
from app.services.stt_filters import (
    FilterStats,
    SttSegment,
    filter_hallucinated_segments,
)

logger = logging.getLogger(__name__)

GROQ_TRANSCRIPTION_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
# Groq 파일 업로드 한도: free tier 25MB / dev tier 100MB.
# 16kHz mono 32kbps mp3로 재인코딩하면 1시간 ≈ 14.4MB지만,
# 안전하게 청크 분할 기준(초)을 두고 넘으면 ffmpeg로 분할 업로드한다.
GROQ_CHUNK_SECONDS = 1800  # 30분 청크 ≈ 7.2MB (32kbps 기준)

ProgressCallback = Callable[[str], None]


def transcribe_audio(
    audio_path: str,
    on_progress: Optional[ProgressCallback] = None,
) -> Tuple[List[SttSegment], Dict[str, Any]]:
    """설정된 STT_PROVIDER로 전사 후 환청 필터를 적용해 반환한다.

    Returns:
        (필터 통과 세그먼트, 통계 dict)
    """
    settings = get_settings()
    provider = (settings.STT_PROVIDER or "local").strip().lower()

    if provider == "groq":
        raw_segments = _transcribe_groq(audio_path, on_progress)
    else:
        provider = "local"
        raw_segments = _transcribe_local(audio_path, on_progress)

    kept, filter_stats = filter_hallucinated_segments(raw_segments)
    logger.info(
        "[stt:%s] 전사 %d 세그먼트 → 필터 통과 %d (환청 의심 제거: %s)",
        provider,
        filter_stats.total,
        filter_stats.kept,
        filter_stats.as_dict(),
    )

    stats: Dict[str, Any] = {"provider": provider, **filter_stats.as_dict()}
    return kept, stats


# ─── local: faster-whisper ────────────────────────────────────────────


def _transcribe_local(
    audio_path: str,
    on_progress: Optional[ProgressCallback] = None,
) -> List[SttSegment]:
    """faster-whisper 로컬 전사 (환청 억제 파라미터 적용).

    - vad_filter=False: Silero VAD가 코트 실촬영 오디오(원거리 마이크로 녹음된
      코치 음성)에서 speech 확률을 0.03~0.29 수준으로만 내는 사고가 반복
      확인됨 — threshold를 0.05까지 낮춰도 26분 영상에서 26분 39초가
      무음으로 오판되어 전사 자체가 통째로 비는 결과가 나왔다. ASR 인코더
      자체는 이 신호에서 실제 코칭 대화를 정확히 인식하므로, 무음 판별은
      VAD 대신 후단 필터(no_speech_prob/logprob/compression_ratio/반복감지)에
      전적으로 맡긴다.
    - condition_on_previous_text=False: 이전 환청이 다음 창으로 전파되는 것 차단
    - temperature=0.0: 샘플링 창작 차단
    """
    from faster_whisper import WhisperModel

    settings = get_settings()
    logger.info("[stt:local] faster-whisper %s 로드", settings.WHISPER_MODEL_SIZE)
    model = WhisperModel(
        settings.WHISPER_MODEL_SIZE or "base",
        device=settings.WHISPER_DEVICE or "cpu",
        compute_type="int8",
    )

    segments_iter, info = model.transcribe(
        audio_path,
        language=settings.WHISPER_LANGUAGE or "ko",
        beam_size=5,
        temperature=0.0,
        condition_on_previous_text=False,
        vad_filter=False,
        # whisper 기본 임계값 — 세그먼트 지표는 어차피 후단 필터에서 재검사한다.
        no_speech_threshold=0.6,
        log_prob_threshold=-1.0,
        compression_ratio_threshold=2.4,
    )

    total = getattr(info, "duration", 0.0) or 0.0
    out: List[SttSegment] = []
    for seg in segments_iter:
        out.append(
            SttSegment(
                start=float(seg.start),
                end=float(seg.end),
                text=(seg.text or "").strip(),
                no_speech_prob=getattr(seg, "no_speech_prob", None),
                avg_logprob=getattr(seg, "avg_logprob", None),
                compression_ratio=getattr(seg, "compression_ratio", None),
            )
        )
        if on_progress and total > 0 and len(out) % 50 == 0:
            pct = min(99, int(float(seg.end) / total * 100))
            on_progress(f"음성 인식 중... {pct}%")

    return out


# ─── groq: hosted whisper-large-v3-turbo ─────────────────────────────


def _reencode_for_upload(audio_path: str, tmp_dir: str) -> str:
    """업로드 크기 최소화: 16kHz mono 32kbps mp3 재인코딩 (Groq 권장 전처리)."""
    out_path = os.path.join(tmp_dir, "stt_upload.mp3")
    subprocess.run(
        [
            "ffmpeg", "-y", "-i", audio_path,
            "-ar", "16000", "-ac", "1", "-b:a", "32k",
            out_path,
        ],
        capture_output=True,
        check=True,
    )
    return out_path


def _audio_duration(audio_path: str) -> float:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", audio_path,
        ],
        capture_output=True,
        text=True,
    )
    try:
        return float(result.stdout.strip())
    except (TypeError, ValueError):
        return 0.0


def _split_for_upload(audio_path: str, tmp_dir: str, chunk_sec: int) -> List[Dict[str, Any]]:
    """청크 분할. [{path, offset_sec}] 반환 (한도 이하면 단일 항목)."""
    duration = _audio_duration(audio_path)
    if duration <= chunk_sec:
        return [{"path": audio_path, "offset_sec": 0.0}]

    chunks: List[Dict[str, Any]] = []
    offset = 0.0
    idx = 0
    while offset < duration:
        chunk_path = os.path.join(tmp_dir, f"stt_chunk_{idx:03d}.mp3")
        subprocess.run(
            [
                "ffmpeg", "-y", "-i", audio_path,
                "-ss", str(offset), "-t", str(chunk_sec),
                "-c", "copy",
                chunk_path,
            ],
            capture_output=True,
        )
        if os.path.exists(chunk_path) and os.path.getsize(chunk_path) > 1024:
            chunks.append({"path": chunk_path, "offset_sec": offset})
        offset += chunk_sec
        idx += 1
    return chunks or [{"path": audio_path, "offset_sec": 0.0}]


def _groq_transcribe_file(
    file_path: str,
    api_key: str,
    model: str,
    language: str,
) -> List[Dict[str, Any]]:
    """단일 파일을 Groq transcription API(verbose_json)로 전사."""
    import httpx

    with open(file_path, "rb") as f:
        files = {"file": (os.path.basename(file_path), f, "audio/mpeg")}
        data = {
            "model": model,
            "language": language,
            "response_format": "verbose_json",
            "temperature": "0",
        }
        resp = httpx.post(
            GROQ_TRANSCRIPTION_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            files=files,
            data=data,
            timeout=httpx.Timeout(300.0, connect=30.0),
        )
    resp.raise_for_status()
    payload = resp.json()
    segments = payload.get("segments") or []
    return segments if isinstance(segments, list) else []


def _transcribe_groq(
    audio_path: str,
    on_progress: Optional[ProgressCallback] = None,
) -> List[SttSegment]:
    """Groq 호스티드 Whisper 전사. 업로드 한도 초과 시 분할 후 오프셋 보정."""
    settings = get_settings()
    api_key = settings.GROQ_API_KEY
    if not api_key:
        raise RuntimeError("STT_PROVIDER=groq 이지만 GROQ_API_KEY가 설정되지 않았습니다")

    model = settings.GROQ_STT_MODEL or "whisper-large-v3-turbo"
    language = settings.WHISPER_LANGUAGE or "ko"

    out: List[SttSegment] = []
    with tempfile.TemporaryDirectory(prefix="tennis-groq-stt-") as tmp_dir:
        upload_path = _reencode_for_upload(audio_path, tmp_dir)
        chunks = _split_for_upload(upload_path, tmp_dir, GROQ_CHUNK_SECONDS)
        logger.info("[stt:groq] 업로드 청크 수: %d (model=%s)", len(chunks), model)

        for idx, chunk in enumerate(chunks, start=1):
            if on_progress:
                on_progress(f"음성 인식 중... ({idx}/{len(chunks)})")
            offset = float(chunk["offset_sec"])
            raw_segments = _groq_transcribe_file(
                chunk["path"], api_key, model, language
            )
            for seg in raw_segments:
                if not isinstance(seg, dict):
                    continue
                try:
                    start = float(seg.get("start", 0.0)) + offset
                    end = float(seg.get("end", start)) + offset
                except (TypeError, ValueError):
                    continue
                out.append(
                    SttSegment(
                        start=start,
                        end=end,
                        text=str(seg.get("text") or "").strip(),
                        no_speech_prob=_maybe_float(seg.get("no_speech_prob")),
                        avg_logprob=_maybe_float(seg.get("avg_logprob")),
                        compression_ratio=_maybe_float(seg.get("compression_ratio")),
                    )
                )

    out.sort(key=lambda s: s.start)
    return out


def _maybe_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
