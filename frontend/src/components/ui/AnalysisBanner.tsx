"use client";

import Link from "next/link";
import { useAnalysisTracker } from "@/lib/AnalysisTracker";

const STEPS = [
  "대기 중...",
  "🎵 오디오 다운로드 중...",
  "🔍 영상 분석 중...",
  "📝 오답노트 정리 중...",
];

export function AnalysisBanner() {
  const { active, dismiss } = useAnalysisTracker();

  if (active.length === 0) return null;

  return (
    <div className="border-b border-blue-200 bg-blue-50">
      <div className="mx-auto max-w-6xl px-4 py-3 sm:px-6">
        <div className="space-y-2">
          {active.map((a) => {
            const display = a.message ?? STEPS[Math.min(a.step, 3)] ?? "분석 중...";
            const pct = Math.max(Math.round((Math.min(a.step, 3) / 3) * 100), 5);
            return (
              <div key={a.lessonId} className="flex items-center gap-4">
                {/* 진행 정보 */}
                <div className="min-w-0 flex-1">
                  <div className="flex items-center justify-between gap-2">
                    <p className="truncate text-sm font-semibold text-blue-900">
                      {a.title ?? "레슨 분석 중..."}
                    </p>
                    <span className="shrink-0 text-xs font-bold text-blue-600">{pct}%</span>
                  </div>
                  <p className="mt-0.5 text-xs text-blue-700" aria-live="polite">
                    {display}
                  </p>
                  <div className="mt-1.5 h-1 w-full overflow-hidden rounded-full bg-blue-200">
                    <div
                      className="h-full rounded-full bg-blue-500 transition-all duration-700"
                      style={{ width: `${pct}%` }}
                    />
                  </div>
                </div>

                {/* 액션 버튼 */}
                <div className="flex shrink-0 items-center gap-2">
                  <Link
                    href={`/lessons/${a.lessonId}`}
                    className="rounded-lg bg-blue-500 px-3 py-1.5 text-xs font-semibold text-white hover:bg-blue-600"
                  >
                    상세 보기
                  </Link>
                  <button
                    type="button"
                    onClick={() => dismiss(a.lessonId)}
                    className="rounded-lg border border-blue-300 px-2 py-1.5 text-xs text-blue-600 hover:bg-blue-100"
                    aria-label="닫기"
                  >
                    ✕
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
