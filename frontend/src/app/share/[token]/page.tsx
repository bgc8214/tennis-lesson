"use client";

/**
 * 09문서 #5 / 13문서 축4: 코치 확인 링크 — 인증 없이 여는 읽기전용 리포트 뷰.
 *
 * lessons/[id] 페이지와 달리 Supabase 직접 조회가 아니라 백엔드
 * /api/v1/public/lessons/{share_token}를 사용한다 — RLS가 anon 클라이언트의
 * 타인 레슨 조회를 막기 때문에, 이 라우트만 service role로 우회해야 한다.
 */

import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { getPublicLesson, submitCoachComment, type PublicLesson } from "@/lib/api";
import { LoadingSpinner } from "@/components/ui/LoadingSpinner";
import { ApiCallError } from "@/types/lesson";

function formatTime(sec: number): string {
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

export default function SharedLessonPage() {
  const params = useParams<{ token: string }>();
  const token = params?.token;

  const [lesson, setLesson] = useState<PublicLesson | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const [comment, setComment] = useState("");
  const [submitted, setSubmitted] = useState<"confirmed" | "needs_fix" | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!token) return;
    getPublicLesson(token)
      .then(setLesson)
      .catch((err) => {
        setError(err instanceof ApiCallError ? err.message : "링크를 열 수 없습니다.");
      })
      .finally(() => setLoading(false));
  }, [token]);

  const handleSubmit = useCallback(
    async (verdict: "confirmed" | "needs_fix") => {
      if (!token || submitting) return;
      setSubmitting(true);
      try {
        await submitCoachComment(token, verdict, comment.trim() || undefined);
        setSubmitted(verdict);
      } catch {
        setError("코멘트 등록에 실패했습니다. 다시 시도해 주세요.");
      } finally {
        setSubmitting(false);
      }
    },
    [token, comment, submitting],
  );

  if (loading) {
    return (
      <div className="flex min-h-[40vh] items-center justify-center text-gray-500">
        <LoadingSpinner size="lg" label="리포트를 불러오는 중..." />
      </div>
    );
  }

  if (error || !lesson) {
    return (
      <div className="mx-auto max-w-md rounded-2xl border border-gray-200 bg-white p-8 text-center shadow-sm">
        <h2 className="text-lg font-bold text-gray-900">링크가 유효하지 않아요</h2>
        <p className="mt-2 text-sm text-gray-600">{error ?? "레슨을 찾을 수 없습니다."}</p>
      </div>
    );
  }

  const report = lesson.report;

  return (
    <div className="mx-auto max-w-2xl space-y-4">
      <div className="rounded-2xl border border-gray-100 bg-gray-50 p-4 text-center text-sm text-gray-600">
        🎾 <strong>{lesson.title ?? "레슨"}</strong>의 AI 오답노트예요. 코치님의 확인을 부탁드려요.
      </div>

      {report?.card1_problem && (
        <section className="rounded-2xl border-2 border-red-200 bg-red-50 p-5 shadow-sm">
          <h3 className="text-base font-bold text-red-700">고질병</h3>
          <p className="mt-2 leading-relaxed text-gray-800">{report.card1_problem}</p>
        </section>
      )}

      {report?.card2_cueing && (
        <section className="rounded-2xl border-2 border-blue-200 bg-blue-50 p-5 shadow-sm">
          <h3 className="text-base font-bold text-blue-700">코치 큐잉</h3>
          <p className="mt-2 leading-relaxed text-gray-800">{report.card2_cueing}</p>
        </section>
      )}

      {report?.card3_action && (
        <section className="rounded-2xl border-2 border-brand-200 bg-brand-50 p-5 shadow-sm">
          <h3 className="text-base font-bold text-brand-700">액션 플랜</h3>
          <p className="mt-2 leading-relaxed text-gray-800">{report.card3_action}</p>
        </section>
      )}

      {report?.timestamps && report.timestamps.length > 0 && (
        <section className="rounded-2xl border border-gray-200 bg-white p-4 shadow-sm">
          <h3 className="text-sm font-bold text-gray-900">코칭 구간</h3>
          <ul className="mt-2 space-y-1.5">
            {report.timestamps.map((ts, i) => (
              <li key={`${ts.sec}-${i}`} className="flex items-baseline gap-2 text-sm text-gray-700">
                <span className="font-mono text-xs text-gray-400">{formatTime(ts.sec)}</span>
                <span>{ts.label}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* 09문서 #5: 코치 검증 + 한 줄 코멘트 */}
      <section className="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm">
        {submitted ? (
          <p className="text-sm text-gray-700">
            {submitted === "confirmed"
              ? "✅ 의도가 맞다고 확인해 주셨어요. 감사합니다!"
              : "📝 보완 의견을 전달해 주셔서 감사합니다."}
          </p>
        ) : (
          <>
            <h3 className="text-sm font-bold text-gray-900">
              코치님, 이 오답노트가 정확한가요?
            </h3>
            <textarea
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              maxLength={300}
              rows={2}
              placeholder="보완할 점이 있다면 한 줄로 남겨주세요 (선택)"
              className="mt-3 w-full resize-none rounded-xl border border-gray-200 p-3 text-sm text-gray-800 outline-none focus:border-brand-400"
            />
            <div className="mt-3 flex gap-2">
              <button
                type="button"
                onClick={() => handleSubmit("confirmed")}
                disabled={submitting}
                className="flex-1 rounded-xl bg-brand-500 py-2.5 text-sm font-semibold text-white hover:bg-brand-600 disabled:opacity-60"
              >
                제 의도 맞아요
              </button>
              <button
                type="button"
                onClick={() => handleSubmit("needs_fix")}
                disabled={submitting}
                className="flex-1 rounded-xl border border-gray-200 bg-white py-2.5 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-60"
              >
                보완할게요
              </button>
            </div>
          </>
        )}
      </section>
    </div>
  );
}
