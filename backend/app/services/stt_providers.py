"""STT 프로바이더 추상화 (STT_PROVIDER: local | groq).

  - local: faster-whisper (VAD + 환청 억제 파라미터 적용). 무료지만 CPU에서 느림.
  - groq : Groq 호스티드 whisper-large-v3-turbo ($0.04/오디오시간, 무료 티어 있음).
           Cloud Run처럼 CPU가 약한 환경에서 1시간 영상도 수십 초에 전사.

두 경로 모두 SttSegment 리스트를 반환하고, 공통 환청 필터
(stt_filters.filter_hallucinated_segments)를 통과시킨다.

15문서 2-C(2026-07-19): groq(whisper-large-v3-turbo)를 골든셋 2개 영상으로
실측한 결과 quote precision이 local(medium)보다 낫지 않고 recall은 오히려
악화됨(검증된 코칭 지점 다수에서 세그먼트 자체가 드롭). large-v3 계열
반복 루프 할루시네이션(09문서 1-8)도 turbo에서 재현. STT 모델 교체로
인용 정밀도를 올리는 접근은 여기서 탐색 종료 — 새 실측 근거 없이는
다른 모델을 추가하지 않는다.
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

# 09문서 1-1: whisper initial_prompt로 도메인 용어 인식률을 높인다.
# gemini_service.ALLOWED_LESSON_TYPES 및 청크 프롬프트의 "테니스 용어 참고"
# 목록과 동일 어휘를 재사용.
#
# 실측 결과(aYA3iILW2B0 클립 A/B, 2026-07-17): 용어 사전만으로는 "숏발리"→
# "수비발이" 같은 음향 레벨 오인식이 개선되지 않았다(3가지 프롬프트 조합
# 모두 동일 오인식 재현). 참가자 이름을 단독 주입하면 무음/카운팅 구간에서
# 그 이름을 수십 회 반복하는 할루시네이션이 새로 발생함을 확인 — 다행히
# compression_ratio 후단 필터가 이 반복을 정확히 걸러냈다. 즉 이름 주입은
# 목표한 개선 효과가 확인되지 않았고 부작용 위험만 실증됐으므로, 참가자
# 이름은 기본적으로 주입하지 않는다(호출부 옵션은 남겨두되 명시적 opt-in
# 없이는 사용하지 말 것 — 09문서 1-1 후속 재검토 필요).
TENNIS_TERM_HINT = (
    "타점, 팔로우스루, 내전, 라켓드롭, 토스, 발리, 스플릿스텝, 풋워크, "
    "크로스, 다운더라인, 트로피자세, 하프발리, 슬라이스, 스트로크, "
    "포핸드, 백핸드, 서브, 로브, 드롭샷, 어프로치, 숏발리, 그립"
)

ProgressCallback = Callable[[str], None]


def _build_initial_prompt(participant_names: Optional[List[str]] = None) -> Optional[str]:
    """테니스 용어 사전 + (명시적으로 전달된 경우) 참가자 이름을 whisper
    initial_prompt로 합성한다.

    참가자 이름 주입은 실측 결과 효과 미확인 + 반복 할루시네이션 위험이
    확인된 기능이라(모듈 상단 주석 참고) 호출부가 명시적으로 값을 넘기지
    않는 한 사용되지 않는다.
    """
    settings = get_settings()
    if not settings.STT_TERM_HINT_ENABLED:
        return None
    parts = [TENNIS_TERM_HINT]
    if participant_names:
        parts.append(", ".join(n.strip() for n in participant_names if n.strip()))
    return " ".join(parts) if parts else None


def transcribe_audio(
    audio_path: str,
    on_progress: Optional[ProgressCallback] = None,
    participant_names: Optional[List[str]] = None,
) -> Tuple[List[SttSegment], Dict[str, Any]]:
    """설정된 STT_PROVIDER로 전사 후 환청 필터를 적용해 반환한다.

    Args:
        participant_names: 레슨 참가자 이름. 실측상 오인식 개선 효과가
            확인되지 않고 반복 할루시네이션 위험만 있어(모듈 상단 주석),
            명시적으로 opt-in하지 않는 한 비워둘 것. 현재 호출부는 항상 비움.

    Returns:
        (필터 통과 세그먼트, 통계 dict)
    """
    settings = get_settings()
    provider = (settings.STT_PROVIDER or "local").strip().lower()
    initial_prompt = _build_initial_prompt(participant_names)

    if provider == "groq":
        raw_segments = _transcribe_groq(audio_path, on_progress, initial_prompt)
    else:
        provider = "local"
        raw_segments = _transcribe_local(audio_path, on_progress, initial_prompt)

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
    initial_prompt: Optional[str] = None,
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
    - initial_prompt: 09문서 1-1. 테니스 용어(+참가자 이름)를 whisper 인코더에
      선힌트로 제공해 도메인 어휘 인식률을 높인다.
    """
    from faster_whisper import WhisperModel

    settings = get_settings()
    audio_input = audio_path
    tmp_dir_holder = None
    if settings.AUDIO_PREPROCESS_ENABLED:
        tmp_dir_holder = tempfile.TemporaryDirectory(prefix="tennis-stt-pre-")
        audio_input = _preprocess_audio(audio_path, tmp_dir_holder.name)

    try:
        logger.info("[stt:local] faster-whisper %s 로드", settings.WHISPER_MODEL_SIZE)
        model = WhisperModel(
            settings.WHISPER_MODEL_SIZE or "base",
            device=settings.WHISPER_DEVICE or "cpu",
            compute_type="int8",
        )

        segments_iter, info = model.transcribe(
            audio_input,
            language=settings.WHISPER_LANGUAGE or "ko",
            beam_size=5,
            temperature=0.0,
            condition_on_previous_text=False,
            vad_filter=False,
            initial_prompt=initial_prompt,
            # whisper 기본 임계값 — 세그먼트 지표는 어차피 후단 필터에서 재검사한다.
            no_speech_threshold=0.6,
            log_prob_threshold=-1.0,
            compression_ratio_threshold=2.4,
        )
        return _collect_local_segments(segments_iter, info, on_progress)
    finally:
        if tmp_dir_holder is not None:
            tmp_dir_holder.cleanup()


