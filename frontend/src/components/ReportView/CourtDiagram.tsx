"use client";

import { useMemo, useState } from "react";
import type { CourtAnalysisStatus, CourtTactic, LessonTimestamp } from "@/types/lesson";
import { mergeFeedbackItems, getPositionLabel, type FeedbackItem } from "./FeedbackTimeline";
import { LoadingSpinner } from "@/components/ui/LoadingSpinner";
import { ReactionButtons } from "./ReactionButtons";
import type { ReactionsMap } from "@/types/lesson";

/* -------------------------------------------------------------------------- */
/* Utilities                                                                   */
/* -------------------------------------------------------------------------- */

function formatTime(sec: number): string {
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

/** Category to marker color mapping. */
function getCategoryColor(category: string | null | undefined): string {
  if (!category) return "#6b7280"; // gray-500
  const lower = category.toLowerCase();
  if (lower.includes("포핸드")) return "#ef4444"; // red-500
  if (lower.includes("백핸드")) return "#3b82f6"; // blue-500
  if (lower.includes("발리")) return "#22c55e"; // green-500
  if (lower.includes("서브")) return "#a855f7"; // purple-500
  if (lower.includes("풋워크") || lower.includes("스텝")) return "#f97316"; // orange-500
  return "#6b7280"; // gray-500
}

function getTypeBadgeClass(type: string | null | undefined): string {
  if (type === "드릴") return "bg-amber-100 text-amber-700";
  if (type === "전술") return "bg-cyan-100 text-cyan-700";
  return "bg-rose-100 text-rose-700";
}

function getCategoryBadgeClass(category: string | null | undefined): string {
  if (!category) return "bg-gray-100 text-gray-700";
  const lower = category.toLowerCase();
  if (lower.includes("포핸드")) return "bg-red-100 text-red-700";
  if (lower.includes("백핸드")) return "bg-blue-100 text-blue-700";
  if (lower.includes("발리")) return "bg-green-100 text-green-700";
  if (lower.includes("서브")) return "bg-purple-100 text-purple-700";
  if (lower.includes("풋워크") || lower.includes("스텝")) return "bg-orange-100 text-orange-700";
  return "bg-gray-100 text-gray-700";
}

/* -------------------------------------------------------------------------- */
/* Court SVG                                                                   */
/* -------------------------------------------------------------------------- */

/** Static half-court SVG (top-down, rear camera angle). */
function CourtSVG() {
  return (
    <g>
      {/* Court surface */}
      <rect x="10" y="10" width="280" height="380" rx="2" fill="#e8f5e9" />

      {/* Outer boundary */}
      <rect
        x="30"
        y="20"
        width="240"
        height="360"
        fill="none"
        stroke="#ffffff"
        strokeWidth="2.5"
      />

      {/* Net line (top) */}
      <line x1="30" y1="20" x2="270" y2="20" stroke="#9ca3af" strokeWidth="3" />

      {/* Service line */}
      <line x1="30" y1="180" x2="270" y2="180" stroke="#ffffff" strokeWidth="2" />

      {/* Center service line */}
      <line x1="150" y1="20" x2="150" y2="180" stroke="#ffffff" strokeWidth="2" />

      {/* Center mark on baseline */}
      <line x1="150" y1="370" x2="150" y2="380" stroke="#ffffff" strokeWidth="2" />

      {/* Singles sidelines (narrower for doubles court representation) */}
      <line x1="50" y1="20" x2="50" y2="380" stroke="#ffffff" strokeWidth="1.5" strokeDasharray="4 4" opacity="0.5" />
      <line x1="250" y1="20" x2="250" y2="380" stroke="#ffffff" strokeWidth="1.5" strokeDasharray="4 4" opacity="0.5" />

      {/* Zone labels (subtle) */}
      <text x="150" y="14" textAnchor="middle" fontSize="8" fill="#6b7280" opacity="0.7">NET</text>
      <text x="150" y="395" textAnchor="middle" fontSize="8" fill="#6b7280" opacity="0.7">BASELINE</text>
    </g>
  );
}

/* -------------------------------------------------------------------------- */
/* TacticMarker                                                               */
/* -------------------------------------------------------------------------- */

interface TacticMarkerProps {
  tactic: CourtTactic;
  index: number;
  isSelected: boolean;
  onSelect: (index: number) => void;
}

/** 같은 position에 여러 마커가 몰릴 때 나선형으로 분산 */
function getJitteredCoords(
  tactics: CourtTactic[],
  index: number,
): { cx: number; cy: number } {
  const t = tactics[index];
  const baseCx = 30 + t.position_x * 240;
  const baseCy = 20 + t.position_y * 360;

  // 같은 (position_x, position_y)인 마커들 찾기
  const samePos = tactics
    .map((tt, i) => ({ i, same: tt.position_x === t.position_x && tt.position_y === t.position_y }))
    .filter((x) => x.same);

  if (samePos.length <= 1) return { cx: baseCx, cy: baseCy };

  const myOrder = samePos.findIndex((x) => x.i === index);
  const spread = 14; // 중심에서 퍼지는 반경
  const angle = (myOrder / samePos.length) * 2 * Math.PI - Math.PI / 2;
  return {
    cx: baseCx + spread * Math.cos(angle),
    cy: baseCy + spread * Math.sin(angle),
  };
}

interface TacticArrowProps {
  tactic: CourtTactic;
  cx: number;
  cy: number;
}

function TacticArrow({ tactic, cx, cy }: TacticArrowProps) {
  if (!tactic.to_position_x || !tactic.to_position_y) return null;
  const tx = 30 + tactic.to_position_x * 240;
  const ty = 20 + tactic.to_position_y * 360;
  const color = getCategoryColor(tactic.category);

  // 화살표 방향 벡터 (끝점 근처에서 마커를 피해 10px 앞에서 끝냄)
  const dx = tx - cx;
  const dy = ty - cy;
  const len = Math.sqrt(dx * dx + dy * dy);
  if (len < 1) return null;
  const ex = tx - (dx / len) * 12;
  const ey = ty - (dy / len) * 12;

  return (
    <g>
      <defs>
        <marker
          id={`arrow-${tactic.sec}`}
          markerWidth="6" markerHeight="6"
          refX="3" refY="3"
          orient="auto"
        >
          <path d="M0,0 L0,6 L6,3 z" fill={color} opacity="0.8" />
        </marker>
      </defs>
      <line
        x1={cx} y1={cy}
        x2={ex} y2={ey}
        stroke={color}
        strokeWidth="2"
        strokeDasharray="5 3"
        opacity="0.7"
        markerEnd={`url(#arrow-${tactic.sec})`}
      />
    </g>
  );
}

function TacticMarker({ tactic, index, isSelected, onSelect, tactics }: TacticMarkerProps & { tactics: CourtTactic[] }) {
  const { cx, cy } = getJitteredCoords(tactics, index);
  const color = getCategoryColor(tactic.category);
  const radius = isSelected ? 12 : 9;

  return (
    <g>
      {/* 이동 화살표 (마커 뒤에 렌더링) */}
      <TacticArrow tactic={tactic} cx={cx} cy={cy} />
      <g
        className="cursor-pointer transition-transform"
        onClick={() => onSelect(index)}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") onSelect(index); }}
        aria-label={`${tactic.label} - ${tactic.tactic}`}
      >
        {/* Pulse ring for selected */}
        {isSelected && (
          <circle
            cx={cx}
            cy={cy}
            r={radius + 4}
            fill="none"
            stroke={color}
            strokeWidth="2"
            opacity="0.4"
            className="animate-ping"
          />
        )}
        {/* Shadow */}
        <circle cx={cx} cy={cy + 1} r={radius} fill="black" opacity="0.15" />
        {/* Main marker */}
        <circle
          cx={cx}
          cy={cy}
          r={radius}
          fill={color}
          stroke="#ffffff"
          strokeWidth="2"
          opacity={isSelected ? 1 : 0.85}
        />
        {/* Index label */}
        <text
          x={cx}
          y={cy + 1}
          textAnchor="middle"
          dominantBaseline="middle"
          fontSize={isSelected ? "9" : "8"}
          fontWeight="bold"
          fill="#ffffff"
        >
          {index + 1}
        </text>
      </g>
    </g>
  );
}

/* -------------------------------------------------------------------------- */
/* Tooltip Popover (shows on marker select, positioned near SVG)              */
/* -------------------------------------------------------------------------- */

interface TooltipProps {
  tactic: CourtTactic;
  onClose: () => void;
}

function TacticTooltip({ tactic, onClose }: TooltipProps) {
  return (
    <div className="absolute left-1/2 bottom-2 z-10 w-64 -translate-x-1/2 rounded-xl border border-gray-200 bg-white p-3 shadow-lg sm:w-72">
      <button
        type="button"
        onClick={onClose}
        className="absolute top-2 right-2 text-gray-400 hover:text-gray-600"
        aria-label="닫기"
      >
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="h-4 w-4">
          <path d="M6.28 5.22a.75.75 0 0 0-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 1 0 1.06 1.06L10 11.06l3.72 3.72a.75.75 0 1 0 1.06-1.06L11.06 10l3.72-3.72a.75.75 0 0 0-1.06-1.06L10 8.94 6.28 5.22Z" />
        </svg>
      </button>
      <div className="flex items-center gap-2">
        <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-semibold ${getCategoryBadgeClass(tactic.category)}`}>
          {tactic.category}
        </span>
        <span className="text-xs text-gray-500">{formatTime(tactic.sec)}</span>
      </div>
      <p className="mt-1.5 text-sm font-semibold text-gray-900">{tactic.tactic}</p>
      {tactic.quote && (
        <p className="mt-1 text-xs text-gray-500 italic">&ldquo;{tactic.quote}&rdquo;</p>
      )}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Tactic Card (list item)                                                    */
/* -------------------------------------------------------------------------- */

interface TacticCardProps {
  tactic: CourtTactic;
  index: number;
  isSelected: boolean;
  onSelect: (index: number) => void;
}

function TacticCard({ tactic, index, isSelected, onSelect }: TacticCardProps) {
  return (
    <button
      type="button"
      onClick={() => onSelect(index)}
      className={[
        "w-full rounded-xl border p-3 text-left transition-all",
        isSelected
          ? "border-brand-300 bg-brand-50 ring-1 ring-brand-200"
          : "border-gray-100 bg-white hover:border-gray-200 hover:bg-gray-50",
      ].join(" ")}
    >
      <div className="flex items-center gap-2">
        <span
          className="inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[10px] font-bold text-white"
          style={{ backgroundColor: getCategoryColor(tactic.category) }}
        >
          {index + 1}
        </span>
        <span className={`inline-flex rounded-full px-2 py-0.5 text-[10px] font-semibold ${getCategoryBadgeClass(tactic.category)}`}>
          {tactic.category}
        </span>
        <span className="ml-auto text-[10px] font-mono text-gray-400">
          {formatTime(tactic.sec)}
        </span>
      </div>
      <p className="mt-1.5 text-sm font-medium text-gray-900 leading-snug">
        {tactic.tactic}
      </p>
      {tactic.quote && (
        <p className="mt-1 text-xs text-gray-500 truncate italic">
          &ldquo;{tactic.quote}&rdquo;
        </p>
      )}
    </button>
  );
}

/* -------------------------------------------------------------------------- */
/* Main CourtDiagram Component                                                */
/* -------------------------------------------------------------------------- */

interface CourtDiagramProps {
  tactics: CourtTactic[];
  timestamps?: LessonTimestamp[];
  courtAnalysisStatus?: CourtAnalysisStatus;
  onSeek?: (sec: number) => void;
  selectedIndex?: number | null;
  onSelectIndex?: (index: number | null) => void;
  /** 15문서 2-A: "low"/null이면 timestamps 출처(source==="timestamp") 항목의
   * quote 원문을 숨기고 모먼트 내비게이션으로 전환한다. court 출처(관절
   * 분석)는 별개 검증 체계라 이 판단에서 제외 — 계속 quote 그대로 노출. */
  transcriptQuality?: "high" | "low" | null;
  /** 13문서 대체카드: 항목별 👍/👎 표시용. lessonId 없으면 반응 버튼 숨김. */
  lessonId?: string;
  reactions?: ReactionsMap;
}

function feedbackTargetKey(item: FeedbackItem): string {
  return `${item.source}:${item.sec}`;
}

export function CourtDiagram({
  tactics,
  timestamps = [],
  courtAnalysisStatus,
  onSeek,
  selectedIndex: controlledIndex,
  onSelectIndex,
  transcriptQuality,
  lessonId,
  reactions = {},
}: CourtDiagramProps) {
  const showQuote = transcriptQuality === "high";
  const [internalIndex, setInternalIndex] = useState<number | null>(null);
  const feedbackItems = useMemo(() => mergeFeedbackItems(timestamps, tactics), [timestamps, tactics]);

  // Support both controlled and uncontrolled modes
  const selectedIndex = controlledIndex !== undefined ? controlledIndex : internalIndex;

  const handleSelect = (index: number) => {
    const newIndex = selectedIndex === index ? null : index;
    if (onSelectIndex) {
      onSelectIndex(newIndex);
    } else {
      setInternalIndex(newIndex);
    }
    // Seek to the tactic's timestamp when clicking a marker
    if (newIndex !== null && onSeek && tactics[newIndex]) {
      onSeek(tactics[newIndex].sec);
    }
  };

  // Status-based rendering
  if (courtAnalysisStatus === "PROCESSING") {
    return (
      <section className="rounded-2xl border border-gray-200 bg-white p-6 shadow-sm">
        <h3 className="text-base font-bold text-gray-900 sm:text-lg">
          오늘의 코트 전술
        </h3>
        <div className="mt-6 flex flex-col items-center justify-center gap-3 py-8">
          <LoadingSpinner size="md" />
          <p className="text-sm text-gray-500">코트 전술을 분석 중입니다...</p>
        </div>
      </section>
    );
  }

  if (courtAnalysisStatus === "FAILED") {
    return (
      <section className="rounded-2xl border border-red-100 bg-red-50/50 p-6 shadow-sm">
        <h3 className="text-base font-bold text-gray-900 sm:text-lg">
          오늘의 코트 전술
        </h3>
        <div className="mt-4 flex flex-col items-center justify-center gap-2 py-6">
          <div className="inline-flex h-10 w-10 items-center justify-center rounded-full bg-red-100 text-red-500">
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="h-5 w-5">
              <path fillRule="evenodd" d="M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0Zm-8-5a.75.75 0 0 1 .75.75v4.5a.75.75 0 0 1-1.5 0v-4.5A.75.75 0 0 1 10 5Zm0 10a1 1 0 1 0 0-2 1 1 0 0 0 0 2Z" clipRule="evenodd" />
            </svg>
          </div>
          <p className="text-sm text-red-700">코트 분석에 실패했습니다.</p>
          <p className="text-xs text-red-500/80">영상 형식 또는 화질 문제일 수 있습니다.</p>
        </div>
      </section>
    );
  }

  // court_analysis_status is null/undefined => timestamps-only mode
  if (courtAnalysisStatus === null || courtAnalysisStatus === undefined) {
    if (feedbackItems.length === 0) return null;
    return (
      <section className="rounded-2xl border border-gray-200 bg-white p-4 shadow-sm sm:p-6">
        <h3 className="text-base font-bold text-gray-900 sm:text-lg">
          {showQuote ? "피드백 타임라인" : "🔊 코칭 구간 안내"}
        </h3>
        <p className="mt-0.5 text-xs text-gray-500">
          {showQuote
            ? `코치 피드백 (${feedbackItems.length}개) — 카드를 눌러 영상 이동`
            : `이 영상은 음성이 멀어 정확한 발언 대신 코칭 구간 중심으로 안내해요 (${feedbackItems.length}개) — 카드를 눌러 영상에서 직접 들어보세요`}
        </p>
        <ul className="mt-4 space-y-2">
          {feedbackItems.map((item: FeedbackItem, i: number) => {
            const mainText = item.tactic || item.label;
            const hideQuote = item.source === "timestamp" && !showQuote;
            return (
              <li key={`${item.sec}-${i}`}>
                <button
                  type="button"
                  onClick={() => { if (onSeek) onSeek(item.sec); }}
                  className="w-full rounded-xl border border-gray-100 bg-white p-3 text-left transition-all hover:border-gray-200 hover:bg-gray-50"
                >
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-gray-900 text-[10px] font-bold text-white">{i + 1}</span>
                    {item.type && (
                      <span className={`inline-flex rounded-full px-2 py-0.5 text-[10px] font-semibold ${getTypeBadgeClass(item.type)}`}>{item.type}</span>
                    )}
                    {item.category && (
                      <span className={`inline-flex rounded-full px-2 py-0.5 text-[10px] font-semibold ${getCategoryBadgeClass(item.category)}`}>{item.category}</span>
                    )}
                    <span className="font-mono text-[11px] text-gray-500">{formatTime(item.sec)}</span>
                    <span className="ml-auto inline-flex items-center gap-0.5 text-[10px] font-medium text-brand-600">
                      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="h-3.5 w-3.5" aria-hidden>
                        <path d="M6.3 2.84A1.5 1.5 0 0 0 4 4.11v11.78a1.5 1.5 0 0 0 2.3 1.27l9.344-5.891a1.5 1.5 0 0 0 0-2.538L6.3 2.841Z" />
                      </svg>
                      이동
                    </span>
                  </div>
                  <p className="mt-1 text-sm font-medium leading-snug text-gray-900">{mainText}</p>
                  {hideQuote ? (
                    <p className="mt-1.5 flex items-center gap-1 text-[11px] font-medium text-gray-400">
                      <span aria-hidden>🔊</span>
                      <span>이 구간에서 코칭이 있었어요 (AI 추정, 발언 내용은 영상에서 직접 확인)</span>
                    </p>
                  ) : (
                    <>
                      {item.quote && <p className="mt-1 text-xs italic text-gray-400">&ldquo;{item.quote}&rdquo;</p>}
                      {item.fix && (
                        <p className="mt-1 flex items-start gap-1 text-xs text-brand-700">
                          <span className="shrink-0">→</span><span>{item.fix}</span>
                        </p>
                      )}
                    </>
                  )}
                  {lessonId && (
                    <div className="mt-2 flex justify-end">
                      <ReactionButtons
                        lessonId={lessonId}
                        targetKey={feedbackTargetKey(item)}
                        initialValue={reactions[feedbackTargetKey(item)]}
                      />
                    </div>
                  )}
                </button>
              </li>
            );
          })}
        </ul>
      </section>
    );
  }

  // DONE status but empty tactics
  if (!tactics || tactics.length === 0) {
    return (
      <section className="rounded-2xl border border-gray-200 bg-white p-6 shadow-sm">
        <h3 className="text-base font-bold text-gray-900 sm:text-lg">
          오늘의 코트 전술
        </h3>
        <div className="mt-4 flex flex-col items-center justify-center gap-2 py-6">
          <p className="text-sm text-gray-500">코트 전술 데이터가 없습니다</p>
          <p className="text-xs text-gray-400">위치 기반 피드백이 감지되지 않았어요.</p>
        </div>
      </section>
    );
  }

  // Normal rendering with tactics data
  const selectedTactic = selectedIndex !== null ? tactics[selectedIndex] : null;

  return (
    <section className="rounded-2xl border border-gray-200 bg-white p-4 shadow-sm sm:p-6">
      <h3 className="text-base font-bold text-gray-900 sm:text-lg">
        오늘의 코트 전술
      </h3>
      <p className="mt-0.5 text-xs text-gray-500">
        코치가 지적한 위치별 전술 피드백 ({tactics.length}개)
      </p>

      {/* Court Diagram + Tooltip */}
      <div className="relative mx-auto mt-4 max-w-sm">
        <svg
          viewBox="0 0 300 400"
          width="100%"
          className="rounded-xl border border-gray-100"
          aria-label="하프코트 전술 다이어그램"
          role="img"
        >
          <CourtSVG />
          {tactics.map((tactic, i) => (
            <TacticMarker
              key={`${tactic.sec}-${i}`}
              tactic={tactic}
              index={i}
              isSelected={selectedIndex === i}
              onSelect={handleSelect}
              tactics={tactics}
            />
          ))}
        </svg>

        {/* Tooltip popover */}
        {selectedTactic && (
          <TacticTooltip
            tactic={selectedTactic}
            onClose={() => {
              if (onSelectIndex) {
                onSelectIndex(null);
              } else {
                setInternalIndex(null);
              }
            }}
          />
        )}
      </div>

      {/* 통합 피드백 카드 목록 */}
      {feedbackItems.length > 0 && (
        <ul className="mt-4 space-y-2">
          {feedbackItems.map((item: FeedbackItem, i: number) => {
            // court 출처면 tactics 인덱스와 매핑해서 마커 강조
            const tacticIndex = item.source === "court"
              ? tactics.findIndex((t) => t.sec === item.sec)
              : -1;
            const isActive = tacticIndex >= 0 && selectedIndex === tacticIndex;
            const mainText = item.tactic || item.label;
            const posLabel = getPositionLabel(item.position);
            const hideQuote = item.source === "timestamp" && !showQuote;

            return (
              <li key={`${item.sec}-${i}`}>
                <button
                  type="button"
                  onClick={() => {
                    if (onSeek) onSeek(item.sec);
                    if (tacticIndex >= 0) handleSelect(tacticIndex);
                  }}
                  className={[
                    "w-full rounded-xl border p-3 text-left transition-all",
                    isActive
                      ? "border-brand-400 bg-brand-50 ring-2 ring-brand-200"
                      : "border-gray-100 bg-white hover:border-gray-200 hover:bg-gray-50",
                  ].join(" ")}
                >
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-gray-900 text-[10px] font-bold text-white">
                      {i + 1}
                    </span>
                    {item.category && (
                      <span className={`inline-flex rounded-full px-2 py-0.5 text-[10px] font-semibold ${getCategoryBadgeClass(item.category)}`}>
                        {item.category}
                      </span>
                    )}
                    <span className="font-mono text-[11px] text-gray-500">{formatTime(item.sec)}</span>
                    <span className="ml-auto inline-flex items-center gap-0.5 text-[10px] font-medium text-brand-600">
                      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="h-3.5 w-3.5" aria-hidden>
                        <path d="M6.3 2.84A1.5 1.5 0 0 0 4 4.11v11.78a1.5 1.5 0 0 0 2.3 1.27l9.344-5.891a1.5 1.5 0 0 0 0-2.538L6.3 2.841Z" />
                      </svg>
                      이동
                    </span>
                  </div>
                  {posLabel && (
                    <p className="mt-1.5 text-xs text-gray-500">{posLabel}</p>
                  )}
                  <p className="mt-1 text-sm font-medium leading-snug text-gray-900">{mainText}</p>
                  {hideQuote ? (
                    <p className="mt-1.5 flex items-center gap-1 text-[11px] font-medium text-gray-400">
                      <span aria-hidden>🔊</span>
                      <span>이 구간에서 코칭이 있었어요 (AI 추정, 발언 내용은 영상에서 직접 확인)</span>
                    </p>
                  ) : (
                    <>
                      {item.quote && (
                        <p className="mt-1 text-xs italic text-gray-400">&ldquo;{item.quote}&rdquo;</p>
                      )}
                      {item.fix && (
                        <p className="mt-1 flex items-start gap-1 text-xs text-brand-700">
                          <span className="shrink-0">→</span>
                          <span>{item.fix}</span>
                        </p>
                      )}
                    </>
                  )}
                  {lessonId && (
                    <div className="mt-2 flex justify-end">
                      <ReactionButtons
                        lessonId={lessonId}
                        targetKey={feedbackTargetKey(item)}
                        initialValue={reactions[feedbackTargetKey(item)]}
                      />
                    </div>
                  )}
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
