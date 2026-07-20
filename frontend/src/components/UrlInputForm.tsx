"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { analyzeLesson, analyzeLessonUpload, getLesson } from "@/lib/api";
import { getSupabaseClient } from "@/lib/supabase";
import { ApiCallError } from "@/types/lesson";
import { LoadingSpinner } from "@/components/ui/LoadingSpinner";
import { useToast } from "@/components/ui/Toast";
import { useAnalysisTracker } from "@/lib/AnalysisTracker";
import {
  extractAudioFromVideo,
  probeVideoDuration,
  sha256Hex,
} from "@/lib/extractAudio";

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

/**
 * 15문서 2-D: 촬영 가이드.
 *
 * 골든셋 사람 검토(2026-07-19)로 확인된 사실 — quote 정밀도는 13~20%로
 * 낮지만 moment 정밀도는 100%(사람 귀로는 다 들림). 즉 오디오가 한계선
 * *근처*라는 뜻이라, 마이크가 조금만 가까워져도 STT 결과가 크게 달라질
 * 가능성이 크다. 새 영상 등록 전에 이 사실을 안내해 준수 유인을 만든다.
 */
function RecordingGuide() {
  return (
    <details className="mx-auto mt-4 max-w-2xl rounded-xl border border-gray-100 bg-gray-50 open:bg-white">
      <summary className="cursor-pointer select-none px-4 py-2.5 text-xs font-medium text-gray-500 hover:text-gray-700">
        🎙️ 더 정확한 오답노트를 원한다면? 촬영 팁 보기
      </summary>
      <div className="space-y-1.5 px-4 pb-3 pt-1 text-xs leading-relaxed text-gray-600">
        <p>
          AI는 코치님이 말씀하신 <strong>순간</strong>은 거의 정확히 찾아내지만,
          목소리가 멀면 <strong>정확한 문장</strong>까지는 못 알아듣는 경우가 있어요.
        </p>
        <ul className="list-disc space-y-1 pl-4">
          <li>촬영할 때 폰을 코치님 쪽 펜스에 최대한 가깝게 두세요.</li>
          <li>가능하면 네트 근처에서 촬영하면 목소리가 더 잘 들려요.</li>
          <li>바람이 심한 날은 마이크가 바람 소리를 먼저 잡을 수 있어요 — 마이크 방향을 신경 써주세요.</li>
        </ul>
      </div>
    </details>
  );
}

type InputMode = "youtube" | "upload";
type UploadPhase = "idle" | "extracting" | "uploading";

export function UrlInputForm({ onAnalyzed }: UrlInputFormProps) {
  const [mode, setMode] = useState<InputMode>("youtube");
  const [url, setUrl] = useState("");
  const [analyzeCourt, setAnalyzeCourt] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [messageIndex, setMessageIndex] = useState(0);
  // 파일 업로드 상태 머신
  const [uploadPhase, setUploadPhase] = useState<UploadPhase>("idle");
  const [uploadMsg, setUploadMsg] = useState("");
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

  const handleFile = useCallback(
    async (file: File) => {
      if (isLoading) return;
      setIsLoading(true);
      setUploadPhase("extracting");
      setUploadMsg("영상 길이 확인 중...");

      try {
        const durationSec = await probeVideoDuration(file);

        const extracted = await extractAudioFromVideo(file, (p) => {
          setUploadPhase("extracting");
          setUploadMsg(
            p.phase === "loading-ffmpeg"
              ? "오디오 추출 도구 준비 중..."
              : "영상에서 소리만 추출하는 중...",
          );
        });

        setUploadPhase("uploading");
        setUploadMsg("분석 서버로 소리만 전송 중...");
        const fileHash = await sha256Hex(extracted.data);
        const audioBlob = new Blob([extracted.data.buffer as ArrayBuffer], { type: "audio/mp4" });

        const res = await analyzeLessonUpload({
          audio: audioBlob,
          title: file.name.replace(/\.[^/.]+$/, ""),
          duration_sec: Math.round(durationSec ?? 0),
          file_hash: fileHash,
        });

        setIsLoading(false);
        setUploadPhase("idle");
        tracker.track(res.lesson_id, null);
        onAnalyzed?.(res.lesson_id);
        router.push(`/lessons/${res.lesson_id}`);
      } catch (err) {
        setIsLoading(false);
        setUploadPhase("idle");
        setUploadMsg("");
        if (err instanceof ApiCallError) {
          if (err.code === "LESSON_ALREADY_EXISTS") {
            const existingId = err.details?.existing_lesson_id as string | undefined;
            if (existingId) {
              toast.show("이미 분석된 영상으로 이동합니다.", "info");
              router.push(`/lessons/${existingId}`);
              return;
            }
          }
          toast.show(err.message, "error");
        } else {
          // eslint-disable-next-line no-console -- 폰 원격 디버깅 시 원인 파악용
          console.error("영상 업로드 처리 실패:", err);
          toast.show(
            "영상 처리 중 문제가 발생했어요. 다른 영상이나 유튜브 링크를 이용해주세요.",
            "error",
          );
        }
      }
    },
    [isLoading, onAnalyzed, router, toast, tracker],
  );

  return (
    <div className="w-full max-w-2xl mx-auto">
      {/* 17문서 U-1: 입력 방식 탭 */}
      <div className="mb-4 flex justify-center">
        <div className="inline-flex rounded-xl bg-gray-100 p-1">
          {(["youtube", "upload"] as const).map((m) => (
            <button
              key={m}
              type="button"
              onClick={() => !isLoading && setMode(m)}
              disabled={isLoading}
              className={[
                "rounded-lg px-4 py-2 text-sm font-semibold transition-colors disabled:cursor-not-allowed",
                mode === m ? "bg-white text-brand-600 shadow-sm" : "text-gray-500 hover:text-gray-700",
              ].join(" ")}
            >
              {m === "youtube" ? "유튜브 링크" : "영상 파일"}
            </button>
          ))}
        </div>
      </div>

      {mode === "youtube" ? (
        <YoutubeTab
          url={url}
          setUrl={setUrl}
          isLoading={isLoading}
          analyzeCourt={analyzeCourt}
          setAnalyzeCourt={setAnalyzeCourt}
          onSubmit={handleSubmit}
          messageIndex={messageIndex}
        />
      ) : (
        <UploadTab
          isLoading={isLoading}
          uploadPhase={uploadPhase}
          uploadMsg={uploadMsg}
          onFile={handleFile}
        />
      )}

      {!isLoading && <RecordingGuide />}
    </div>
  );
}

