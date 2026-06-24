import { ImageResponse } from "next/og";

export const runtime = "edge";
export const alt = "오늘의 테니스 — AI 레슨 복기";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default function OgImage() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "center",
          background: "linear-gradient(135deg, #0f172a 0%, #1a2e1a 100%)",
          padding: "80px",
          fontFamily: "-apple-system, BlinkMacSystemFont, sans-serif",
          position: "relative",
          overflow: "hidden",
        }}
      >
        {/* 배경 글로우 */}
        <div
          style={{
            position: "absolute",
            top: -200,
            right: -100,
            width: 700,
            height: 700,
            borderRadius: "50%",
            background: "radial-gradient(circle, rgba(34,197,94,0.15) 0%, transparent 70%)",
          }}
        />

        {/* 코트 라인 장식 */}
        <div
          style={{
            position: "absolute",
            inset: 40,
            border: "1.5px solid rgba(34,197,94,0.15)",
            borderRadius: 12,
          }}
        />
        <div
          style={{
            position: "absolute",
            top: 40,
            left: "50%",
            bottom: 40,
            width: 1,
            background: "rgba(34,197,94,0.08)",
          }}
        />

        {/* 로고 + 서비스명 */}
        <div style={{ display: "flex", alignItems: "center", gap: 20, marginBottom: 32 }}>
          <div
            style={{
              width: 64,
              height: 64,
              borderRadius: 16,
              background: "#22c55e",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontSize: 32,
            }}
          >
            🎾
          </div>
          <span style={{ fontSize: 48, fontWeight: 800, color: "white", letterSpacing: -1 }}>
            오늘의 테니스
          </span>
        </div>

        {/* 구분선 */}
        <div style={{ width: 100, height: 4, borderRadius: 2, background: "#22c55e", marginBottom: 32 }} />

        {/* 슬로건 */}
        <div style={{ fontSize: 30, color: "#86efac", fontWeight: 600, marginBottom: 16 }}>
          레슨의 망각을 데이터의 자산으로
        </div>

        {/* 설명 */}
        <div style={{ fontSize: 22, color: "#94a3b8", marginBottom: 48 }}>
          AI가 코치님의 피드백을 분석해 오답노트로 정리합니다
        </div>

        {/* 태그 */}
        <div style={{ display: "flex", gap: 16 }}>
          {["고질병 분석", "코치 큐잉", "액션 플랜", "코트 전술"].map((tag) => (
            <div
              key={tag}
              style={{
                padding: "10px 22px",
                borderRadius: 999,
                border: "1px solid rgba(34,197,94,0.4)",
                background: "rgba(34,197,94,0.1)",
                color: "#4ade80",
                fontSize: 17,
                fontWeight: 500,
              }}
            >
              {tag}
            </div>
          ))}
        </div>

        {/* URL */}
        <div
          style={{
            position: "absolute",
            bottom: 60,
            right: 80,
            fontSize: 18,
            color: "rgba(74,222,128,0.6)",
          }}
        >
          tennis-lesson.vercel.app
        </div>
      </div>
    ),
    { ...size }
  );
}
