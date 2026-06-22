"use client";

import { useState } from "react";
import type { LessonDetail } from "@/types/lesson";
import { VideoPlayer } from "./VideoPlayer";
import { NoteCards } from "./NoteCards";
import { ShareButtons } from "./ShareButtons";
import { CourtDiagram } from "./CourtDiagram";

interface ReportViewProps {
  lesson: LessonDetail;
  startSec?: number;
}

export function ReportView({ lesson, startSec }: ReportViewProps) {
  const { report } = lesson;
  const title = lesson.title?.trim() || "레슨 오답노트";

  const [requestedSec, setRequestedSec] = useState<number | undefined>(
    startSec && startSec > 0 ? startSec : undefined,
  );
  const [courtSelectedIndex, setCourtSelectedIndex] = useState<number | null>(null);

  const handleSeek = (sec: number) => setRequestedSec(sec);

  const showCourt = report && (
    report.court_analysis_status === "PROCESSING" ||
    report.court_analysis_status === "FAILED" ||
    (report.court_analysis_status === "DONE" && report.court_tactics)
  );

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)] lg:gap-8">
      {/* 좌측: 비디오만 sticky */}
      <div className="lg:sticky lg:top-24 lg:self-start">
        <VideoPlayer
          youtubeUrl={lesson.youtube_url}
          youtubeVideoId={lesson.youtube_video_id}
          startSec={startSec}
          requestedSec={requestedSec}
        />
      </div>

      {/* 우측: 3단 카드 + 코트 전술(피드백 목록 통합) + 공유 */}
      <div className="space-y-4">
        {report ? (
          <>
            <NoteCards report={report} />
            <CourtDiagram
              tactics={report.court_tactics ?? []}
              timestamps={report.timestamps ?? []}
              courtAnalysisStatus={report.court_analysis_status}
              onSeek={handleSeek}
              selectedIndex={courtSelectedIndex}
              onSelectIndex={setCourtSelectedIndex}
            />
            <ShareButtons report={report} lessonTitle={title} />
          </>
        ) : (
          <div className="rounded-2xl border-2 border-dashed border-gray-200 bg-gray-50 p-6 text-center text-sm text-gray-500">
            리포트 데이터를 불러오는 중입니다.
          </div>
        )}
      </div>
    </div>
  );
}

export { VideoPlayer, NoteCards, ShareButtons, CourtDiagram };
