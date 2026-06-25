"use client";

import { useEffect, useRef, useState } from "react";

interface VideoPlayerProps {
  youtubeUrl: string;
  youtubeVideoId: string;
  startSec?: number;
  requestedSec?: number;
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

export function VideoPlayer({
  youtubeUrl,
  youtubeVideoId,
  startSec = 0,
  requestedSec,
}: VideoPlayerProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const playerRef = useRef<YTPlayer | null>(null);
  const [isReady, setIsReady] = useState(false);

  useEffect(() => {
    let cancelled = false;

    loadYouTubeIframeAPI()
      .then((YT) => {
        if (cancelled || !containerRef.current) return;
        const player = new YT.Player(containerRef.current, {
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

  // requestedSec가 변경되면 플레이어를 해당 초로 이동
  useEffect(() => {
    if (requestedSec === undefined) return;
    const player = playerRef.current;
    if (player && isReady) {
      player.seekTo(requestedSec, true);
      player.playVideo();
    } else if (requestedSec !== undefined) {
      // 폴백: 새 탭으로 시간 지정 링크
      const url = `https://www.youtube.com/watch?v=${youtubeVideoId}&t=${Math.floor(requestedSec)}s`;
      window.open(url, "_blank", "noopener,noreferrer");
    }
  }, [requestedSec, isReady, youtubeVideoId]);

  return (
    <div className="space-y-3">
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
    </div>
  );
}
