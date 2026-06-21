---
name: lesson-report-builder
description: "테니스 레슨 오답노트 리포트 UI 컴포넌트와 Gemini 프롬프트 템플릿을 구축하는 스킬. PMD 7절 UI 와이어프레임(3단 카드, 타임스탬프 링크, 카카오 공유)을 Next.js 컴포넌트로 구현. 레슨 리포트 화면, 오답노트 카드, 리포트 공유 기능, 성장 대시보드 UI 구현 시 반드시 이 스킬을 사용할 것."
---

# Lesson Report Builder

PMD 7.2절의 레슨 상세 분석 리포트 화면을 구현하는 UI + 프롬프트 스킬.

## 리포트 구조 (PMD 7.2 기준)

```
[레슨 상세 분석 리포트]
┌─────────────────────────────────────────────┐
│  좌측: 비디오 플레이어 (스켈레톤 오버레이)     │
│  - 타임스탬프 클릭 시 해당 구간으로 점프       │
│  - 관절 라인 오버레이 토글                    │
├─────────────────────────────────────────────┤
│  우측: AI 오답노트 카드                       │
│  ┌ Card 1 — 고질병 ──────────────────────┐  │
│  │ 코치님이 반복 지적한 핵심 문제           │  │
│  ├ Card 2 — 코치 큐잉 ─────────────────┐  │  │
│  │ "이미지/표현으로 전달한 지시"          │  │
│  ├ Card 3 — 액션 플랜 ─────────────────┐ │  │
│  │ 다음 연습에서 집중할 구체적 행동       │  │
│  └────────────────────────────────────┘  │
│  [카카오톡 공유] [텍스트 복사]              │
└─────────────────────────────────────────────┘
```

## Next.js 컴포넌트 구조

```
src/
├── app/
│   ├── page.tsx                 ← 메인 대시보드
│   └── lessons/
│       └── [id]/
│           └── page.tsx         ← 레슨 리포트 뷰
├── components/
│   ├── LessonCard.tsx           ← 레슨 이력 카드 (대시보드 그리드)
│   ├── ReportView/
│   │   ├── VideoPlayer.tsx      ← 타임스탬프 연동 비디오 플레이어
│   │   ├── NoteCards.tsx        ← 3단 오답노트 카드 컨테이너
│   │   ├── Card1Problem.tsx     ← 고질병 카드
│   │   ├── Card2Cueing.tsx      ← 코치 큐잉 카드
│   │   └── Card3Action.tsx      ← 액션 플랜 카드
│   ├── ShareButtons.tsx         ← 카카오/텍스트 공유
│   └── UrlInputForm.tsx         ← YouTube URL 입력 폼
└── lib/
    ├── api.ts                   ← FastAPI 클라이언트
    └── supabase.ts              ← Supabase 클라이언트
```

## 핵심 컴포넌트: VideoPlayer

타임스탬프 클릭 시 해당 시간으로 점프하는 비디오 플레이어.

```tsx
"use client";
import { useRef, useCallback } from "react";

interface TimestampMarker {
  time: number;     // 초 단위
  label: string;    // 피드백 요약
  severity: "critical" | "normal";
}

interface VideoPlayerProps {
  src: string;
  timestamps: TimestampMarker[];
  showSkeleton: boolean;
  onToggleSkeleton: () => void;
}

export function VideoPlayer({ src, timestamps, showSkeleton, onToggleSkeleton }: VideoPlayerProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  
  const seekTo = useCallback((time: number) => {
    if (videoRef.current) {
      videoRef.current.currentTime = time;
      videoRef.current.play();
    }
  }, []);
  
  return (
    <div className="relative w-full rounded-xl overflow-hidden bg-black">
      <video
        ref={videoRef}
        src={src}
        className="w-full"
        controls
        playsInline
      />
      
      {/* 스켈레톤 오버레이 토글 */}
      <button
        onClick={onToggleSkeleton}
        className="absolute top-3 right-3 bg-black/60 text-white px-3 py-1 rounded-lg text-sm"
      >
        {showSkeleton ? "관절 분석 끄기" : "관절 분석 보기"}
      </button>
      
      {/* 타임스탬프 마커 목록 */}
      <div className="mt-3 space-y-1">
        {timestamps.map((ts, i) => (
          <button
            key={i}
            onClick={() => seekTo(ts.time)}
            className={`flex items-center gap-2 w-full text-left px-3 py-2 rounded-lg text-sm hover:bg-gray-100 transition
              ${ts.severity === "critical" ? "border-l-4 border-red-500" : "border-l-4 border-yellow-400"}`}
          >
            <span className="font-mono text-xs text-gray-500 w-12">
              {Math.floor(ts.time / 60)}:{String(Math.floor(ts.time % 60)).padStart(2, "0")}
            </span>
            <span className="text-gray-700">{ts.label}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
```

