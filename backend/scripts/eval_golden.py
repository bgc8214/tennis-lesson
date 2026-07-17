"""골든셋(tests/golden/*.json) 기준 파이프라인 회귀 채점.

각 골든셋 파일의 verified_feedbacks[].status가 사람 검토를 거쳐
confirmed/hallucination/ambiguous로 채워진 뒤에만 정확한 점수를 낸다.
unreviewed 항목만 있는 파일은 "검토 대기" 경고로 표시하고 채점에서 제외한다.

이 스크립트는 실시간으로 파이프라인을 재실행하지 않는다 — 골든셋 JSON에
이미 기록된 결과를 사람이 검토한 라벨과 대조해 정밀도(precision)를 계산할
뿐이다. 재현율(recall) 측정에는 missed_feedbacks[] 항목 수가 쓰인다.

사용법:
    python scripts/eval_golden.py
    python scripts/eval_golden.py --golden-dir tests/golden
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

VALID_STATUSES = {"unreviewed", "confirmed", "hallucination", "ambiguous"}


def load_golden_files(golden_dir: Path) -> List[Dict[str, Any]]:
    files = sorted(golden_dir.glob("*.json"))
    out = []
    for f in files:
        with open(f, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        data["_file"] = f.name
        out.append(data)
    return out


def score_one(data: Dict[str, Any]) -> Dict[str, Any]:
    feedbacks = data.get("verified_feedbacks", [])
    statuses = [fb.get("status", "unreviewed") for fb in feedbacks]

    unreviewed = statuses.count("unreviewed")
    confirmed = statuses.count("confirmed")
    hallucination = statuses.count("hallucination")
    ambiguous = statuses.count("ambiguous")
    reviewed = confirmed + hallucination + ambiguous

    precision = None
    if reviewed > 0:
        # ambiguous는 분모에는 포함하되 분자(정답)에는 안 넣는 보수적 채점
        precision = round(confirmed / reviewed, 3)

    missed = len(data.get("missed_feedbacks", []))
    recall = None
    if reviewed > 0 or missed > 0:
        total_real = confirmed + missed
        if total_real > 0:
            recall = round(confirmed / total_real, 3)

    return {
        "file": data.get("_file"),
        "video_id": data.get("video_id"),
        "total": len(feedbacks),
        "unreviewed": unreviewed,
        "confirmed": confirmed,
        "hallucination": hallucination,
        "ambiguous": ambiguous,
        "missed": missed,
        "precision": precision,
        "recall": recall,
        "fully_reviewed": unreviewed == 0,
    }


def print_report(scores: List[Dict[str, Any]]) -> None:
    header = f"{'file':24} {'video_id':14} {'total':>5} {'검토대기':>8} {'confirmed':>9} {'환청':>5} {'놓침':>5} {'precision':>9} {'recall':>7}"
    print(header)
    print("-" * len(header))
    for s in scores:
        precision_str = f"{s['precision']:.3f}" if s["precision"] is not None else "-"
        recall_str = f"{s['recall']:.3f}" if s["recall"] is not None else "-"
        flag = "" if s["fully_reviewed"] else "  ⚠ 검토 미완료"
        print(
            f"{s['file']:24} {s['video_id'] or '?':14} {s['total']:>5} "
            f"{s['unreviewed']:>8} {s['confirmed']:>9} {s['hallucination']:>5} "
            f"{s['missed']:>5} {precision_str:>9} {recall_str:>7}{flag}"
        )

    reviewed_scores = [s for s in scores if s["fully_reviewed"] and s["total"] > 0]
    if not reviewed_scores:
        print(
            "\n⚠ 검토 완료된 골든셋이 없습니다. "
            "tests/golden/README.md의 절차대로 verified_feedbacks[].status를 채운 뒤 재실행하세요."
        )
        return

    all_confirmed = sum(s["confirmed"] for s in reviewed_scores)
    all_reviewed = sum(s["confirmed"] + s["hallucination"] + s["ambiguous"] for s in reviewed_scores)
    overall_precision = round(all_confirmed / all_reviewed, 3) if all_reviewed else None
    print(f"\n전체 정밀도(검토 완료 파일 기준): {overall_precision}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--golden-dir",
        default=str(Path(__file__).resolve().parent.parent / "tests" / "golden"),
        help="골든셋 JSON이 있는 디렉터리",
    )
    args = parser.parse_args()

    golden_dir = Path(args.golden_dir)
    if not golden_dir.exists():
        print(f"골든셋 디렉터리를 찾을 수 없습니다: {golden_dir}", file=sys.stderr)
        sys.exit(1)

    data_files = load_golden_files(golden_dir)
    if not data_files:
        print(f"골든셋 JSON이 없습니다: {golden_dir}", file=sys.stderr)
        sys.exit(1)

    scores = [score_one(d) for d in data_files]
    print_report(scores)


if __name__ == "__main__":
    main()
