"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { analyzeLesson, getLesson } from "@/lib/api";
import { getSupabaseClient } from "@/lib/supabase";
import { ApiCallError } from "@/types/lesson";
import { LoadingSpinner } from "@/components/ui/LoadingSpinner";
import { useToast } from "@/components/ui/Toast";
import { useAnalysisTracker } from "@/lib/AnalysisTracker";

const ANALYSIS_MESSAGES = [
  "AI가 레슨을 분석 중입니다...",
  "코치님의 음성을 텍스트로 변환하고 있어요",
  "고질병 패턴을 찾고 있어요",
  "오답노트 카드를 정리하는 중...",
];

const POLL_INTERVAL_MS = 3000;
const POLL_MAX_DURATION_MS = 60_000;

interface UrlInputFormProps {
  onAnalyzed?: (lessonId: string) => void;
}

export function UrlInputForm({ onAnalyzed }: UrlInputFormProps) {
  const [url, setUrl] = useState("");
  const [analyzeCourt, setAnalyzeCourt] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [messageIndex, setMessageIndex] = useState(0);
  const router = useRouter();
  const toast = useToast();
  const cleanupRef = useRef<(() => void) | null>(null);
  const tracker = useAnalysisTracker();

  // 로딩 메시지 회전
  useEffect(() => {
    if (!isLoading) return;
    const t = setInterval(() => {
      setMessageIndex((i) => (i + 1) % ANALYSIS_MESSAGES.length);
    }, 2500);
    return () => clearInterval(t);
  }, [isLoading]);

  // 언마운트 시 구독/폴링 정리
  useEffect(() => {
    return () => {
      cleanupRef.current?.();
    };
  }, []);

  const goToLesson = useCallback(
    (lessonId: string) => {
      cleanupRef.current?.();
      cleanupRef.current = null;
      setIsLoading(false);
      onAnalyzed?.(lessonId);
      router.push(`/lessons/${lessonId}`);
    },
    [onAnalyzed, router],
  );

  /**
   * Supabase Realtime 구독 시도. 실패하거나 채널이 막힌 경우 폴링 폴백.
   */
  const watchLesson = useCallback(
    (lessonId: string) => {
      const supabase = getSupabaseClient();
      let resolved = false;

      const finish = () => {
        if (resolved) return;
        resolved = true;
        goToLesson(lessonId);
      };

      // 1) Realtime 구독 — DONE/FAILED 상태에서만 화면 전환
      const channel = supabase
        .channel(`lesson_reports:${lessonId}`)
        .on(
          "postgres_changes",
          {
            event: "UPDATE",
            schema: "public",
            table: "lesson_reports",
            filter: `lesson_id=eq.${lessonId}`,
          },
          (payload) => {
            const s = (payload.new as { processing_status?: string })
              ?.processing_status;
            if (s === "DONE" || s === "FAILED") finish();
          },
        )
        .subscribe();

      // 2) 폴링 폴백 (Realtime 미동작 대비)
      const startedAt = Date.now();
      const pollTimer = setInterval(async () => {
        if (resolved) return;
        try {
          const detail = await getLesson(lessonId);
          if (
            detail.processing_status === "DONE" ||
            detail.processing_status === "FAILED"
          ) {
            finish();
            return;
          }
        } catch {
          // 일시 오류는 무시하고 다음 폴링에서 재시도
        }
        if (Date.now() - startedAt > POLL_MAX_DURATION_MS) {
          // 시간 초과 — 일단 상세 페이지로 이동시켜 서버 상태 노출
          finish();
        }
      }, POLL_INTERVAL_MS);

      cleanupRef.current = () => {
        clearInterval(pollTimer);
        supabase.removeChannel(channel);
      };
    },
    [goToLesson],
  );

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = url.trim();
    if (!trimmed || isLoading) return;

    setIsLoading(true);
    setMessageIndex(0);
    try {
      const res = await analyzeLesson({ youtube_url: trimmed, analyze_court: analyzeCourt });
      setIsLoading(false);

      if (res.processing_status === "DONE") {
        // 동기 처리 완료 (캐시 등)
        onAnalyzed?.(res.lesson_id);
        router.push(`/lessons/${res.lesson_id}`);
        return;
      }

      // 비동기 — 글로벌 트래커가 완료까지 추적
      tracker.track(res.lesson_id, null);
      onAnalyzed?.(res.lesson_id);
      router.push(`/lessons/${res.lesson_id}`);
    } catch (err) {
      setIsLoading(false);
      if (err instanceof ApiCallError) {
        if (err.code === "LESSON_ALREADY_EXISTS") {
          const existingId = err.details?.existing_lesson_id as
            | string
            | undefined;
          if (existingId) {
            toast.show("이미 분석된 레슨으로 이동합니다.", "info");
            router.push(`/lessons/${existingId}`);
            return;
          }
        }
        toast.show(err.message, "error");
      } else {
        toast.show("분석 요청 중 오류가 발생했습니다.", "error");
      }
    }
  };

  return (
    <form onSubmit={handleSubmit} className="w-full max-w-2xl mx-auto">
      <div className="relative">
        <input
          type="url"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="오늘의 레슨 복기를 시작하세요 (YouTube 링크)"
          aria-label="YouTube 레슨 영상 URL"
          disabled={isLoading}
          required
          className="w-full px-5 py-4 sm:px-6 sm:py-5 text-base sm:text-lg rounded-2xl border-2 border-gray-200 bg-white focus:border-brand-500 outline-none pr-28 sm:pr-36 transition-colors disabled:bg-gray-50"
        />
        <button
          type="submit"
          disabled={isLoading || !url.trim()}
          className="absolute right-2 top-2 bottom-2 px-4 sm:px-6 bg-brand-500 hover:bg-brand-600 text-white text-sm sm:text-base font-bold rounded-xl disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center justify-center min-w-[88px]"
        >
          {isLoading ? (
            <LoadingSpinner size="sm" />
          ) : (
            <span>복기하기</span>
          )}
        </button>
      </div>

      <div className="mt-3 flex items-center justify-center gap-2">
        <label className="flex items-center gap-2 cursor-pointer select-none text-sm text-gray-500">
          <input
            type="checkbox"
            checked={analyzeCourt}
            onChange={(e) => setAnalyzeCourt(e.target.checked)}
            disabled={isLoading}
            className="h-4 w-4 rounded border-gray-300 text-brand-500 focus:ring-brand-500"
          />
          <span>코트 전술 다이어그램 분석 포함</span>
          <span className="text-xs text-gray-400">(+5~7분)</span>
        </label>
      </div>

      {isLoading && (
        <div className="mt-4 flex items-center justify-center gap-3 text-sm text-gray-600 animate-fade-in">
          <span className="inline-block h-2 w-2 rounded-full bg-brand-500 animate-pulse-slow" />
          <span aria-live="polite">{ANALYSIS_MESSAGES[messageIndex]}</span>
        </div>
      )}
    </form>
  );
}
