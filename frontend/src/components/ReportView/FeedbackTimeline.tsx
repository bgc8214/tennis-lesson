"use client";

import { useMemo } from "react";
import type { CourtTactic, LessonTimestamp } from "@/types/lesson";

/* -------------------------------------------------------------------------- */
/* Types                                                                       */
/* -------------------------------------------------------------------------- */

export interface FeedbackItem {
  sec: number;
  type?: "교정" | "드릴" | "전술";
  category: string | null;
  position?: string | null;
  tactic?: string | null;
  label: string;
  quote?: string | null;
  fix?: string | null;
  matchScore?: number | null;
  source: "court" | "timestamp";
}

interface FeedbackTimelineProps {
  timestamps: LessonTimestamp[];
  courtTactics: CourtTactic[] | null | undefined;
  onSeek: (sec: number) => void;
  onSelectIndex: (index: number) => void;
  activeIndex: number | null;
  /** 15문서 2-A: "low"/null이면 quote 원문을 숨기고 모먼트 내비게이션으로
   * 전환한다 — 골든셋 검토로 quote 정밀도 13~20%가 실증되어 원문을
   * "코치가 실제로 한 말"처럼 노출하면 신뢰를 해친다. 반면 그 순간에
   * 코칭이 있었다는 사실(모먼트) 자체는 검증 게이트로 확인된 정보다. */
  transcriptQuality?: "high" | "low" | null;
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

function getTypeBadgeClass(type: string | null | undefined): string {
  if (type === "드릴") return "bg-amber-100 text-amber-700";
  if (type === "전술") return "bg-cyan-100 text-cyan-700";
  return "bg-rose-100 text-rose-700"; // 교정 (기본)
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

  const tactics = courtTactics ?? [];

  // 1. court_tactics 기준으로 넣되, 같은 시점의 timestamp fix도 합침
  for (const ct of tactics) {
    const matchingTs = timestamps.find((ts) => Math.abs(ct.sec - ts.sec) <= 5);
    items.push({
      sec: ct.sec,
      category: ct.category,
      position: ct.position,
      tactic: ct.tactic,
      label: ct.label,
      quote: ct.quote ?? null,
      fix: matchingTs?.fix ?? null,  // timestamps의 fix 병합
      source: "court",
    });
  }

  // 2. court_tactics에 없는 timestamps만 추가
  for (const ts of timestamps) {
    const isDuplicate = tactics.some((ct) => Math.abs(ct.sec - ts.sec) <= 5);
    if (!isDuplicate) {
      items.push({
        sec: ts.sec,
        type: ts.type,
        category: ts.category ?? null,
        position: null,
        tactic: null,
        label: ts.label,
        quote: ts.quote ?? null,
        fix: ts.fix ?? null,
        matchScore: ts.match_score ?? null,
        source: "timestamp",
      });
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
  transcriptQuality,
}: FeedbackTimelineProps) {
  const items = useMemo(
    () => mergeFeedbackItems(timestamps, courtTactics),
    [timestamps, courtTactics],
  );

  // low/null(미판정 포함)이면 인용을 신뢰 노출하지 않는다 — high만 원문 표시.
  const showQuote = transcriptQuality === "high";

  if (items.length === 0) return null;

  return (
    <section className="rounded-2xl border border-gray-200 bg-white p-4 shadow-sm sm:p-6">
      <h3 className="text-base font-bold text-gray-900 sm:text-lg">
        {showQuote ? "피드백 타임라인" : "🔊 코칭 구간 안내"}
      </h3>
      <p className="mt-0.5 text-xs text-gray-500">
        {showQuote
          ? `레슨 중 코치 피드백 (${items.length}개) — 카드를 눌러 영상 이동`
          : `이 영상은 음성이 멀어 정확한 발언 대신 코칭 구간 중심으로 안내해요 (${items.length}개) — 카드를 눌러 영상에서 직접 들어보세요`}
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

                {item.source === "timestamp" && !showQuote ? (
                  // 15문서 2-A: quote 대신 모먼트 내비게이션 — "코치가 이렇게
                  // 말했다"로 오인되지 않도록 AI 추정 라벨을 항상 노출한다.
                  <p className="mt-1.5 flex items-center gap-1 text-[11px] font-medium text-gray-400">
                    <span aria-hidden>🔊</span>
                    <span>이 구간에서 코칭이 있었어요 (AI 추정, 발언 내용은 영상에서 직접 확인)</span>
                  </p>
                ) : (
                  <>
                    {/* Quote — 09문서 1-6: 검증된 코치 발언 원문 + match_score 뱃지 */}
                    {item.quote && (
                      <div className="mt-1.5">
                        {item.matchScore != null && (
                          <span className="mb-1 flex w-fit items-center gap-1 rounded-full bg-emerald-50 px-2 py-0.5 text-[10px] font-semibold text-emerald-700">
                            🎾 코치님 말씀 · 일치도 {Math.round(item.matchScore * 100)}%
                          </span>
                        )}
                        <p className="text-xs italic text-gray-400">
                          &ldquo;{item.quote}&rdquo;
                        </p>
                      </div>
                    )}

                    {/* Fix (timestamps only) */}
                    {item.fix && (
                      <p className="mt-1 flex items-start gap-1 text-xs text-brand-700">
                        <span className="shrink-0">→</span>
                        <span>{item.fix}</span>
                      </p>
                    )}
                  </>
                )}
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
