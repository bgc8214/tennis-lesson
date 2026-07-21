"use client";

import {
  createContext, useCallback, useContext,
  useEffect, useRef, useState,
} from "react";
import { getSupabaseClient } from "@/lib/supabase";
import { getLesson, markLessonStuck } from "@/lib/api";
import { useToast } from "@/components/ui/Toast";
import type { ProcessingStatus } from "@/types/lesson";

// 백엔드 ANALYZE_TIMEOUT_SEC(기본 600초)와 맞춤. lessons/[id] 페이지와 동일 기준.
const STUCK_TIMEOUT_MS = 600_000;

interface ActiveAnalysis {
  lessonId: string;
  title: string | null;
  step: number;
  message: string | null;
  status: ProcessingStatus;
}

interface TrackerCtx {
  active: ActiveAnalysis[];
  track: (lessonId: string, title?: string | null) => void;
  dismiss: (lessonId: string) => void;
}

const Ctx = createContext<TrackerCtx | null>(null);

export function AnalysisTrackerProvider({ children }: { children: React.ReactNode }) {
  const [active, setActive] = useState<ActiveAnalysis[]>([]);
  const toast = useToast();
  const subsRef = useRef<Map<string, { channel: ReturnType<ReturnType<typeof getSupabaseClient>["channel"]>; timer: ReturnType<typeof setInterval> }>>(new Map());

  const dismiss = useCallback((lessonId: string) => {
    const sub = subsRef.current.get(lessonId);
    if (sub) {
      clearInterval(sub.timer);
      getSupabaseClient().removeChannel(sub.channel);
      subsRef.current.delete(lessonId);
    }
    setActive((prev) => prev.filter((a) => a.lessonId !== lessonId));
  }, []);

  const track = useCallback((lessonId: string, title?: string | null) => {
    if (subsRef.current.has(lessonId)) return;

    setActive((prev) => [
      ...prev,
      { lessonId, title: title ?? null, step: 0, message: null, status: "PENDING" },
    ]);

    toast.show("분석이 시작됐어요. 다른 작업을 하셔도 완료되면 알려드릴게요.", "info");

    const sb = getSupabaseClient();

    const tick = async () => {
      try {
        const detail = await getLesson(lessonId);
        const step = detail.report?.progress_step ?? 0;
        const message = detail.report?.progress_message ?? null;

        setActive((prev) =>
          prev.map((a) =>
            a.lessonId === lessonId
              ? { ...a, title: detail.title ?? a.title, status: detail.processing_status, step, message }
              : a
          )
        );

        if (detail.processing_status === "DONE") {
          toast.show(`"${detail.title ?? "레슨"}" 분석이 완료됐어요!`, "success");
          dismiss(lessonId);
        } else if (detail.processing_status === "FAILED") {
          toast.show(`"${detail.title ?? "레슨"}" 분석에 실패했습니다.`, "error");
          dismiss(lessonId);
        } else {
          const elapsedMs = Date.now() - new Date(detail.updated_at).getTime();
          if (elapsedMs > STUCK_TIMEOUT_MS) {
            try {
              const result = await markLessonStuck(lessonId);
              if (result.processing_status === "FAILED") {
                toast.show(`"${detail.title ?? "레슨"}" 분석에 실패했습니다.`, "error");
                dismiss(lessonId);
              }
            } catch {
              // 일시 오류 — 다음 tick에서 재시도
            }
          }
        }
      } catch {
        // 일시 오류 무시
      }
    };

    const channel = sb
      .channel(`tracker:${lessonId}`)
      .on(
        "postgres_changes",
        { event: "UPDATE", schema: "public", table: "lesson_reports", filter: `lesson_id=eq.${lessonId}` },
        () => { tick(); }
      )
      .subscribe();

    const timer = setInterval(tick, 5000);
    subsRef.current.set(lessonId, { channel, timer });
    tick();
  }, [toast, dismiss]);

  useEffect(() => {
    return () => {
      const sb = getSupabaseClient();
      subsRef.current.forEach(({ channel, timer }) => {
        clearInterval(timer);
        sb.removeChannel(channel);
      });
    };
  }, []);

  return (
    <Ctx.Provider value={{ active, track, dismiss }}>
      {children}
    </Ctx.Provider>
  );
}

export function useAnalysisTracker(): TrackerCtx {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("AnalysisTrackerProvider 안에서만 사용 가능");
  return ctx;
}
