"""stt_filters 단위 테스트 — 네트워크/모델 없이 실행 가능."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.stt_filters import (  # noqa: E402
    SttSegment,
    filter_hallucinated_segments,
    normalize_text,
    segments_to_transcript_text,
)


def _seg(start, text, *, ns=0.1, lp=-0.3, cr=1.5, end=None):
    return SttSegment(
        start=start,
        end=end if end is not None else start + 3.0,
        text=text,
        no_speech_prob=ns,
        avg_logprob=lp,
        compression_ratio=cr,
    )


class TestNormalizeText:
    def test_strips_punctuation_and_spaces(self):
        assert normalize_text("팔꿈치를, 더 붙이세요!") == "팔꿈치를더붙이세요"

    def test_lowercases(self):
        assert normalize_text("Split Step") == "splitstep"

    def test_empty(self):
        assert normalize_text("") == ""
        assert normalize_text("...!?") == ""


class TestHallucinationFilters:
    def test_keeps_normal_segments(self):
        segs = [_seg(0, "라켓을 더 일찍 빼세요"), _seg(5, "타점을 앞에서 잡으세요")]
        kept, stats = filter_hallucinated_segments(segs)
        assert len(kept) == 2
        assert stats.kept == 2
        assert stats.total == 2

    def test_drops_high_no_speech_prob(self):
        segs = [_seg(0, "무음 구간에서 지어낸 문장", ns=0.9)]
        kept, stats = filter_hallucinated_segments(segs)
        assert kept == []
        assert stats.dropped_no_speech == 1

    def test_drops_low_avg_logprob(self):
        segs = [_seg(0, "자신 없는 저품질 디코딩", lp=-1.5)]
        kept, stats = filter_hallucinated_segments(segs)
        assert kept == []
        assert stats.dropped_logprob == 1

    def test_drops_high_compression_ratio(self):
        segs = [_seg(0, "발리 발리 발리 발리 발리 발리", cr=3.1)]
        kept, stats = filter_hallucinated_segments(segs)
        assert kept == []
        assert stats.dropped_compression == 1

    def test_drops_empty_text(self):
        segs = [_seg(0, "  ... "), _seg(3, "정상 발화입니다")]
        kept, stats = filter_hallucinated_segments(segs)
        assert len(kept) == 1
        assert stats.dropped_empty == 1

    def test_boundary_values_are_kept(self):
        # 임계값과 정확히 같은 값은 통과 (초과/미만만 제거)
        segs = [_seg(0, "경계값 세그먼트", ns=0.6, lp=-1.0, cr=2.4)]
        kept, _ = filter_hallucinated_segments(segs)
        assert len(kept) == 1

    def test_missing_metrics_skip_rules(self):
        # 프로바이더가 지표를 안 주면 해당 규칙은 건너뛴다
        segs = [SttSegment(start=0, end=3, text="지표 없는 세그먼트")]
        kept, _ = filter_hallucinated_segments(segs)
        assert len(kept) == 1


class TestRepeatDedupe:
    def test_drops_identical_consecutive(self):
        segs = [
            _seg(0, "라켓드롭을 더 깊게"),
            _seg(3, "라켓드롭을 더 깊게"),
            _seg(6, "라켓드롭을 더 깊게"),
            _seg(9, "이제 서브 연습하겠습니다"),
        ]
        kept, stats = filter_hallucinated_segments(segs)
        assert [s.start for s in kept] == [0, 9]
        assert stats.dropped_repeat == 2

    def test_drops_near_identical_consecutive(self):
        segs = [
            _seg(0, "타점을 앞에서 잡으세요"),
            _seg(3, "타점을 앞에서 잡으세요."),  # 문장부호만 다름
        ]
        kept, stats = filter_hallucinated_segments(segs)
        assert len(kept) == 1
        assert stats.dropped_repeat == 1

    def test_keeps_repeat_after_different_segment(self):
        # 연속이 아닌 반복(실제 코칭에서 흔함)은 유지
        segs = [
            _seg(0, "타점을 앞에서"),
            _seg(3, "발리는 짧게 끊어 치세요"),
            _seg(6, "타점을 앞에서"),
        ]
        kept, _ = filter_hallucinated_segments(segs)
        assert len(kept) == 3


class TestTranscriptSerialization:
    def test_format(self):
        segs = [_seg(1.23, "첫 발화", end=4.56), _seg(10.0, "둘째 발화", end=12.5)]
        text = segments_to_transcript_text(segs)
        assert text == "[1.2~4.6] 첫 발화\n[10.0~12.5] 둘째 발화"
