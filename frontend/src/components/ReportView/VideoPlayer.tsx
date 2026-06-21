"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { LessonTimestamp } from "@/types/lesson";

interface VideoPlayerProps {
  youtubeUrl: string;
  youtubeVideoId: string;
  timestamps: LessonTimestamp[];
  startSec?: number;
}

interface YTPlayer {
  seekTo(seconds: number, allowSeekAhead?: boolean): void;
  playVideo(): void;
  destroy(): void;
}

interface YTNamespace {
  Player: new (
    el: HTMLElement | string,
    options: {
      videoId: string;
      playerVars?: Record<string, unknown>;
      events?: {
        onReady?: () => void;
        onStateChange?: (event: { data: number }) => void;
      };
    },
  ) => YTPlayer;
  ready?: (cb: () => void) => void;
}

declare global {
  interface Window {
    YT?: YTNamespace;
    onYouTubeIframeAPIReady?: () => void;
  }
}

let apiLoadingPromise: Promise<YTNamespace> | null = null;

function loadYouTubeIframeAPI(): Promise<YTNamespace> {
  if (typeof window === "undefined") {
    return Promise.reject(new Error("SSR에서는 호출할 수 없습니다."));
  }
  if (window.YT && window.YT.Player) return Promise.resolve(window.YT);
  if (apiLoadingPromise) return apiLoadingPromise;

  apiLoadingPromise = new Promise((resolve) => {
    const prev = window.onYouTubeIframeAPIReady;
    window.onYouTubeIframeAPIReady = () => {
      prev?.();
      if (window.YT) resolve(window.YT);
    };
    if (!document.querySelector('script[src*="youtube.com/iframe_api"]')) {
      const tag = document.createElement("script");
      tag.src = "https://www.youtube.com/iframe_api";
      tag.async = true;
      document.head.appendChild(tag);
    }
  });
  return apiLoadingPromise;
}

