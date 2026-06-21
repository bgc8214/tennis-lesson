import type { LessonDetail } from "@/types/lesson";
import { VideoPlayer } from "./VideoPlayer";
import { NoteCards } from "./NoteCards";
import { ShareButtons } from "./ShareButtons";

interface ReportViewProps {
  lesson: LessonDetail;
  startSec?: number;
}

/**
 * 레슨 리포트 좌우 2단 레이아웃 컨테이너.
 * - 모바일: 세로로 비디오 → 카드
 * - 데스크톱(lg+): 좌측 비디오(스티키) + 우측 카드
 */
export function ReportView({ lesson, startSec }: ReportViewProps) {
  const { report } = lesson;
  const title = lesson.title?.trim() || "레슨 오답노트";

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)] lg:gap-8">
      {/* 좌측: 비디오 + 타임스탬프 */}
      <div className="lg:sticky lg:top-24 lg:self-start">
        <VideoPlayer
          youtubeUrl={lesson.youtube_url}
          youtubeVideoId={lesson.youtube_video_id}
          timestamps={report?.timestamps ?? []}
          startSec={startSec}
        />
      </div>

      {/* 우측: 3단 카드 + 공유 */}
      <div className="space-y-4">
        {report ? (
          <>
            <NoteCards report={report} />
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

export { VideoPlayer, NoteCards, ShareButtons };
