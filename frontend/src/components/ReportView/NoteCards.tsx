import type { LessonReport } from "@/types/lesson";
import { ReactionButtons } from "./ReactionButtons";

interface NoteCardsProps {
  report: LessonReport;
  lessonId: string;
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

export function NoteCards({ report, lessonId }: NoteCardsProps) {
  const reactions = report.reactions ?? {};
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
            <ReactionButtons
              className="ml-auto"
              lessonId={lessonId}
              targetKey="card1_problem"
              initialValue={reactions.card1_problem}
            />
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
            <ReactionButtons
              className="ml-auto"
              lessonId={lessonId}
              targetKey="card2_cueing"
              initialValue={reactions.card2_cueing}
            />
          </header>
          {/* 15문서 2-A: card2_cueing은 Pass B가 만든 취지 요약이지 코치
              원문 인용이 아니다 — 따옴표+blockquote는 "코치가 이렇게
              말했다"로 오인되기 쉬워 일반 문단으로 표시한다. */}
          <p className="leading-relaxed text-gray-800">
            {report.card2_cueing}
          </p>
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
            <ReactionButtons
              className="ml-auto"
              lessonId={lessonId}
              targetKey="card3_action"
              initialValue={reactions.card3_action}
            />
          </header>
          <p className="leading-relaxed text-gray-800">{report.card3_action}</p>
        </section>
      )}

      {/* AI 코치 노트 — 09문서 1-6: quote 없는 AI 일반 지식 보충 설명.
          코치 인용 카드(1~3)와 확실히 다른 배경색·아이콘으로 구분하고
          "AI 보조 설명" 라벨을 항상 노출해 코치 발언으로 오인되지 않게 함. */}
      {report.ai_context && report.ai_context.length > 0 && (
        <section className="rounded-2xl border-2 border-dashed border-violet-200 bg-violet-50 p-5 shadow-sm">
          <header className="mb-3 flex items-center gap-2">
            <span className="text-lg" aria-hidden>
              💡
            </span>
            <h3 className="text-base font-bold text-violet-700 sm:text-lg">
              AI 코치 노트
            </h3>
            <span className="rounded-full bg-violet-200 px-2 py-0.5 text-[10px] font-semibold text-violet-800">
              AI 보조 설명
            </span>
          </header>
          <ul className="space-y-3">
            {report.ai_context.map((note, i) => (
              <li key={`${note.title}-${i}`}>
                <p className="text-sm font-semibold text-violet-900">
                  {note.title}
                </p>
                <p className="mt-0.5 text-sm leading-relaxed text-violet-700">
                  {note.note}
                </p>
              </li>
            ))}
          </ul>
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