def _collect_local_segments(
    segments_iter: Any,
    info: Any,
    on_progress: Optional[ProgressCallback],
) -> List[SttSegment]:
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


# ─── 공통: 오디오 전처리 (09문서 1-2) ─────────────────────────────────


def _preprocess_audio(audio_path: str, tmp_dir: str) -> str:
    """저볼륨 코트 오디오 보정: highpass(저주파 노이즈 제거) + loudnorm(EBU R128).

    가설(09문서 1-2): mean_volume -27~-40dB — 표준 발화(-20dB 안팎) 대비 낮아
    no_speech_prob가 과대 산출될 가능성 → -16 LUFS 정규화로 개선.

    실측 결과(5PUGx-OYI5s 60초 클립 A/B, 2026-07-17): 가설이 반증됨.
    - kept 세그먼트 수가 오히려 줄었다(원본 12개 → 전처리 9개, no_speech
      탈락은 양쪽 동일 12개로 무음 판별 개선 없음).
    - 골든셋(tests/golden/5pugx_oyi5s.json)에서 이미 의심 표시했던 정확히
      같은 위치(27초 근방)에 새로운 할루시네이션이 발생함: 원본 "이 애를
      잘 이렇게 펴서" → 전처리 후 "이 앨범을 잘하고 이렇게 펴서". 노이즈
      증폭이 whisper의 그럴듯한 오인식을 유발하는 것으로 보인다.
    결론: 이 필터 체인은 기본으로 켜지 않는다(AUDIO_PREPROCESS_ENABLED 기본
    False 유지). 다른 필터 파라미터로 재검증 전까지 실사용 비권장.
    """
    out_path = os.path.join(tmp_dir, "preprocessed.wav")
    subprocess.run(
        [
            "ffmpeg", "-y", "-i", audio_path,
            "-af", "highpass=f=100,loudnorm=I=-16:TP=-1.5:LRA=11",
            out_path,
        ],
        capture_output=True,
        check=True,
    )
    return out_path


# ─── groq: hosted whisper-large-v3-turbo ─────────────────────────────


def _reencode_for_upload(audio_path: str, tmp_dir: str) -> str:
    """업로드 크기 최소화: 16kHz mono 32kbps mp3 재인코딩 (Groq 권장 전처리)."""
    settings = get_settings()
    source = audio_path
    pre_tmp_dir = None
    if settings.AUDIO_PREPROCESS_ENABLED:
        pre_tmp_dir = tempfile.TemporaryDirectory(prefix="tennis-groq-pre-")
        source = _preprocess_audio(audio_path, pre_tmp_dir.name)

    try:
        out_path = os.path.join(tmp_dir, "stt_upload.mp3")
        subprocess.run(
            [
                "ffmpeg", "-y", "-i", source,
                "-ar", "16000", "-ac", "1", "-b:a", "32k",
                out_path,
            ],
            capture_output=True,
            check=True,
        )
        return out_path
    finally:
        if pre_tmp_dir is not None:
            pre_tmp_dir.cleanup()


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
    initial_prompt: Optional[str] = None,
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
        if initial_prompt:
            data["prompt"] = initial_prompt
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
    initial_prompt: Optional[str] = None,
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
                chunk["path"], api_key, model, language, initial_prompt
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
