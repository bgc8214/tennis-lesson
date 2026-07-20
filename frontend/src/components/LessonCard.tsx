"use client";

import Link from "next/link";
import { useState } from "react";
import { deleteLesson } from "@/lib/api";
import { ApiCallError, type LessonSummary } from "@/types/lesson";
import { LoadingSpinner } from "@/components/ui/LoadingSpinner";
import { useToast } from "@/components/ui/Toast";

interface LessonCardProps {
  lesson: LessonSummary;
  /** Card 1 미리보기용 텍스트 (선택). 상세 fetch 비용을 피하기 위해 옵셔널. */
  previewText?: string | null;
  /** 삭제 성공 시 부모 컴포넌트에서 목록 갱신. */
  onDeleted?: (lessonId: string) => void;
}

const STATUS_LABEL: Record<LessonSummary["processing_status"], string> = {
  PENDING: "대기 중",
  PROCESSING: "분석 중",
  DONE: "분석 완료",
  FAILED: "분석 실패",
};

const STATUS_STYLE: Record<LessonSummary["processing_status"], string> = {
  PENDING: "bg-gray-100 text-gray-600",
  PROCESSING: "bg-blue-100 text-blue-700",
  DONE: "bg-brand-100 text-brand-700",
  FAILED: "bg-red-100 text-red-700",
};