interface YoutubeTabProps {
  url: string;
  setUrl: (v: string) => void;
  isLoading: boolean;
  analyzeCourt: boolean;
  setAnalyzeCourt: (v: boolean) => void;
  onSubmit: (e: React.FormEvent) => void;
  messageIndex: number;
}

function YoutubeTab({
  url,
  setUrl,
  isLoading,
  analyzeCourt,
  setAnalyzeCourt,
  onSubmit,
  messageIndex,
}: YoutubeTabProps) {
  return (
    <form onSubmit={onSubmit}>
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

interface UploadTabProps {
  isLoading: boolean;
  uploadPhase: UploadPhase;
  uploadMsg: string;
  onFile: (file: File) => void;
}

function UploadTab({ isLoading, uploadPhase, uploadMsg, onFile }: UploadTabProps) {
  return (
    <div>
      <label
        className={[
          "flex w-full cursor-pointer flex-col items-center justify-center gap-2 rounded-2xl border-2 border-dashed p-8 text-center transition-colors",
          isLoading
            ? "border-gray-200 bg-gray-50 cursor-not-allowed"
            : "border-gray-300 bg-white hover:border-brand-400 hover:bg-brand-50/30",
        ].join(" ")}
      >
        <span className="text-3xl" aria-hidden>🎾</span>
        <span className="text-base font-semibold text-gray-800">
          레슨 영상 파일 선택
        </span>
        <span className="text-sm text-gray-500">
          영상을 고르면 브라우저에서 소리만 추출해 분석해요
        </span>
        <input
          type="file"
          accept="video/*"
          disabled={isLoading}
          className="hidden"
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) onFile(file);
            // 같은 파일 재선택 허용
            e.target.value = "";
          }}
        />
      </label>

      {/* 2-4(A) 안내 문구 고정 노출 */}
      <div className="mt-3 space-y-1 text-center text-xs text-gray-500">
        <p>🔒 영상은 서버로 전송되지 않고, 소리만 분석에 사용돼요.</p>
        <p>👥 코치님·친구와 영상까지 공유하려면 유튜브 링크로 분석하세요.</p>
      </div>

      {isLoading && (
        <div className="mt-4 flex items-center justify-center gap-3 text-sm text-gray-600 animate-fade-in">
          <LoadingSpinner size="sm" />
          <span aria-live="polite">
            {uploadMsg ||
              (uploadPhase === "extracting"
                ? "영상에서 소리만 추출하는 중..."
                : "분석 서버로 전송 중...")}
          </span>
        </div>
      )}
    </div>
  );
}
