"use client";

import { useCallback, useEffect, useRef, useState } from "react";

interface LocalVideoPlayerProps {
  /** ReportView가 타임스탬프 클릭 시 넘기는 점프 목표 초. */
  requestedSec?: number;
  startSec?: number;
}

/**
 * 17문서 U-1: 업로드 레슨용 로컬 영상 플레이어.
 *
 * 영상은 서버에 저장되지 않으므로, 사용자가 기기에서 파일을 다시 선택해야 재생된다.
 * 파일 미선택 상태에서도 리포트 텍스트/타임라인은 완전히 열람 가능하다(영상은 부가물).
 * 선택한 파일은 URL.createObjectURL로만 재생하며 어디로도 전송하지 않는다.
 */
export function LocalVideoPlayer({ requestedSec, startSec = 0 }: LocalVideoPlayerProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const objectUrlRef = useRef<string | null>(null);
  const [objectUrl, setObjectUrl] = useState<string | null>(null);
  const [fileName, setFileName] = useState<string | null>(null);

  const revoke = useCallback(() => {
    if (objectUrlRef.current) {
      URL.revokeObjectURL(objectUrlRef.current);
      objectUrlRef.current = null;
    }
  }, []);

  // 언마운트 시 objectURL 해제
  useEffect(() => revoke, [revoke]);

  const handleSelect = useCallback(
    (file: File) => {
      revoke();
      const url = URL.createObjectURL(file);
      objectUrlRef.current = url;
      setObjectUrl(url);
      setFileName(file.name);
    },
    [revoke],
  );

  // 타임스탬프 → currentTime 점프. 영상 길이를 넘으면 clamp(seek 무시/리셋 방지).
  useEffect(() => {
    if (requestedSec === undefined) return;
    const video = videoRef.current;
    if (!video || !objectUrl) return;

    const seekTo = (sec: number) => {
      const duration = Number.isFinite(video.duration) ? video.duration : 0;
      const clamped = duration > 0 && sec > duration ? Math.max(0, duration - 1) : sec;
      video.currentTime = clamped;
      void video.play().catch(() => { /* 자동재생 차단은 무시 */ });
    };

    if (video.readyState >= 1) {
      seekTo(requestedSec);
    } else {
      const onMeta = () => {
        seekTo(requestedSec);
        video.removeEventListener("loadedmetadata", onMeta);
      };
      video.addEventListener("loadedmetadata", onMeta);
      return () => video.removeEventListener("loadedmetadata", onMeta);
    }
  }, [requestedSec, objectUrl]);

  // 최초 로드 시 startSec 반영
  useEffect(() => {
    if (!objectUrl || startSec <= 0) return;
    const video = videoRef.current;
    if (!video) return;
    const onMeta = () => {
      video.currentTime = startSec;
      video.removeEventListener("loadedmetadata", onMeta);
    };
    video.addEventListener("loadedmetadata", onMeta);
    return () => video.removeEventListener("loadedmetadata", onMeta);
  }, [objectUrl, startSec]);

  if (!objectUrl) {
    return (
      <div className="space-y-3">
        <div className="flex aspect-video w-full flex-col items-center justify-center gap-3 rounded-2xl border-2 border-dashed border-gray-200 bg-gray-50 p-6 text-center">
          <span className="text-3xl" aria-hidden>📁</span>
          <p className="text-sm text-gray-600">
            영상은 서버에 저장되지 않아 기기에서 다시 선택해요.
          </p>
          <label className="cursor-pointer rounded-xl bg-brand-500 px-4 py-2.5 text-sm font-bold text-white hover:bg-brand-600">
            영상 파일 선택
            <input
              type="file"
              accept="video/*"
              className="hidden"
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) handleSelect(file);
              }}
            />
          </label>
          <p className="text-xs text-gray-400">
            아래 오답노트와 타임라인은 영상 없이도 모두 볼 수 있어요.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="relative w-full overflow-hidden rounded-2xl bg-black shadow-sm">
        <div className="aspect-video w-full">
          <video
            ref={videoRef}
            src={objectUrl}
            controls
            playsInline
            className="h-full w-full"
          />
        </div>
      </div>
      <div className="flex items-center justify-between gap-2 text-xs text-gray-500">
        <span className="truncate">{fileName}</span>
        <label className="shrink-0 cursor-pointer hover:text-gray-700">
          다른 파일 선택
          <input
            type="file"
            accept="video/*"
            className="hidden"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) handleSelect(file);
            }}
          />
        </label>
      </div>
    </div>
  );
}