function formatTime(sec: number): string {
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

export function VideoPlayer({
  youtubeUrl,
  youtubeVideoId,
  timestamps,
  startSec = 0,
}: VideoPlayerProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const playerRef = useRef<YTPlayer | null>(null);
  const [isReady, setIsReady] = useState(false);
  const [activeIndex, setActiveIndex] = useState<number | null>(null);

  const sortedTimestamps = useMemo(
    () => [...timestamps].sort((a, b) => a.sec - b.sec),
    [timestamps],
  );

  useEffect(() => {
    let cancelled = false;
    let player: YTPlayer | null = null;

    loadYouTubeIframeAPI()
      .then((YT) => {
        if (cancelled || !containerRef.current) return;
        player = new YT.Player(containerRef.current, {
          videoId: youtubeVideoId,
          playerVars: {
            playsinline: 1,
            rel: 0,
            modestbranding: 1,
            ...(startSec > 0 ? { start: Math.floor(startSec) } : {}),
          },
          events: {
            onReady: () => {
              setIsReady(true);
              if (startSec > 0) {
                playerRef.current?.seekTo(startSec, true);
                playerRef.current?.playVideo();
              }
            },
          },
        });
        playerRef.current = player;
      })
      .catch(() => {
        // API 로드 실패 — fallback iframe 노출됨
      });

    return () => {
      cancelled = true;
      try {
        playerRef.current?.destroy();
      } catch {
        // ignore
      }
      playerRef.current = null;
    };
  }, [youtubeVideoId]);

  const seekTo = useCallback(
    (sec: number, idx: number) => {
      setActiveIndex(idx);
      const player = playerRef.current;
      if (player && isReady) {
        player.seekTo(sec, true);
        player.playVideo();
      } else {
        // 폴백: 새 탭으로 시간 지정 링크
        const url = `https://www.youtube.com/watch?v=${youtubeVideoId}&t=${Math.floor(sec)}s`;
        window.open(url, "_blank", "noopener,noreferrer");
      }
    },
    [isReady, youtubeVideoId],
  );

  const severityClass = (ts: LessonTimestamp): string => {
    if (ts.severity === "critical") {
      return "border-l-4 border-red-500 bg-red-50/40";
    }
    return "border-l-4 border-yellow-400 bg-yellow-50/40";
  };

  return (
    <div className="space-y-4">
      {/* 플레이어 */}
      <div className="relative w-full overflow-hidden rounded-2xl bg-black shadow-sm">
        <div className="aspect-video w-full">
          <div ref={containerRef} className="h-full w-full" />
        </div>
        {!isReady && (
          <div className="pointer-events-none absolute inset-0 flex items-center justify-center bg-black/60 text-sm text-white">
            플레이어를 준비하는 중...
          </div>
        )}
      </div>

      <a
        href={youtubeUrl}
        target="_blank"
        rel="noopener noreferrer"
        className="inline-flex items-center gap-1 text-xs text-gray-500 hover:text-gray-700"
      >
        YouTube에서 열기
        <svg
          xmlns="http://www.w3.org/2000/svg"
          viewBox="0 0 20 20"
          fill="currentColor"
          className="h-3 w-3"
          aria-hidden
        >
          <path
            fillRule="evenodd"
            d="M4.25 5.5a.75.75 0 0 0-.75.75v8.5c0 .414.336.75.75.75h8.5a.75.75 0 0 0 .75-.75v-4a.75.75 0 0 1 1.5 0v4A2.25 2.25 0 0 1 12.75 17h-8.5A2.25 2.25 0 0 1 2 14.75v-8.5A2.25 2.25 0 0 1 4.25 4h5a.75.75 0 0 1 0 1.5h-5Z"
            clipRule="evenodd"
          />
          <path
            fillRule="evenodd"
            d="M6.194 12.753a.75.75 0 0 0 1.06.053L16.5 4.44v2.81a.75.75 0 0 0 1.5 0v-4.5a.75.75 0 0 0-.75-.75h-4.5a.75.75 0 0 0 0 1.5h2.553l-9.056 8.194a.75.75 0 0 0-.053 1.06Z"
            clipRule="evenodd"
          />
        </svg>
      </a>

      {/* 타임스탬프 목록 */}
      {sortedTimestamps.length > 0 && (
        <div>
          <h3 className="mb-2 text-sm font-semibold text-gray-900">
            주요 장면 ({sortedTimestamps.length})
          </h3>
          <ul className="space-y-1.5">
            {sortedTimestamps.map((ts, i) => {
              const active = activeIndex === i;
              return (
                <li key={`${ts.sec}-${i}`}>
                  <button
                    type="button"
                    onClick={() => seekTo(ts.sec, i)}
                    className={`flex w-full items-start gap-3 rounded-lg px-3 py-2.5 text-left text-sm transition-colors hover:bg-gray-50 ${severityClass(ts)} ${active ? "ring-2 ring-brand-400" : ""}`}
                  >
                    <span className="mt-0.5 inline-flex min-w-[44px] justify-center rounded bg-gray-900/90 px-1.5 py-0.5 font-mono text-xs font-semibold text-white shrink-0">
                      {formatTime(ts.sec)}
                    </span>
                    <span className="flex-1 min-w-0 text-gray-800">
                      <span className="flex items-center gap-1.5 flex-wrap">
                        {ts.category && (
                          <span className="inline-block rounded-full bg-brand-100 px-2 py-0.5 text-xs font-semibold text-brand-700">
                            {ts.category}
                          </span>
                        )}
                        <span className="font-medium">{ts.label}</span>
                      </span>
                      {ts.quote && (
                        <span className="mt-1 block text-xs italic text-gray-500">
                          &ldquo;{ts.quote}&rdquo;
                        </span>
                      )}
                      {ts.fix && (
                        <span className="mt-1 flex items-start gap-1 text-xs text-brand-700">
                          <span className="shrink-0">→</span>
                          <span>{ts.fix}</span>
                        </span>
                      )}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </div>
  );
}
