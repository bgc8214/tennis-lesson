import type { LessonReport } from "@/types/lesson";

interface NoteCardsProps {
  report: LessonReport;
}

function extractFirstSentence(text: string | null): string | null {
  if (!text) return null;
  const match = text.match(/^[^.!?\n]{10,}[.!?]/);
  return match?.[0]?.trim() ?? text.slice(0, 60).trim();
}

function KeyLearnings({ report }: { report: LessonReport }) {
  const lines = [
    { icon: "🎯", text: extractFirstSentence(report.card1_problem) },
    { icon: "💬", text: extractFirstSentence(report.card2_cueing) },
    { icon: "✅", text: extractFirstSentence(report.card3_action) },
  ].filter((l) => l.text);

  if (lines.length === 0) return null;

  return (
    <section className="rounded-2xl bg-gray-900 p-5 shadow-sm">
      <h3 className="mb-3 text-xs font-bold uppercase tracking-widest text-gray-400">
        오늘 레슨 핵심
      </h3>
      <ol className="space-y-2.5">
        {lines.map((line, i) => (
          <li key={i} className="flex items-start gap-3">
            <span className="mt-0.5 inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-white/10 text-xs font-bold text-white">
              {i + 1}
            </span>
            <span className="text-sm leading-relaxed text-gray-100">
              {line.icon} {line.text}
            </span>
          </li>
        ))}
      </ol>
    </section>
  );
}

export function NoteCards({ report }: NoteCardsProps) {
  const hasContent =
    report.card1_problem || report.card2_cueing || report.card3_action;

  if (!hasContent) {
    return (
      <div className="rounded-2xl border-2 border-dashed border-gray-200 bg-gray-50 p-6 text-center">
        <p className="text-sm text-gray-500">
          {report.error_message ??
            "오답노트를 생성하지 못했습니다. 다른 영상으로 시도해 보세요."}
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <KeyLearnings report={report} />
      {/* Card 1: 고질병 */}
      {report.card1_problem && (
        <section className="rounded-2xl border-2 border-red-200 bg-red-50 p-5 shadow-sm">
          <header className="mb-3 flex items-center gap-2">
            <span
              className="inline-flex h-7 w-7 items-center justify-center rounded-full bg-red-500 text-sm font-bold text-white"
              aria-hidden
            >
              1
            </span>
            <h3 className="text-base font-bold text-red-700 sm:text-lg">
              고질병
            </h3>
          </header>
          <p className="leading-relaxed text-gray-800">
            {report.card1_problem}
          </p>
        </section>
      )}

      {/* Card 2: 코치 큐잉 */}
      {report.card2_cueing && (
        <section className="rounded-2xl border-2 border-blue-200 bg-blue-50 p-5 shadow-sm">
          <header className="mb-3 flex items-center gap-2">
            <span
              className="inline-flex h-7 w-7 items-center justify-center rounded-full bg-blue-500 text-sm font-bold text-white"
              aria-hidden
            >
              2
            </span>
            <h3 className="text-base font-bold text-blue-700 sm:text-lg">
              코치 큐잉
            </h3>
          </header>
          <blockquote className="leading-relaxed text-gray-800 italic">
            &ldquo;{report.card2_cueing}&rdquo;
          </blockquote>
        </section>
      )}

      {/* Card 3: 액션 플랜 */}
      {report.card3_action && (
        <section className="rounded-2xl border-2 border-brand-200 bg-brand-50 p-5 shadow-sm">
          <header className="mb-3 flex items-center gap-2">
            <span
              className="inline-flex h-7 w-7 items-center justify-center rounded-full bg-brand-500 text-sm font-bold text-white"
              aria-hidden
            >
              3
            </span>
            <h3 className="text-base font-bold text-brand-700 sm:text-lg">
              액션 플랜
            </h3>
          </header>
          <p className="leading-relaxed text-gray-800">{report.card3_action}</p>
        </section>
      )}

      {/* 키워드 */}
      {report.keywords?.length > 0 && (
        <div className="flex flex-wrap gap-2 pt-1">
          {report.keywords.map((kw, i) => (
            <span
              key={`${kw}-${i}`}
              className="rounded-full bg-gray-100 px-3 py-1 text-xs font-medium text-gray-600 sm:text-sm"
            >
              #{kw}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
