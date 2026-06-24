import type { Metadata, Viewport } from "next";
import { Header } from "@/components/ui/Header";
import { AnalysisBanner } from "@/components/ui/AnalysisBanner";
import { ToastProvider } from "@/components/ui/Toast";
import { AnalysisTrackerProvider } from "@/lib/AnalysisTracker";
import "./globals.css";

export const metadata: Metadata = {
  title: "오늘의 테니스 — AI 레슨 복기",
  description:
    "유튜브 레슨 영상을 1분 만에 오답노트로. AI가 코치님의 피드백을 분석해 고질병 / 코치 큐잉 / 액션 플랜 3장으로 정리합니다.",
  metadataBase: new URL(
    process.env.NEXT_PUBLIC_SITE_URL ?? "https://tennis-lesson.vercel.app",
  ),
  openGraph: {
    title: "오늘의 테니스 — AI 레슨 복기",
    description: "레슨의 망각을 데이터의 자산으로.",
    type: "website",
    siteName: "오늘의 테니스",
  },
  twitter: {
    card: "summary_large_image",
    title: "오늘의 테니스 — AI 레슨 복기",
    description: "레슨의 망각을 데이터의 자산으로.",
  },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#22c55e",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="ko">
      <body className="min-h-screen bg-white">
        <ToastProvider>
          <AnalysisTrackerProvider>
            <Header />
            <AnalysisBanner />
            <main className="mx-auto max-w-6xl px-4 pb-16 pt-6 sm:px-6 sm:pt-10">
              {children}
            </main>
            <footer className="border-t border-gray-100 py-6">
              <div className="mx-auto max-w-6xl px-4 text-center text-xs text-gray-400 sm:px-6">
                © {new Date().getFullYear()} 오늘의 테니스 · Phase 1 MVP
              </div>
            </footer>
          </AnalysisTrackerProvider>
        </ToastProvider>
      </body>
    </html>
  );
}
