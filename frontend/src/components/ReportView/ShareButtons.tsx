"use client";

import { useEffect, useState } from "react";
import type { LessonReport } from "@/types/lesson";
import { useToast } from "@/components/ui/Toast";

interface KakaoShare {
  sendDefault: (params: {
    objectType: "text";
    text: string;
    link: { mobileWebUrl: string; webUrl: string };
  }) => void;
}

interface KakaoNamespace {
  isInitialized?: () => boolean;
  init?: (key: string) => void;
  Share?: KakaoShare;
}

declare global {
  interface Window {
    Kakao?: KakaoNamespace;
  }
}

interface ShareButtonsProps {
  report: LessonReport;
  lessonTitle: string;
}

let kakaoLoadingPromise: Promise<void> | null = null;

function loadKakaoSdk(jsKey: string): Promise<void> {
  if (typeof window === "undefined") return Promise.resolve();
  if (window.Kakao?.isInitialized?.()) return Promise.resolve();
  if (kakaoLoadingPromise) return kakaoLoadingPromise;

  kakaoLoadingPromise = new Promise((resolve, reject) => {
    const existing = document.querySelector<HTMLScriptElement>(
      'script[data-kakao-sdk="true"]',
    );
    const onLoad = () => {
      try {
        if (window.Kakao && !window.Kakao.isInitialized?.()) {
          window.Kakao.init?.(jsKey);
        }
        resolve();
      } catch (e) {
        reject(e);
      }
    };
    if (existing) {
      if (window.Kakao) {
        onLoad();
      } else {
        existing.addEventListener("load", onLoad, { once: true });
        existing.addEventListener("error", () => reject(new Error("load")), {
          once: true,
        });
      }
      return;
    }
    const script = document.createElement("script");
    script.src = "https://t1.kakaocdn.net/kakao_js_sdk/2.7.2/kakao.min.js";
    script.async = true;
    script.dataset.kakaoSdk = "true";
    script.onload = onLoad;
    script.onerror = () => reject(new Error("Kakao SDK 로드 실패"));
    document.head.appendChild(script);
  });
  return kakaoLoadingPromise;
}

function buildShareText(report: LessonReport, title: string): string {
  const lines = [`[오늘의 테니스 오답노트] ${title}`, ""];
  if (report.card1_problem) {
    lines.push(`📌 고질병`);
    lines.push(report.card1_problem);
    lines.push("");
  }
  if (report.card2_cueing) {
    lines.push(`💬 코치 큐잉`);
    lines.push(`"${report.card2_cueing}"`);
    lines.push("");
  }
  if (report.card3_action) {
    lines.push(`✅ 액션 플랜`);
    lines.push(report.card3_action);
    lines.push("");
  }
  if (report.keywords?.length) {
    lines.push(report.keywords.map((k) => `#${k}`).join(" "));
  }
  return lines.join("\n").trim();
}

export function ShareButtons({ report, lessonTitle }: ShareButtonsProps) {
  const toast = useToast();
  const [isKakaoLoading, setIsKakaoLoading] = useState(false);
  const [isCopying, setIsCopying] = useState(false);
  const [pageUrl, setPageUrl] = useState("");

  useEffect(() => {
    if (typeof window !== "undefined") {
      setPageUrl(window.location.href);
    }
  }, []);

  const reportText = buildShareText(report, lessonTitle);

  const handleKakao = async () => {
    if (isKakaoLoading) return;
    const jsKey = process.env.NEXT_PUBLIC_KAKAO_JS_KEY;
    if (!jsKey) {
      toast.show(
        "카카오 공유 키가 설정되지 않았습니다. 텍스트 복사를 이용해 주세요.",
        "info",
      );
      return;
    }
    setIsKakaoLoading(true);
    try {
      await loadKakaoSdk(jsKey);
      if (!window.Kakao?.Share) {
        throw new Error("Kakao.Share 미지원");
      }
      window.Kakao.Share.sendDefault({
        objectType: "text",
        text: reportText,
        link: {
          mobileWebUrl: pageUrl,
          webUrl: pageUrl,
        },
      });
    } catch {
      toast.show("카카오톡 공유에 실패했습니다.", "error");
    } finally {
      setIsKakaoLoading(false);
    }
  };

  const handleCopy = async () => {
    if (isCopying) return;
    setIsCopying(true);
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(reportText);
      } else {
        // fallback
        const ta = document.createElement("textarea");
        ta.value = reportText;
        ta.style.position = "fixed";
        ta.style.opacity = "0";
        document.body.appendChild(ta);
        ta.select();
        document.execCommand("copy");
        document.body.removeChild(ta);
      }
      toast.show("오답노트 텍스트를 복사했습니다.", "success");
    } catch {
      toast.show("복사에 실패했습니다.", "error");
    } finally {
      setIsCopying(false);
    }
  };

  return (
    <div className="flex gap-3 pt-2">
      <button
        type="button"
        onClick={handleKakao}
        disabled={isKakaoLoading}
        className="flex flex-1 items-center justify-center gap-2 rounded-xl bg-yellow-400 py-3 text-sm font-semibold text-black transition hover:bg-yellow-500 disabled:opacity-60 sm:text-base"
      >
        {isKakaoLoading ? "준비 중..." : "카카오톡으로 공유"}
      </button>
      <button
        type="button"
        onClick={handleCopy}
        disabled={isCopying}
        className="flex flex-1 items-center justify-center gap-2 rounded-xl bg-gray-100 py-3 text-sm font-semibold text-gray-700 transition hover:bg-gray-200 disabled:opacity-60 sm:text-base"
      >
        {isCopying ? "복사 중..." : "텍스트 복사"}
      </button>
    </div>
  );
}
