"use client";

/**
 * 17문서 U-0: 폰 브라우저에서 FFmpeg.wasm demux(오디오 추출) 실측용 진단 페이지.
 *
 * 게이트: "폰에서 1분 이내 추출 성공률". 이 페이지는 배포된 사이트에서
 * 실제 폰(안드로이드/iOS Safari)으로 열어 영상 파일을 선택하면, demux
 * (-vn -acodec copy) 소요 시간·결과 파일 크기·실패 여부를 화면에 보여준다.
 * 구현 코드가 아니라 측정 도구 — 결과를 17문서 4절 표에 기록할 것.
 */

import { useCallback, useState } from "react";
import { extractAudioFromVideo, probeVideoDuration } from "@/lib/extractAudio";

type Phase = "idle" | "loading-ffmpeg" | "probing" | "extracting" | "done" | "error";

interface Result {
  fileName: string;
  fileSizeMB: number;
  durationSec: number | null;
  extractMs: number;
  outputSizeMB: number;
  copyOk: boolean;
  reencodeUsed: boolean;
  errorMessage?: string;
}

export default function U0FfmpegTestPage() {
  const [phase, setPhase] = useState<Phase>("idle");
  const [progressMsg, setProgressMsg] = useState("");
  const [result, setResult] = useState<Result | null>(null);

  const handleFile = useCallback(async (file: File) => {
    setResult(null);
    setPhase("probing");
    setProgressMsg("영상 길이 확인 중...");

    const durationSec = await probeVideoDuration(file);
    const fileSizeMB = file.size / (1024 * 1024);

    try {
      const extracted = await extractAudioFromVideo(file, (p) => {
        setPhase(p.phase);
        setProgressMsg(p.message);
      });

      setResult({
        fileName: file.name,
        fileSizeMB,
        durationSec,
        extractMs: extracted.extractMs,
        outputSizeMB: extracted.outputSizeBytes / (1024 * 1024),
        copyOk: extracted.copyOk,
        reencodeUsed: extracted.reencodeUsed,
      });
      setPhase("done");
    } catch (e) {
      setPhase("error");
      setResult({
        fileName: file.name,
        fileSizeMB,
        durationSec,
        extractMs: 0,
        outputSizeMB: 0,
        copyOk: false,
        reencodeUsed: false,
        errorMessage: e instanceof Error ? e.message : String(e),
      });
    }
  }, []);

  const busy = phase === "loading-ffmpeg" || phase === "probing" || phase === "extracting";

  return (
    <div className="mx-auto max-w-lg space-y-4">
      <div className="rounded-2xl border border-gray-100 bg-gray-50 p-4 text-sm text-gray-600">
        <p className="font-semibold text-gray-800">17문서 U-0: 폰 오디오 추출 실측</p>
        <p className="mt-1">
          영상 파일을 선택하면 브라우저에서 오디오만 추출합니다. 영상은 어디로도
          전송되지 않아요 — 이 페이지에서 소요 시간만 측정합니다.
        </p>
      </div>

      <label className="block">
        <span className="mb-1 block text-sm font-medium text-gray-700">영상 파일 선택</span>
        <input
          type="file"
          accept="video/*"
          disabled={busy}
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) handleFile(file);
          }}
          className="block w-full rounded-xl border border-gray-200 p-3 text-sm disabled:opacity-50"
        />
      </label>

      {busy && (
        <div className="rounded-xl border border-brand-200 bg-brand-50 p-3 text-sm text-brand-700">
          <span className="font-mono text-xs">{phase}</span> — {progressMsg || "처리 중..."}
        </div>
      )}

      {result && (
        <div
          className={[
            "rounded-2xl border-2 p-4 text-sm",
            phase === "error" ? "border-red-200 bg-red-50" : "border-emerald-200 bg-emerald-50",
          ].join(" ")}
        >
          <h2 className="font-bold text-gray-900">
            {phase === "error" ? "❌ 추출 실패" : "✅ 추출 완료"}
          </h2>
          <dl className="mt-2 space-y-1 text-gray-700">
            <Row label="파일명" value={result.fileName} />
            <Row label="원본 크기" value={`${result.fileSizeMB.toFixed(1)} MB`} />
            <Row
              label="영상 길이"
              value={result.durationSec != null ? `${Math.round(result.durationSec)}초` : "확인 불가"}
            />
            <Row label="소요 시간" value={`${(result.extractMs / 1000).toFixed(1)}초`} />
            <Row label="결과 크기" value={`${result.outputSizeMB.toFixed(2)} MB`} />
            <Row label="방식" value={result.reencodeUsed ? "재인코딩 폴백(aac)" : "demux(copy, 무손실)"} />
            {result.errorMessage && <Row label="에러" value={result.errorMessage} />}
          </dl>
          <p className="mt-3 text-xs text-gray-500">
            게이트 기준(17문서): 60분 내외 영상이 폰에서 1분 이내 추출되면 통과.
            이 결과를 스크린샷으로 남겨서 알려주세요 (기기 모델 + 브라우저 포함).
          </p>
        </div>
      )}
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-3">
      <dt className="text-gray-500">{label}</dt>
      <dd className="text-right font-medium">{value}</dd>
    </div>
  );
}