## 핵심 컴포넌트: NoteCards (3단 카드)

```tsx
interface LessonReport {
  card1_problem: string;
  card2_cueing: string;
  card3_action: string;
  keywords: Array<{ text: string; count: number }>;
}

export function NoteCards({ report }: { report: LessonReport }) {
  return (
    <div className="space-y-4">
      {/* Card 1: 고질병 */}
      <div className="rounded-2xl border-2 border-red-200 bg-red-50 p-5">
        <div className="flex items-center gap-2 mb-3">
          <span className="text-red-500 text-lg">🎯</span>
          <h3 className="font-bold text-red-700">고질병</h3>
        </div>
        <p className="text-gray-800 leading-relaxed">{report.card1_problem}</p>
      </div>
      
      {/* Card 2: 코치 큐잉 */}
      <div className="rounded-2xl border-2 border-blue-200 bg-blue-50 p-5">
        <div className="flex items-center gap-2 mb-3">
          <span className="text-blue-500 text-lg">💬</span>
          <h3 className="font-bold text-blue-700">코치 큐잉</h3>
        </div>
        <p className="text-gray-800 leading-relaxed italic">"{report.card2_cueing}"</p>
      </div>
      
      {/* Card 3: 액션 플랜 */}
      <div className="rounded-2xl border-2 border-green-200 bg-green-50 p-5">
        <div className="flex items-center gap-2 mb-3">
          <span className="text-green-500 text-lg">✅</span>
          <h3 className="font-bold text-green-700">액션 플랜</h3>
        </div>
        <p className="text-gray-800 leading-relaxed">{report.card3_action}</p>
      </div>
      
      {/* 키워드 */}
      <div className="flex flex-wrap gap-2 pt-2">
        {report.keywords.map((kw, i) => (
          <span key={i} className="bg-gray-100 text-gray-600 px-3 py-1 rounded-full text-sm">
            {kw.text} <span className="text-gray-400">×{kw.count}</span>
          </span>
        ))}
      </div>
    </div>
  );
}
```

## 공유 버튼 컴포넌트

```tsx
export function ShareButtons({ report, lessonTitle }: { report: LessonReport; lessonTitle: string }) {
  const reportText = `[오늘의 테니스 오답노트]\n\n📌 고질병: ${report.card1_problem}\n💬 코치 큐잉: "${report.card2_cueing}"\n✅ 액션 플랜: ${report.card3_action}`;
  
  const shareKakao = () => {
    // Kakao SDK 사용 (환경변수: NEXT_PUBLIC_KAKAO_JS_KEY)
    if (window.Kakao) {
      window.Kakao.Share.sendDefault({
        objectType: "text",
        text: reportText,
        link: { mobileWebUrl: window.location.href, webUrl: window.location.href }
      });
    }
  };
  
  const copyText = async () => {
    await navigator.clipboard.writeText(reportText);
    // toast 알림 표시
  };
  
  return (
    <div className="flex gap-3 pt-2">
      <button
        onClick={shareKakao}
        className="flex-1 bg-yellow-400 hover:bg-yellow-500 text-black font-medium py-3 rounded-xl transition"
      >
        카카오톡으로 공유
      </button>
      <button
        onClick={copyText}
        className="flex-1 bg-gray-100 hover:bg-gray-200 text-gray-700 font-medium py-3 rounded-xl transition"
      >
        텍스트 복사
      </button>
    </div>
  );
}
```

## 메인 대시보드 URL 입력 폼

```tsx
"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";

export function UrlInputForm() {
  const [url, setUrl] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const router = useRouter();
  
  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!url.trim()) return;
    
    setIsLoading(true);
    try {
      const res = await fetch("/api/lessons/analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ youtube_url: url }),
      });
      const lesson = await res.json();
      router.push(`/lessons/${lesson.id}`);
    } catch {
      // 에러 toast
    } finally {
      setIsLoading(false);
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
          className="w-full px-6 py-5 text-lg rounded-2xl border-2 border-gray-200 focus:border-green-500 outline-none pr-36"
        />
        <button
          type="submit"
          disabled={isLoading}
          className="absolute right-2 top-2 bottom-2 px-6 bg-green-500 hover:bg-green-600 text-white font-bold rounded-xl disabled:opacity-50 transition"
        >
          {isLoading ? "분석 중..." : "복기하기"}
        </button>
      </div>
    </form>
  );
}
```

## Supabase DB 타입 (TypeScript)

```typescript
export interface LessonRecord {
  id: string;
  user_id: string;
  youtube_url: string;
  title: string;
  lesson_date: string;
  card1_problem: string;
  card2_cueing: string;
  card3_action: string;
  keywords: Array<{ text: string; count: number }>;
  timestamps: Array<{ time: number; label: string; severity: string }>;
  created_at: string;
}
```
