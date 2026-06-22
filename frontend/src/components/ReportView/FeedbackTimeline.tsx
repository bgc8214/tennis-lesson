"use client";

import { useMemo } from "react";
import type { CourtTactic, LessonTimestamp } from "@/types/lesson";

/* -------------------------------------------------------------------------- */
/* Types                                                                       */
/* -------------------------------------------------------------------------- */

export interface FeedbackItem {
  sec: number;
  category: string | null;
  position?: string | null;
  tactic?: string | null;
  label: string;
  quote?: string | null;
  fix?: string | null;
  source: "court" | "timestamp";
}

interface FeedbackTimelineProps {
  timestamps: LessonTimestamp[];
  courtTactics: CourtTactic[] | null | undefined;
  onSeek: (sec: number) => void;
  onSelectIndex: (index: number) => void;
  activeIndex: number | null;
}

/* -------------------------------------------------------------------------- */
/* Position label mapping                                                      */
/* -------------------------------------------------------------------------- */

const POSITION_LABELS: Record<string, string> = {
  net_left: "네트 좌측",
  net_center: "네트 중앙",
  net_right: "네트 우측",
  service_line_left: "서비스라인 좌측",
  service_line_center: "서비스라인 중앙",
  service_line_right: "서비스라인 우측",
  baseline_left: "베이스라인 좌측",
  baseline_center: "베이스라인 중앙",
  baseline_right: "베이스라인 우측",
  unknown: "",
};

export function getPositionLabel(position: string | null | undefined): string {
  if (!position) return "";
  return POSITION_LABELS[position] ?? position;
}

/* -------------------------------------------------------------------------- */
/* Utilities                                                                   */
/* -------------------------------------------------------------------------- */

function formatTime(sec: number): string {
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

function getCategoryBadgeClass(category: string | null | undefined): string {
  if (!category) return "bg-gray-100 text-gray-700";
  const lower = category.toLowerCase();
  if (lower.includes("포핸드")) return "bg-red-100 text-red-700";
  if (lower.includes("백핸드")) return "bg-blue-100 text-blue-700";
  if (lower.includes("발리")) return "bg-green-100 text-green-700";
  if (lower.includes("서브")) return "bg-purple-100 text-purple-700";
  if (lower.includes("풋워크") || lower.includes("스텝"))
    return "bg-orange-100 text-orange-700";
  return "bg-gray-100 text-gray-700";
}

/* -------------------------------------------------------------------------- */
/* Merge logic                                                                 */
/* -------------------------------------------------------------------------- */

export function mergeFeedbackItems(
  timestamps: LessonTimestamp[],
  courtTactics: CourtTactic[] | null | undefined,
): FeedbackItem[] {
  const items: FeedbackItem[] = [];

  // 1. court_tactics를 기준으로 먼저 넣기
  const tactics = courtTactics ?? [];
  const usedTimestampSecs = new Set<number>();

  for (const ct of tactics) {
    items.push({
      sec: ct.sec,
      category: ct.category,
      position: ct.position,
      tactic: ct.tactic,
      label: ct.label,
      quote: ct.quote ?? null,
      fix: null,
      source: "court",
    });
  }

  // 2. timestamps 중 court_tactics에 없는 sec(+-5초 이내면 같은 것)는 추가
  for (const ts of timestamps) {
    const isDuplicate = tactics.some(
      (ct) => Math.abs(ct.sec - ts.sec) <= 5,
    );
    if (!isDuplicate) {
      items.push({
        sec: ts.sec,
        category: ts.category ?? null,
        position: null,
        tactic: null,
        label: ts.label,
        quote: ts.quote ?? null,
        fix: ts.fix ?? null,
        source: "timestamp",
      });
    } else {
      usedTimestampSecs.add(ts.sec);
    }
  }

  // 3. sec 오름차순 정렬
  items.sort((a, b) => a.sec - b.sec);

  return items;
}

/* -------------------------------------------------------------------------- */
/* FeedbackTimeline Component                                                  */
/* -------------------------------------------------------------------------- */

export function FeedbackTimeline({
  timestamps,
  courtTactics,
  onSeek,
  onSelectIndex,
  activeIndex,
}: FeedbackTimelineProps) {
  const items = useMemo(
    () => mergeFeedbackItems(timestamps, courtTactics),
    [timestamps, courtTactics],
  );

  if (items.length === 0) return null;

  return (
    <section className="rounded-2xl border border-gray-200 bg-white p-4 shadow-sm sm:p-6">
      <h3 className="text-base font-bold text-gray-900 sm:text-lg">
        피드백 타임라인
      </h3>
      <p className="mt-0.5 text-xs text-gray-500">
        레슨 중 코치 피드백 ({items.length}개) — 카드를 눌러 영상 이동
      </p>

      <ul className="mt-4 space-y-2">
        {items.map((item, i) => {
          const isActive = activeIndex === i;
          const mainText = item.tactic || item.label;
          const positionLabel = getPositionLabel(item.position);

          return (
            <li key={`${item.sec}-${i}`}>
              <button
                type="button"
                onClick={() => {
                  onSeek(item.sec);
                  onSelectIndex(i);
                }}
                className={[
                  "w-full rounded-xl border p-3 text-left transition-all",
                  isActive
                    ? "border-brand-400 bg-brand-50 ring-2 ring-brand-200"
                    : "border-gray-100 bg-white hover:border-gray-200 hover:bg-gray-50",
                ].join(" ")}
              >
                {/* Header row */}
                <div className="flex items-center gap-2 flex-wrap">
                  {/* 번호 */}
                  <span className="inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-gray-900 text-[10px] font-bold text-white">
                    {i + 1}
                  </span>

                  {/* 카테고리 뱃지 */}
                  {item.category && (
                    <span
                      className={`inline-flex rounded-full px-2 py-0.5 text-[10px] font-semibold ${getCategoryBadgeClass(item.category)}`}
                    >
                      {item.category}
                    </span>
                  )}

                  {/* 시간 */}
                  <span className="font-mono text-[11px] text-gray-500">
                    {formatTime(item.sec)}
                  </span>

                  {/* 이동 버튼 */}
                  <span className="ml-auto inline-flex items-center gap-0.5 text-[10px] font-medium text-brand-600">
                    <svg
                      xmlns="http://www.w3.org/2000/svg"
                      viewBox="0 0 20 20"
                      fill="currentColor"
                      className="h-3.5 w-3.5"
                      aria-hidden
                    >
                      <path d="M6.3 2.84A1.5 1.5 0 0 0 4 4.11v11.78a1.5 1.5 0 0 0 2.3 1.27l9.344-5.891a1.5 1.5 0 0 0 0-2.538L6.3 2.841Z" />
                    </svg>
                    이동
                  </span>
                </div>

                {/* Position (court only) */}
                {positionLabel && (
                  <p className="mt-1.5 text-xs text-gray-500">
                    {positionLabel}
                  </p>
                )}

                {/* Main text */}
                <p className="mt-1 text-sm font-medium leading-snug text-gray-900">
                  {mainText}
                </p>

                {/* Quote */}
                {item.quote && (
                  <p className="mt-1 text-xs italic text-gray-400">
                    &ldquo;{item.quote}&rdquo;
                  </p>
                )}

                {/* Fix (timestamps only) */}
                {item.fix && (
                  <p className="mt-1 flex items-start gap-1 text-xs text-brand-700">
                    <span className="shrink-0">→</span>
                    <span>{item.fix}</span>
                  </p>
                )}
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