function formatDate(value: string | null | undefined): string {
  if (!value) return "";
  // YYYY-MM-DD 또는 ISO 8601 모두 처리
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${yyyy}.${mm}.${dd}`;
}

export function LessonCard({
  lesson,
  previewText,
  onDeleted,
}: LessonCardProps) {
  const [isDeleting, setIsDeleting] = useState(false);
  const toast = useToast();

  const dateLabel = formatDate(lesson.lesson_date ?? lesson.created_at);
  const title = lesson.title?.trim() || "제목 없는 레슨";
  const isUpload = lesson.source_type === "upload";
  // 업로드 레슨은 유튜브 썸네일이 없다 — thumbnail_url이 있으면 쓰고, 없으면 플레이스홀더.
  const thumbnail = isUpload
    ? lesson.thumbnail_url || null
    : lesson.thumbnail_url ||
      (lesson.youtube_video_id
        ? `https://i.ytimg.com/vi/${lesson.youtube_video_id}/hqdefault.jpg`
        : null);
  const isClickable =
    lesson.processing_status === "DONE" ||
    lesson.processing_status === "FAILED";

  const handleDelete = async (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (isDeleting) return;
    const ok = window.confirm(
      `"${title}" 레슨을 삭제하시겠어요?\n삭제하면 복구할 수 없습니다.`,
    );
    if (!ok) return;
    setIsDeleting(true);
    try {
      await deleteLesson(lesson.lesson_id);
      toast.show("레슨을 삭제했습니다.", "success");
      onDeleted?.(lesson.lesson_id);
    } catch (err) {
      const msg =
        err instanceof ApiCallError
          ? err.message
          : "삭제 중 오류가 발생했습니다.";
      toast.show(msg, "error");
      setIsDeleting(false);
    }
  };

  const cardBody = (
    <article className="group relative flex h-full flex-col overflow-hidden rounded-2xl border border-gray-200 bg-white shadow-sm transition-all hover:border-brand-300 hover:shadow-md">
      {/* 썸네일 */}
      <div className="relative aspect-video w-full overflow-hidden bg-gray-100">
        {thumbnail ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={thumbnail}
            alt={title}
            loading="lazy"
            className="h-full w-full object-cover transition-transform duration-300 group-hover:scale-[1.03]"
          />
        ) : (
          <div className="flex h-full w-full items-center justify-center bg-gradient-to-br from-brand-50 to-gray-100 text-4xl">
            <span aria-hidden>🎾</span>
          </div>
        )}
        <div className="absolute inset-x-0 bottom-0 h-12 bg-gradient-to-t from-black/40 to-transparent" />
        <span
          className={`absolute left-3 top-3 rounded-full px-2.5 py-1 text-xs font-semibold ${STATUS_STYLE[lesson.processing_status]}`}
        >
          {STATUS_LABEL[lesson.processing_status]}
        </span>
        {isUpload && (
          <span className="absolute right-3 top-3 rounded-full bg-black/60 px-2.5 py-1 text-xs font-semibold text-white backdrop-blur">
            📁 업로드
          </span>
        )}
      </div>

      {/* 본문 */}
      <div className="flex flex-1 flex-col gap-2 p-4">
        <p className="text-xs font-medium text-gray-500">{dateLabel}</p>
        <h3 className="line-clamp-2 text-sm font-bold leading-snug text-gray-900 sm:text-base">
          {title}
        </h3>
        {previewText ? (
          <p className="mt-1 line-clamp-2 text-xs text-gray-600 sm:text-sm">
            <span className="mr-1 inline-block font-semibold text-red-600">
              고질병
            </span>
            {previewText}
          </p>
        ) : lesson.processing_status === "PROCESSING" ||
          lesson.processing_status === "PENDING" ? (
          <p className="mt-1 text-xs text-gray-500">
            AI가 오답노트를 작성하고 있어요
          </p>
        ) : null}

        {lesson.lesson_type && lesson.lesson_type.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-1">
            {lesson.lesson_type.map((type) => (
              <span
                key={type}
                className="rounded-full bg-green-100 px-2 py-0.5 text-xs font-medium text-green-700"
              >
                {type}
              </span>
            ))}
          </div>
        )}
      </div>

      {/* 삭제 버튼 */}
      <button
        type="button"
        onClick={handleDelete}
        disabled={isDeleting}
        aria-label="레슨 삭제"
        className="absolute right-2 top-2 inline-flex h-8 w-8 items-center justify-center rounded-full bg-white/90 text-gray-500 opacity-0 shadow-sm backdrop-blur transition hover:bg-red-50 hover:text-red-600 focus-visible:opacity-100 group-hover:opacity-100 disabled:opacity-50 sm:h-9 sm:w-9"
      >
        {isDeleting ? (
          <LoadingSpinner size="sm" />
        ) : (
          <svg
            xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 20 20"
            fill="currentColor"
            className="h-4 w-4"
            aria-hidden
          >
            <path
              fillRule="evenodd"
              d="M8.75 1A2.75 2.75 0 0 0 6 3.75v.443c-.795.077-1.584.176-2.365.298a.75.75 0 1 0 .23 1.482l.149-.022.841 10.518A2.75 2.75 0 0 0 7.596 19h4.807a2.75 2.75 0 0 0 2.742-2.53l.841-10.52.149.023a.75.75 0 0 0 .23-1.482A41.03 41.03 0 0 0 14 4.193V3.75A2.75 2.75 0 0 0 11.25 1h-2.5ZM10 4c.84 0 1.673.025 2.5.075V3.75c0-.69-.56-1.25-1.25-1.25h-2.5c-.69 0-1.25.56-1.25 1.25v.325C8.327 4.025 9.16 4 10 4ZM8.58 7.72a.75.75 0 0 0-1.5.06l.3 7.5a.75.75 0 1 0 1.5-.06l-.3-7.5Zm4.34.06a.75.75 0 1 0-1.5-.06l-.3 7.5a.75.75 0 1 0 1.5.06l.3-7.5Z"
              clipRule="evenodd"
            />
          </svg>
        )}
      </button>
    </article>
  );

  if (isClickable) {
    return (
      <Link
        href={`/lessons/${lesson.lesson_id}`}
        className="block focus-visible:rounded-2xl"
      >
        {cardBody}
      </Link>
    );
  }
  // PENDING/PROCESSING — 클릭은 가능하지만 시각적으로 비활성 느낌 (상세에서 진행 상태 노출)
  return (
    <Link
      href={`/lessons/${lesson.lesson_id}`}
      className="block opacity-90 focus-visible:rounded-2xl"
    >
      {cardBody}
    </Link>
  );
}

/** 로딩용 스켈레톤 */
export function LessonCardSkeleton() {
  return (
    <div className="overflow-hidden rounded-2xl border border-gray-200 bg-white">
      <div className="aspect-video w-full animate-pulse bg-gray-200" />
      <div className="space-y-2 p-4">
        <div className="h-3 w-16 animate-pulse rounded bg-gray-200" />
        <div className="h-4 w-3/4 animate-pulse rounded bg-gray-200" />
        <div className="h-3 w-full animate-pulse rounded bg-gray-200" />
      </div>
    </div>
  );
}
