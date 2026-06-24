"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { ReportView } from "@/components/ReportView";
import { LoadingSpinner } from "@/components/ui/LoadingSpinner";
import { useToast } from "@/components/ui/Toast";
import { deleteLesson, getLesson } from "@/lib/api";
import { getSupabaseClient } from "@/lib/supabase";
import { ApiCallError, type LessonDetail } from "@/types/lesson";

function suggestTitle(lesson: LessonDetail): string {
  const types = lesson.lesson_type?.join(", ") ?? "";
  const keywords = lesson.report?.keywords?.slice(0, 2).join(", ") ?? "";
  const problem = lesson.report?.card1_problem
    ? lesson.report.card1_problem.match(/^[^.!?\n]{6,}[.!?]?/)?.[0]?.trim()
    : null;
  if (types && keywords) return `${types} 레슨 — ${keywords}`;
  if (types && problem) return `${types} — ${problem}`;
  if (types) return `${types} 레슨`;
  if (keywords) return `레슨 — ${keywords}`;
  return lesson.title ?? "레슨 오답노트";
}

const POLL_INTERVAL_MS = 4000;

export default function LessonDetailPage() {
  const params = useParams<{ id: string }>();
  const lessonId = params?.id;
  const router = useRouter();
  const searchParams = typeof window !== "undefined"
    ? new URLSearchParams(window.location.search)
    : null;
  const startSec = searchParams ? Number(searchParams.get("t") ?? 0) : 0;
  const toast = useToast();

  const [lesson, setLesson] = useState<LessonDetail | null>(null);
  const [error, setError] = useState<{ status?: number; message: string } | null>(null);
  const [isInitialLoading, setIsInitialLoading] = useState(true);
  const [isDeleting, setIsDeleting] = useState(false);
  const [isEditingTitle, setIsEditingTitle] = useState(false);
  const [editTitle, setEditTitle] = useState("");
  const [isSavingTitle, setIsSavingTitle] = useState(false);
  const titleInputRef = useRef<HTMLInputElement>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchLesson = useCallback(
    async (id: string): Promise<LessonDetail | null> => {
      try {
        const detail = await getLesson(id);
        setLesson(detail);
        setError(null);
        return detail;
      } catch (err) {
        if (err instanceof ApiCallError) {
          setError({ status: err.status, message: err.message });
        } else {
          setError({
            message:
              err instanceof Error
                ? err.message
                : "레슨을 불러오지 못했습니다.",
          });
        }
        return null;
      }
    },
    [],
  );

  // 초기 로드 + 진행 중일 때 폴링
  useEffect(() => {
    if (!lessonId) return;
    let cancelled = false;

    const stopPolling = () => {
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };

    const tick = async () => {
      const detail = await fetchLesson(lessonId);
      if (cancelled) return;
      if (
        detail &&
        (detail.processing_status === "DONE" ||
          detail.processing_status === "FAILED")
      ) {
        stopPolling();
      }
    };

    setIsInitialLoading(true);
    tick().finally(() => {
      if (!cancelled) setIsInitialLoading(false);
    });

    // 폴링 시작 (PENDING/PROCESSING 일 때만 실제로 의미 있음. 매 tick 에서 종료 체크)
    pollRef.current = setInterval(tick, POLL_INTERVAL_MS);

    return () => {
      cancelled = true;
      stopPolling();
    };
  }, [lessonId, fetchLesson]);

  // Realtime 구독 (lesson_reports 변경 감지 시 즉시 재조회)
  useEffect(() => {
    if (!lessonId) return;
    const supabase = getSupabaseClient();
    const channel = supabase
      .channel(`lesson_detail:${lessonId}`)
      .on(
        "postgres_changes",
        {
          event: "*",
          schema: "public",
          table: "lesson_reports",
          filter: `lesson_id=eq.${lessonId}`,
        },
        () => {
          fetchLesson(lessonId);
        },
      )
      .on(
        "postgres_changes",
        {
          event: "UPDATE",
          schema: "public",
          table: "lessons",
          filter: `id=eq.${lessonId}`,
        },
        () => {
          fetchLesson(lessonId);
        },
      )
      .subscribe();
    return () => {
      supabase.removeChannel(channel);
    };
  }, [lessonId, fetchLesson]);

  const handleStartEditTitle = () => {
    if (!lesson) return;
    setEditTitle(lesson.title?.trim() || "");
    setIsEditingTitle(true);
    setTimeout(() => titleInputRef.current?.select(), 0);
  };

  const handleSuggestTitle = () => {
    if (!lesson) return;
    setEditTitle(suggestTitle(lesson));
    setIsEditingTitle(true);
    setTimeout(() => titleInputRef.current?.select(), 0);
  };

  const handleSaveTitle = async () => {
    if (!lesson || isSavingTitle) return;
    const newTitle = editTitle.trim();
    if (!newTitle || newTitle === lesson.title) {
      setIsEditingTitle(false);
      return;
    }
    setIsSavingTitle(true);
    try {
      const supabase = getSupabaseClient();
      await supabase.from("lessons").update({ title: newTitle }).eq("id", lesson.lesson_id);
      setLesson((prev) => prev ? { ...prev, title: newTitle } : prev);
      toast.show("제목을 저장했습니다.", "success");
      setIsEditingTitle(false);
    } catch {
      toast.show("저장에 실패했습니다.", "error");
    } finally {
      setIsSavingTitle(false);
    }
  };

  const handleDelete = async () => {
    if (!lesson || isDeleting) return;
    const ok = window.confirm("이 레슨을 삭제하시겠어요? 복구할 수 없습니다.");
    if (!ok) return;
    setIsDeleting(true);
    try {
      await deleteLesson(lesson.lesson_id);
      toast.show("레슨을 삭제했습니다.", "success");
      router.push("/");
    } catch (err) {
      const msg =
        err instanceof ApiCallError
          ? err.message
          : "삭제 중 오류가 발생했습니다.";
      toast.show(msg, "error");
      setIsDeleting(false);
    }
  };

  if (!lessonId) return null;

  if (isInitialLoading) {
    return (
      <div className="flex min-h-[40vh] items-center justify-center text-gray-500">
        <LoadingSpinner size="lg" label="레슨을 불러오는 중..." />
      </div>
    );
  }

  if (error) {
    const isNotFound = error.status === 404;
    return (
      <div className="mx-auto max-w-md rounded-2xl border border-gray-200 bg-white p-8 text-center shadow-sm">
        <h2 className="text-lg font-bold text-gray-900">
          {isNotFound ? "레슨을 찾을 수 없어요" : "오류가 발생했습니다"}
        </h2>
        <p className="mt-2 text-sm text-gray-600">{error.message}</p>
        <Link
          href="/"
          className="mt-5 inline-flex items-center justify-center rounded-xl bg-brand-500 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-600"
        >
          대시보드로 돌아가기
        </Link>
      </div>
    );
  }

  if (!lesson) return null;

  const status = lesson.processing_status;
  const title = lesson.title?.trim() || "레슨 오답노트";

  return (
    <div className="space-y-6">
      {/* 헤더 */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <Link
            href="/"
            className="inline-flex items-center gap-1 text-xs text-gray-500 hover:text-gray-700"
          >
            <svg
              xmlns="http://www.w3.org/2000/svg"
              viewBox="0 0 20 20"
              fill="currentColor"
              className="h-3.5 w-3.5"
              aria-hidden
            >
              <path
                fillRule="evenodd"
                d="M12.78 5.22a.75.75 0 0 1 0 1.06L8.06 11l4.72 4.72a.75.75 0 1 1-1.06 1.06l-5.25-5.25a.75.75 0 0 1 0-1.06l5.25-5.25a.75.75 0 0 1 1.06 0Z"
                clipRule="evenodd"
              />
            </svg>
            대시보드
          </Link>
          {isEditingTitle ? (
            <div className="mt-1 flex items-center gap-2">
              <input
                ref={titleInputRef}
                type="text"
                value={editTitle}
                onChange={(e) => setEditTitle(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") handleSaveTitle(); if (e.key === "Escape") setIsEditingTitle(false); }}
                className="w-full rounded-lg border border-brand-400 px-3 py-1.5 text-lg font-bold text-gray-900 outline-none ring-2 ring-brand-200 sm:text-xl"
                autoFocus
              />
              <button type="button" onClick={handleSaveTitle} disabled={isSavingTitle}
                className="shrink-0 rounded-lg bg-brand-500 px-3 py-1.5 text-sm font-semibold text-white hover:bg-brand-600 disabled:opacity-50">
                {isSavingTitle ? "저장 중..." : "저장"}
              </button>
              <button type="button" onClick={() => setIsEditingTitle(false)}
                className="shrink-0 rounded-lg border border-gray-200 px-3 py-1.5 text-sm text-gray-500 hover:bg-gray-50">
                취소
              </button>
            </div>
          ) : (
            <div className="mt-1 flex items-center gap-2">
              <h1 className="truncate text-xl font-bold text-gray-900 sm:text-2xl">{title}</h1>
              <button type="button" onClick={handleStartEditTitle}
                className="shrink-0 rounded-md p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-600"
                title="제목 편집">
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="h-4 w-4" aria-hidden>
                  <path d="M5.433 13.917l1.262-3.155A4 4 0 0 1 7.58 9.42l6.92-6.918a2.121 2.121 0 0 1 3 3l-6.92 6.918c-.383.383-.84.685-1.343.886l-3.154 1.262a.5.5 0 0 1-.65-.65Z" />
                  <path d="M3.5 5.75c0-.69.56-1.25 1.25-1.25H10A.75.75 0 0 0 10 3H4.75A2.75 2.75 0 0 0 2 5.75v9.5A2.75 2.75 0 0 0 4.75 18h9.5A2.75 2.75 0 0 0 17 15.25V10a.75.75 0 0 0-1.5 0v5.25c0 .69-.56 1.25-1.25 1.25h-9.5c-.69 0-1.25-.56-1.25-1.25v-9.5Z" />
                </svg>
              </button>
            </div>
          )}
          <div className="mt-1 flex items-center gap-2">
            <p className="text-xs text-gray-500">
              {lesson.lesson_date ?? new Date(lesson.created_at).toLocaleDateString()}
            </p>
            {!isEditingTitle && lesson.processing_status === "DONE" && (
              <button type="button" onClick={handleSuggestTitle}
                className="inline-flex items-center gap-1 rounded-full bg-brand-50 px-2.5 py-0.5 text-xs font-medium text-brand-700 hover:bg-brand-100">
                ✨ AI 이름 제안
              </button>
            )}
          </div>
        </div>

        <button
          type="button"
          onClick={handleDelete}
          disabled={isDeleting}
          className="inline-flex items-center gap-1.5 rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-sm font-medium text-gray-600 transition hover:border-red-200 hover:bg-red-50 hover:text-red-600 disabled:opacity-50"
        >
          {isDeleting ? <LoadingSpinner size="sm" /> : "삭제"}
        </button>
      </div>

      {/* 상태별 분기 */}
      {status === "PENDING" || status === "PROCESSING" ? (
        <ProcessingPlaceholder
          step={lesson.report?.progress_step ?? (lesson.processing_status === "PROCESSING" ? 1 : 0)}
          message={lesson.report?.progress_message}
        />
      ) : status === "FAILED" ? (
        <FailedPlaceholder lesson={lesson} />
      ) : (
        <ReportView lesson={lesson} startSec={startSec} />
      )}
    </div>
  );
}

function ProcessingPlaceholder({
  step = 0,
  message,
}: {
  step?: number;
  message?: string | null;
}) {
  const TOTAL = 3;
  const current = Math.min(Math.max(step, 1), TOTAL);
  const FALLBACK: Record<number, string> = {
    0: "곧 분석이 시작됩니다...",
    1: "🎵 오디오 다운로드 중... (1/3)",
    2: "🔍 영상 분석 중... (2/3)",
    3: "📝 오답노트 정리 중... (3/3)",
  };
  const display = message ?? FALLBACK[step] ?? "분석 중...";

  return (
    <div className="rounded-3xl border border-gray-200 bg-white p-8 sm:p-12 text-center shadow-sm">
      {/* 단계 인디케이터 */}
      <div className="mx-auto mb-6 flex items-center justify-center gap-2">
        {Array.from({ length: TOTAL }).map((_, i) => {
          const idx = i + 1;
          const done = idx < current;
          const active = idx === current;
          return (
            <div key={idx} className="flex items-center gap-2">
              <span
                className={[
                  "h-3 w-3 rounded-full transition-all duration-500",
                  done ? "bg-green-500" :
                  active ? "bg-green-500 animate-pulse scale-125" :
                  "bg-gray-200",
                ].join(" ")}
              />
              {i < TOTAL - 1 && (
                <span className={`h-0.5 w-10 transition-all duration-500 ${done ? "bg-green-500" : "bg-gray-200"}`} />
              )}
            </div>
          );
        })}
      </div>

      <h2 className="text-lg sm:text-xl font-bold text-gray-900">
        AI가 레슨을 분석 중입니다
      </h2>
      <p className="mt-2 text-sm text-gray-700 min-h-[1.5rem]" aria-live="polite">
        {display}
      </p>
      <p className="mt-2 text-xs text-gray-400">
        평균 2~3분 소요됩니다. 다른 페이지로 이동하셔도 분석은 계속 진행돼요.
      </p>

      <Link
        href="/"
        className="mt-5 inline-flex items-center gap-1.5 rounded-xl border border-gray-200 bg-gray-50 px-4 py-2 text-sm font-medium text-gray-600 hover:bg-gray-100 transition"
      >
        ← 대시보드에서 기다리기
      </Link>
    </div>
  );
}

function FailedPlaceholder({ lesson }: { lesson: LessonDetail }) {
  const [retrying, setRetrying] = React.useState(false);
  const router = useRouter();

  const message =
    lesson.report?.error_message ??
    "레슨 분석에 실패했습니다. 자막이 없거나 영상이 너무 길 수 있어요.";

  const handleRetry = async () => {
    setRetrying(true);
    try {
      const res = await fetch(
        `${process.env.NEXT_PUBLIC_API_BASE_URL}/api/v1/lessons/${lesson.lesson_id}/retry`,
        { method: "POST" }
      );
      if (res.ok) {
        router.refresh();
      }
    } catch {
      setRetrying(false);
    }
  };

  return (
    <div className="rounded-3xl border-2 border-red-200 bg-red-50 p-8 text-center sm:p-12">
      <div className="mx-auto mb-4 inline-flex h-12 w-12 items-center justify-center rounded-2xl bg-red-100 text-red-600">
        <svg
          xmlns="http://www.w3.org/2000/svg"
          viewBox="0 0 24 24"
          fill="currentColor"
          className="h-6 w-6"
          aria-hidden
        >
          <path
            fillRule="evenodd"
            d="M12 2a10 10 0 1 0 10 10A10 10 0 0 0 12 2Zm0 5a1 1 0 0 1 1 1v5a1 1 0 0 1-2 0V8a1 1 0 0 1 1-1Zm0 10a1.25 1.25 0 1 1 0-2.5 1.25 1.25 0 0 1 0 2.5Z"
            clipRule="evenodd"
          />
        </svg>
      </div>
      <h2 className="text-lg font-bold text-red-700 sm:text-xl">분석 실패</h2>
      <p className="mx-auto mt-2 max-w-md text-sm text-red-700/80">{message}</p>
      <div className="mt-5 flex items-center justify-center gap-3">
        <button
          type="button"
          onClick={handleRetry}
          disabled={retrying}
          className="inline-flex items-center justify-center gap-1.5 rounded-xl bg-red-600 px-4 py-2 text-sm font-semibold text-white hover:bg-red-700 disabled:opacity-50"
        >
          {retrying ? "재시도 중..." : "다시 분석하기"}
        </button>
        <Link
          href="/"
          className="inline-flex items-center justify-center rounded-xl border border-red-200 bg-white px-4 py-2 text-sm font-medium text-red-600 hover:bg-red-50"
        >
          대시보드로
        </Link>
      </div>
    </div>
  );
}
