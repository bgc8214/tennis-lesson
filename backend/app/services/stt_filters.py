"""Whisper STT 세그먼트 환청(hallucination) 필터.

Whisper 계열 모델은 무음/공 소리 구간에서 문장을 지어내거나(no_speech),
같은 문장을 무한 반복(compression loop)하는 환청이 잘 알려져 있다.
이 모듈은 전사 결과 세그먼트를 코드 레벨에서 걸러내는 순수 함수들을 제공한다.

임계값 근거 (openai/whisper 기본값 = faster-whisper 커뮤니티 권장값):
  - no_speech_prob  > 0.6  → 무음 구간 창작 의심 (whisper no_speech_threshold=0.6)
  - avg_logprob     < -1.0 → 디코더가 자신 없는 저품질 세그먼트 (logprob_threshold=-1.0)
  - compression_ratio > 2.4 → 반복 루프 환청 (compression_ratio_threshold=2.4)

이 모듈은 외부 의존성이 없어 네트워크/모델 없이 단위 테스트 가능하다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Dict, List, Optional, Tuple

# openai/whisper 기본값이자 faster-whisper 커뮤니티 표준 권장값
NO_SPEECH_PROB_THRESHOLD = 0.6
AVG_LOGPROB_THRESHOLD = -1.0
COMPRESSION_RATIO_THRESHOLD = 2.4
# 연속 세그먼트 반복 판정 유사도 (정규화 후)
DEDUPE_SIMILARITY_THRESHOLD = 0.9


@dataclass
class SttSegment:
    """STT 프로바이더 공통 세그먼트 표현."""

    start: float
    end: float
    text: str
    no_speech_prob: Optional[float] = None
    avg_logprob: Optional[float] = None
    compression_ratio: Optional[float] = None


@dataclass
class FilterStats:
    """필터링 통계 (로그/리포트 메타 기록용)."""

    total: int = 0
    dropped_no_speech: int = 0
    dropped_logprob: int = 0
    dropped_compression: int = 0
    dropped_repeat: int = 0
    dropped_empty: int = 0
    kept: int = 0

    def as_dict(self) -> Dict[str, int]:
        return {
            "total": self.total,
            "kept": self.kept,
            "dropped_no_speech": self.dropped_no_speech,
            "dropped_logprob": self.dropped_logprob,
            "dropped_compression": self.dropped_compression,
            "dropped_repeat": self.dropped_repeat,
            "dropped_empty": self.dropped_empty,
        }


def normalize_text(value: str) -> str:
    """비교용 정규화: 소문자화 + 한글/영숫자 외 문자 제거."""
    return re.sub(r"[^0-9a-z가-힣]+", "", (value or "").lower())


def _similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def filter_hallucinated_segments(
    segments: List[SttSegment],
    *,
    no_speech_threshold: float = NO_SPEECH_PROB_THRESHOLD,
    logprob_threshold: float = AVG_LOGPROB_THRESHOLD,
    compression_ratio_threshold: float = COMPRESSION_RATIO_THRESHOLD,
    dedupe_similarity: float = DEDUPE_SIMILARITY_THRESHOLD,
) -> Tuple[List[SttSegment], FilterStats]:
    """환청 의심 세그먼트를 제거하고 (통과 세그먼트, 통계)를 반환한다.

    제거 규칙 (순서대로 평가):
      1. 빈 텍스트
      2. compression_ratio > threshold  — 반복 루프 환청
      3. avg_logprob < threshold        — 저신뢰 디코딩
      4. no_speech_prob > threshold     — 무음 구간 창작
      5. 직전 통과 세그먼트와 정규화 텍스트가 동일/고유사 — 반복 dedupe

    지표가 None인 경우(프로바이더가 미제공) 해당 규칙은 건너뛴다.
    """
    stats = FilterStats(total=len(segments))
    kept: List[SttSegment] = []
    prev_norm = ""

    for seg in segments:
        norm = normalize_text(seg.text)
        if not norm:
            stats.dropped_empty += 1
            continue

        if (
            seg.compression_ratio is not None
            and seg.compression_ratio > compression_ratio_threshold
        ):
            stats.dropped_compression += 1
            continue

        if seg.avg_logprob is not None and seg.avg_logprob < logprob_threshold:
            stats.dropped_logprob += 1
            continue

        if seg.no_speech_prob is not None and seg.no_speech_prob > no_speech_threshold:
            stats.dropped_no_speech += 1
            continue

        # 연속 동일/유사 텍스트 반복 dedupe (Whisper 루프 환청의 전형적 패턴)
        if prev_norm and (
            norm == prev_norm or _similarity(norm, prev_norm) >= dedupe_similarity
        ):
            stats.dropped_repeat += 1
            continue

        kept.append(seg)
        prev_norm = norm

    stats.kept = len(kept)
    return kept, stats


def segments_to_transcript_text(segments: List[SttSegment]) -> str:
    """세그먼트 목록을 '[시작초~종료초] 텍스트' 라인 포맷으로 직렬화."""
    lines = []
    for seg in segments:
        lines.append(f"[{seg.start:.1f}~{seg.end:.1f}] {seg.text.strip()}")
    return "\n".join(lines)


@dataclass
class TranscriptWindow:
    """Pass A 호출 단위 — 고정 절대시간 구간 + 그 구간에 속한 세그먼트."""

    window_start: float
    window_end: float
    segments: List[SttSegment]


def split_segments_into_windows(
    segments: List[SttSegment], window_sec: float
) -> List[TranscriptWindow]:
    """세그먼트를 영상 재생 시간 기준 고정 절대시간 window_sec 창으로 분할한다.

    09문서 1-5 가설("전사를 작은 창으로 나눠 각각 독립 호출하면 리콜이
    개선된다")은 실측(2026-07-17, Wh2B6VyR_ys 56.9분, 동일 캐시된 STT
    결과에 창 크기만 바꿔 A/B)으로 반증됨:
      10분 창(5개) 검증통과 8개 < 15분(4개) 12개 < 20분(3개) 11개
      < 30분(2개) 15개 < 단일 창(1개, 전체) 13개
    창을 작게 나눌수록 리콜이 오히려 떨어졌다. 현재 gemini_service.py의
    WHISPER_PASS_A_WINDOW_SEC는 항상 단일 창이 되도록 충분히 크게 고정되어
    있고, 이 함수 자체는 향후 다른 실험(예: 겹치는 슬라이딩 윈도우)을 위해
    남겨둔 것이다 — 기본 파이프라인에서는 실질적으로 분할이 일어나지 않는다.

    창 경계는 [0, window_sec), [window_sec, 2*window_sec), ... 처럼 오디오
    시작을 기준으로 고정한다(세그먼트가 나타나는 시각 기준이 아님) — 이렇게
    하지 않고 세그먼트 등장 시각 기준으로 나누면, 발화가 뜸한 구간에서
    "창 길이"가 실제보다 훨씬 짧게 계산되어 개수 가이드(길이 비례)가
    무력화되는 버그가 있었다(2026-07-17 확인 후 수정).
    세그먼트가 하나도 없는 창(완전 무음 구간)은 결과 리스트에서 제외한다.

    빈 세그먼트 리스트나 window_sec<=0이면 전체를 단일 창으로 반환한다.
    """
    if not segments:
        return []
    if window_sec <= 0:
        return [TranscriptWindow(segments[0].start, segments[-1].end, segments)]

    total_end = segments[-1].end
    windows: List[TranscriptWindow] = []
    idx = 0
    n = len(segments)
    window_start = 0.0

    while window_start < total_end:
        window_end = window_start + window_sec
        bucket: List[SttSegment] = []
        while idx < n and segments[idx].start < window_end:
            bucket.append(segments[idx])
            idx += 1
        if bucket:
            windows.append(TranscriptWindow(window_start, window_end, bucket))
        window_start = window_end

    return windows
