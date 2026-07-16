"""리포트 인용(quote) 검증기 — 코드 레벨 할루시네이션 게이트.

Gemini가 생성한 리포트의 모든 인용(timestamps[].quote, cardN_evidence)을
전사 원문과 fuzzy match로 대조한다.

  - 매칭 실패한 timestamp  → 폐기
  - 매칭 실패한 card 근거   → 해당 카드 내용 폐기(None)
  - 매칭 성공한 timestamp  → sec를 매칭된 전사 세그먼트의 실제 시작초로 재계산

LLM이 "transcript에 없는 내용 금지"라는 프롬프트를 어기고 지어낸 내용은
이 게이트에서 전부 걸러진다. 외부 의존성이 없어 네트워크 없이 테스트 가능.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Tuple

from app.services.stt_filters import SttSegment, normalize_text

logger = logging.getLogger(__name__)

# 보수적 기본 임계값: 인용이 전사 원문 그대로라면(정규화 후) 1.0에 가깝고,
# STT 표기 차이(띄어쓰기·문장부호)는 normalize가 흡수하므로 0.75면 충분히 엄격하다.
DEFAULT_MATCH_THRESHOLD = 0.75
# 인용이 여러 세그먼트에 걸칠 수 있으므로 연속 세그먼트를 합쳐 비교하는 최대 창 크기
MAX_WINDOW = 3
# 지나치게 짧은 인용(정규화 후 4자 미만)은 아무 데나 매칭되므로 검증 불가로 폐기
MIN_QUOTE_CHARS = 4


@dataclass
class QuoteMatch:
    """전사 원문 매칭 결과."""

    start_sec: float
    end_sec: float
    score: float
    segment_index: int
    window_size: int


def _ratio(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    m = SequenceMatcher(None, a, b)
    # quick_ratio 프리필터로 대량 비교 비용 절감
    if m.quick_ratio() < 0.5:
        return 0.0
    return m.ratio()


def _window_score(norm_quote: str, norm_window: str) -> float:
    """인용 vs 세그먼트 창 유사도. 부분 문자열 포함이면 1.0."""
    if not norm_quote or not norm_window:
        return 0.0
    if norm_quote in norm_window:
        return 1.0
    # 창이 인용보다 훨씬 길면 ratio가 부당하게 낮아지므로,
    # 인용 길이에 맞춘 슬라이딩 부분 문자열과도 비교한다.
    if len(norm_window) > len(norm_quote):
        best = _ratio(norm_quote, norm_window)
        qlen = len(norm_quote)
        step = max(1, qlen // 4)
        for i in range(0, len(norm_window) - qlen + 1, step):
            best = max(best, _ratio(norm_quote, norm_window[i : i + qlen]))
            if best >= 0.999:
                break
        return best
    return _ratio(norm_quote, norm_window)


def find_quote_match(
    quote: str,
    segments: List[SttSegment],
    *,
    threshold: float = DEFAULT_MATCH_THRESHOLD,
    hint_sec: Optional[float] = None,
    max_window: int = MAX_WINDOW,
) -> Optional[QuoteMatch]:
    """인용문을 전사 세그먼트(연속 창 포함)와 대조해 최적 매칭을 찾는다.

    Args:
        quote: 검증할 인용문.
        segments: 전사 세그먼트 (시간 오름차순).
        threshold: 통과 최소 유사도 (정규화 텍스트 기준).
        hint_sec: LLM이 주장한 시각. 동점 후보 중 이 값에 가장 가까운 것을 선택.
        max_window: 연속 세그먼트 병합 최대 개수.

    Returns:
        threshold 이상 매칭이 없으면 None.
    """
    norm_quote = normalize_text(quote or "")
    if len(norm_quote) < MIN_QUOTE_CHARS or not segments:
        return None

    norms = [normalize_text(s.text) for s in segments]
    candidates: List[QuoteMatch] = []

    for i in range(len(segments)):
        window_text = ""
        for w in range(max_window):
            j = i + w
            if j >= len(segments):
                break
            window_text += norms[j]
            # 창이 인용의 3배를 넘으면 더 늘려도 의미 없음
            if w > 0 and len(window_text) > len(norm_quote) * 3:
                break
            score = _window_score(norm_quote, window_text)
            if score >= threshold:
                # 첫 세그먼트가 매칭에 실제로 기여하는지 검사 —
                # 기여하지 않으면 i+1에서 시작하는 더 정확한 후보가 존재하므로
                # 이 시작점은 버린다 (시작초가 과도하게 앞당겨지는 것 방지).
                if w > 0:
                    tail_text = window_text[len(norms[i]):]
                    if _window_score(norm_quote, tail_text) >= score:
                        break
                candidates.append(
                    QuoteMatch(
                        start_sec=segments[i].start,
                        end_sec=segments[j].end,
                        score=score,
                        segment_index=i,
                        window_size=w + 1,
                    )
                )
                break  # 이 시작점에서는 최소 창으로 충분

    if not candidates:
        return None

    if hint_sec is not None:
        # 점수 우선, 근접 후보(점수 차 0.05 이내)끼리는 hint_sec에 가까운 쪽 선택
        best_score = max(c.score for c in candidates)
        near_best = [c for c in candidates if c.score >= best_score - 0.05]
        return min(near_best, key=lambda c: abs(c.start_sec - float(hint_sec)))

    return max(candidates, key=lambda c: c.score)


def verify_report(
    parsed: Dict[str, Any],
    segments: List[SttSegment],
    *,
    threshold: float = DEFAULT_MATCH_THRESHOLD,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """LLM 리포트를 전사 원문과 대조해 검증된 사본과 통계를 반환한다.

    - timestamps: quote가 전사와 매칭되면 sec를 매칭 세그먼트 시작초로 재계산,
      매칭 실패(또는 quote 없음)면 항목 폐기.
    - cards: cardN_evidence가 매칭 실패하면 cardN 내용을 None으로 폐기.

    원본 parsed는 수정하지 않는다.
    """
    result = dict(parsed)
    stats: Dict[str, Any] = {
        "match_threshold": threshold,
        "timestamps_total": 0,
        "timestamps_verified": 0,
        "timestamps_dropped": 0,
        "cards_dropped": [],
    }

    # 1) timestamps 검증
    verified_ts: List[Dict[str, Any]] = []
    raw_ts = parsed.get("timestamps") or []
    if isinstance(raw_ts, list):
        for item in raw_ts:
            if not isinstance(item, dict):
                continue
            stats["timestamps_total"] += 1
            quote = str(item.get("quote") or "").strip()
            hint_sec: Optional[float]
            try:
                hint_sec = float(item.get("sec"))
            except (TypeError, ValueError):
                hint_sec = None

            match = find_quote_match(
                quote, segments, threshold=threshold, hint_sec=hint_sec
            )
            if match is None:
                stats["timestamps_dropped"] += 1
                logger.info(
                    "[verify] timestamp 폐기 (sec=%s): 전사 미매칭 quote=%r",
                    item.get("sec"), quote[:60],
                )
                continue

            verified = dict(item)
            verified["sec"] = int(match.start_sec)  # 전사 세그먼트 실제 시작초로 보정
            verified["match_score"] = round(match.score, 3)
            verified_ts.append(verified)
            stats["timestamps_verified"] += 1

    verified_ts.sort(key=lambda x: x.get("sec", 0))
    result["timestamps"] = verified_ts

    # 2) 카드 근거 검증 — 근거 인용이 전사에 없으면 카드 내용 폐기
    for key in ("card1_problem", "card2_cueing", "card3_action"):
        evidence_key = key.split("_")[0] + "_evidence"  # card1_evidence ...
        card_value = parsed.get(key)
        if not str(card_value or "").strip():
            continue
        evidence = str(parsed.get(evidence_key) or "").strip()
        match = find_quote_match(evidence, segments, threshold=threshold)
        if match is None:
            result[key] = None
            stats["cards_dropped"].append(key)
            logger.info(
                "[verify] %s 폐기: 근거 인용 전사 미매칭 evidence=%r",
                key, evidence[:60],
            )

    logger.info(
        "[verify] 검증 완료: timestamps %d/%d 통과, 카드 폐기 %s",
        stats["timestamps_verified"],
        stats["timestamps_total"],
        stats["cards_dropped"] or "없음",
    )
    return result, stats
