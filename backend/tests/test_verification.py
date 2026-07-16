"""verification(인용 검증기) 단위 테스트 — 네트워크 없이 실행 가능."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.stt_filters import SttSegment  # noqa: E402
from app.services.verification import (  # noqa: E402
    find_quote_match,
    verify_report,
)


def _seg(start, end, text):
    return SttSegment(start=start, end=end, text=text)


TRANSCRIPT = [
    _seg(10.0, 14.0, "팔꿈치를 몸에 더 붙이고 스윙하세요"),
    _seg(30.0, 33.0, "타점이 너무 늦어요"),
    _seg(33.0, 37.0, "공을 앞에서 잡는다는 느낌으로"),
    _seg(60.0, 65.0, "라켓드롭을 깊게 하고 트로피 자세를 유지하세요"),
    _seg(90.0, 94.0, "발리는 짧게 끊어 치세요"),
    _seg(120.0, 124.0, "타점이 너무 늦어요"),  # 동일 발화 반복 (다른 시각)
]


class TestFindQuoteMatch:
    def test_exact_match(self):
        m = find_quote_match("타점이 너무 늦어요", TRANSCRIPT)
        assert m is not None
        assert m.score == 1.0
        assert m.start_sec == 30.0

    def test_match_ignores_punctuation_and_spacing(self):
        m = find_quote_match("팔꿈치를 몸에 더 붙이고, 스윙하세요!", TRANSCRIPT)
        assert m is not None
        assert m.start_sec == 10.0

    def test_partial_quote_matches_containing_segment(self):
        m = find_quote_match("라켓드롭을 깊게", TRANSCRIPT)
        assert m is not None
        assert m.start_sec == 60.0

    def test_quote_spanning_two_segments(self):
        m = find_quote_match(
            "타점이 너무 늦어요 공을 앞에서 잡는다는 느낌으로", TRANSCRIPT
        )
        assert m is not None
        assert m.start_sec == 30.0
        assert m.window_size >= 2

    def test_fabricated_quote_rejected(self):
        m = find_quote_match("서브 토스를 오른쪽 어깨 위로 올리세요", TRANSCRIPT)
        assert m is None

    def test_too_short_quote_rejected(self):
        assert find_quote_match("네", TRANSCRIPT) is None
        assert find_quote_match("", TRANSCRIPT) is None

    def test_hint_sec_picks_nearest_occurrence(self):
        # 같은 발화가 30초/120초에 있을 때 hint에 가까운 쪽 선택
        m = find_quote_match("타점이 너무 늦어요", TRANSCRIPT, hint_sec=118.0)
        assert m is not None
        assert m.start_sec == 120.0

    def test_empty_segments(self):
        assert find_quote_match("타점이 너무 늦어요", []) is None


class TestVerifyReport:
    def _report(self):
        return {
            "card1_problem": "타점이 늦는 것이 고질적인 문제입니다.",
            "card1_evidence": "타점이 너무 늦어요",
            "card2_cueing": "공을 앞에서 잡는 이미지를 가지세요.",
            "card2_evidence": "공을 앞에서 잡는다는 느낌으로",
            "card3_action": "서브 토스 위치를 교정하세요.",
            "card3_evidence": "토스를 어깨 위로 올리세요",  # 전사에 없음 → 폐기 대상
            "timestamps": [
                {"sec": 31, "label": "타점 지적", "quote": "타점이 너무 늦어요"},
                {"sec": 62, "label": "라켓드롭", "quote": "라켓드롭을 깊게 하고 트로피 자세를 유지하세요"},
                {"sec": 200, "label": "지어낸 장면", "quote": "그립을 컨티넨탈로 바꾸세요"},
                {"sec": 95, "label": "quote 없음"},
            ],
        }

    def test_verified_timestamps_kept_and_sec_recomputed(self):
        result, stats = verify_report(self._report(), TRANSCRIPT)
        secs = [ts["sec"] for ts in result["timestamps"]]
        # 31초 주장 → 실제 세그먼트 시작 30초로 보정
        assert 30 in secs
        assert 60 in secs

    def test_fabricated_timestamp_dropped(self):
        result, stats = verify_report(self._report(), TRANSCRIPT)
        labels = [ts["label"] for ts in result["timestamps"]]
        assert "지어낸 장면" not in labels
        assert "quote 없음" not in labels
        assert stats["timestamps_total"] == 4
        assert stats["timestamps_verified"] == 2
        assert stats["timestamps_dropped"] == 2

    def test_card_with_valid_evidence_kept(self):
        result, _ = verify_report(self._report(), TRANSCRIPT)
        assert result["card1_problem"] is not None
        assert result["card2_cueing"] is not None

    def test_card_with_fabricated_evidence_nulled(self):
        result, stats = verify_report(self._report(), TRANSCRIPT)
        assert result["card3_action"] is None
        assert "card3_action" in stats["cards_dropped"]

    def test_card_without_evidence_nulled(self):
        report = self._report()
        del report["card1_evidence"]
        result, stats = verify_report(report, TRANSCRIPT)
        assert result["card1_problem"] is None
        assert "card1_problem" in stats["cards_dropped"]

    def test_match_score_added(self):
        result, _ = verify_report(self._report(), TRANSCRIPT)
        for ts in result["timestamps"]:
            assert 0.0 <= ts["match_score"] <= 1.0

    def test_original_not_mutated(self):
        report = self._report()
        verify_report(report, TRANSCRIPT)
        assert report["card3_action"] is not None
        assert len(report["timestamps"]) == 4

    def test_timestamps_sorted_by_sec(self):
        result, _ = verify_report(self._report(), TRANSCRIPT)
        secs = [ts["sec"] for ts in result["timestamps"]]
        assert secs == sorted(secs)

    def test_empty_report(self):
        result, stats = verify_report({}, TRANSCRIPT)
        assert result["timestamps"] == []
        assert stats["timestamps_total"] == 0
        assert stats["cards_dropped"] == []
