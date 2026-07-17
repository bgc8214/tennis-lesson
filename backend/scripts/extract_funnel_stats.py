"""whisper 파이프라인 로그에서 4단계 퍼널 숫자를 추출한다.

단계: STT 세그먼트(total) → 환청 필터 통과(kept) → Gemini 추출(timestamps_total)
      → 검증 통과(timestamps_verified)

사용법:
    python scripts/extract_funnel_stats.py /tmp/tennis-backend.log
    python scripts/extract_funnel_stats.py /tmp/tennis-backend.log --video-id 4mr0tVIu9sw
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional

_LESSON_CREATED_RE = re.compile(
    r"youtube_video_id=eq\.([A-Za-z0-9_-]{11}).*?\n.*?rest/v1/lessons \"HTTP/2 201 Created\""
)
_ANALYZE_ACCEPTED_RE = re.compile(r'"POST /api/v1/lessons/analyze HTTP/1\.1" 202 Accepted')
_LESSON_ID_PATCH_RE = re.compile(r"rest/v1/lessons\?id=eq\.([0-9a-f-]{36}) \"HTTP/2 200 OK\"")
_TRANSCRIBE_RE = re.compile(
    r"전사 (\d+) 세그먼트 → 필터 통과 (\d+) \(환청 의심 제거: (\{.*?\})\)"
)
_VERIFY_RE = re.compile(
    r"검증 완료: timestamps (\d+)/(\d+) 통과, 카드 폐기 (.+)"
)
_LESSON_REPORT_PATCH_RE = re.compile(r"lesson_reports\?lesson_id=eq\.([0-9a-f-]{36})")


@dataclass
class FunnelRun:
    """단일 analyze 실행의 퍼널 통계."""

    lesson_id: Optional[str] = None
    stt_total: Optional[int] = None
    stt_kept: Optional[int] = None
    drop_breakdown: Optional[dict] = None
    ts_verified: Optional[int] = None
    ts_total: Optional[int] = None
    cards_dropped: Optional[str] = None
    line_no: int = 0

    def recall_stt(self) -> Optional[float]:
        if not self.stt_total:
            return None
        return round((self.stt_kept or 0) / self.stt_total, 3)

    def recall_verify(self) -> Optional[float]:
        if not self.ts_total:
            return None
        return round((self.ts_verified or 0) / self.ts_total, 3)


def parse_log(path: str) -> List[FunnelRun]:
    """로그를 순서대로 훑어 lesson_id별로 최신 lesson_reports PATCH를 힌트로
    삼아 STT/검증 라인을 그룹화한다.

    로그에 lesson_id가 STT/검증 라인 자체에는 없으므로, 직전에 등장한
    lesson_reports PATCH의 lesson_id를 현재 컨텍스트로 취급하는 근사 매칭을
    사용한다. 여러 레슨이 인터리빙되면 오차가 생길 수 있음 — 정확한 매칭이
    필요하면 lesson_id별로 로그를 미리 grep해서 이 스크립트를 재실행할 것.
    """
    runs: List[FunnelRun] = []
    current_lesson_id: Optional[str] = None
    pending = FunnelRun()

    with open(path, "r", errors="ignore") as f:
        for line_no, line in enumerate(f, start=1):
            m = _LESSON_REPORT_PATCH_RE.search(line)
            if m:
                current_lesson_id = m.group(1)

            m = _TRANSCRIBE_RE.search(line)
            if m:
                pending = FunnelRun(lesson_id=current_lesson_id, line_no=line_no)
                pending.stt_total = int(m.group(1))
                pending.stt_kept = int(m.group(2))
                try:
                    pending.drop_breakdown = ast.literal_eval(m.group(3))
                except (ValueError, SyntaxError):
                    pending.drop_breakdown = None
                continue

            m = _VERIFY_RE.search(line)
            if m and pending.stt_total is not None:
                pending.ts_verified = int(m.group(1))
                pending.ts_total = int(m.group(2))
                pending.cards_dropped = m.group(3).strip()
                pending.lesson_id = pending.lesson_id or current_lesson_id
                runs.append(pending)
                pending = FunnelRun()

    return runs


def print_table(runs: List[FunnelRun]) -> None:
    header = f"{'lesson_id':38} {'line':>6} {'STT total':>10} {'kept':>6} {'recall%':>8} {'ts_total':>9} {'ts_ok':>6} {'verify%':>8} {'cards_dropped'}"
    print(header)
    print("-" * len(header))
    for r in runs:
        stt_recall = r.recall_stt()
        verify_recall = r.recall_verify()
        print(
            f"{(r.lesson_id or '?'):38} {r.line_no:>6} {r.stt_total or 0:>10} "
            f"{r.stt_kept or 0:>6} {f'{stt_recall*100:.1f}' if stt_recall is not None else '-':>8} "
            f"{r.ts_total or 0:>9} {r.ts_verified or 0:>6} "
            f"{f'{verify_recall*100:.1f}' if verify_recall is not None else '-':>8} "
            f"{r.cards_dropped or ''}"
        )
        if r.drop_breakdown:
            b = r.drop_breakdown
            print(
                f"   ↳ 무음={b.get('dropped_no_speech',0)} "
                f"저신뢰={b.get('dropped_logprob',0)} "
                f"반복압축={b.get('dropped_compression',0)} "
                f"반복문장={b.get('dropped_repeat',0)} "
                f"빈문자열={b.get('dropped_empty',0)}"
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log_path", help="백엔드 로그 파일 경로")
    parser.add_argument(
        "--video-id", help="특정 lesson_id만 필터링 (알고 있다면 grep 후 재실행 권장)"
    )
    args = parser.parse_args()

    runs = parse_log(args.log_path)
    if not runs:
        print("퍼널 로그를 찾지 못했습니다 (whisper 경로 실행 기록이 없거나 로그 포맷이 다름).")
        sys.exit(1)

    print_table(runs)
    print(f"\n총 {len(runs)}개 실행 발견.")


if __name__ == "__main__":
    main()
