"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { UrlInputForm } from "@/components/UrlInputForm";
import { LessonCard, LessonCardSkeleton } from "@/components/LessonCard";
import { LessonTypeFilter } from "@/components/LessonTypeFilter";
import { InsightPanel } from "@/components/InsightPanel";
import { getLessons } from "@/lib/api";
import { ApiCallError, type LessonSummary } from "@/types/lesson";
import { useAnalysisTracker } from "@/lib/AnalysisTracker";

const PAGE_SIZE = 12;

export default function HomePage() {
  const [lessons, setLessons] = useState<LessonSummary[]>([]);
  const [isLoadingList, setIsLoadingList] = useState(true);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [listError, setListError] = useState<string | null>(null);
  const [selectedType, setSelectedType] = useState<string | null>(null);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);

  const loadLessons = useCallback(async () => {
    setIsLoadingList(true);
    setListError(null);
    try {
      const res = await getLessons({
        limit: PAGE_SIZE,
        lesson_type: selectedType ?? undefined,
      });
      setLessons(res.data);
      setNextCursor(res.pagination.next_cursor);
      setHasMore(res.pagination.has_more);
    } catch (err) {
      if (err instanceof ApiCallError && err.status === 401) {
        setLessons([]);
      } else {
        const msg =
          err instanceof Error ? err.message : "레슨 목록을 불러오지 못했습니다.";
        setListError(msg);
      }
    } finally {
      setIsLoadingList(false);
    }
  }, [selectedType]);

  const loadMore = useCallback(async () => {
    if (!nextCursor || isLoadingMore) return;
    setIsLoadingMore(true);
    try {
      const res = await getLessons({
        limit: PAGE_SIZE,
        cursor: nextCursor,
        lesson_type: selectedType ?? undefined,
      });
      setLessons((prev) => [...prev, ...res.data]);
      setNextCursor(res.pagination.next_cursor);
      setHasMore(res.pagination.has_more);
    } catch {
      // 더보기 실패는 조용히 무시
    } finally {
      setIsLoadingMore(false);
    }
  }, [nextCursor, isLoadingMore, selectedType]);

  useEffect(() => {
    loadLessons();
  }, [loadLessons]);

  const { active } = useAnalysisTracker();
  const prevCountRef = useRef(active.length);

  useEffect(() => {
    if (active.length < prevCountRef.current) {
      loadLessons();
    }
    prevCountRef.current = active.length;
  }, [active.length, loadLessons]);

  const handleDeleted = useCallback((deletedId: string) => {
    setLessons((prev) => prev.filter((l) => l.lesson_id !== deletedId));
  }, []);

  return (
    <div className="space-y-12">
      {/* 헤드라인 */}
      <section className="pt-4 text-center sm:pt-10">
        <h1 className="text-2xl font-extrabold leading-tight tracking-tight text-gray-900 sm:text-4xl">
          레슨의 망각을{" "}
          <span className="text-brand-600">데이터의 자산</span>으로
        </h1>
        <p className="mx-auto mt-3 max-w-xl text-sm text-gray-600 sm:mt-4 sm:text-base">
          유튜브 레슨 영상 한 개로, AI가 1분 만에 고질병 · 코치 큐잉 · 액션 플랜
          3단 오답노트를 정리해 드립니다.
        </p>

        <div className="mt-6 sm:mt-8">
          <UrlInputForm onAnalyzed={() => loadLessons()} />
        </div>
      </section>

      {/* 최근 레슨 */}
      <section>
        <div className="mb-4 flex items-end justify-between">
          <h2 className="text-lg font-bold text-gray-900 sm:text-xl">
            최근 레슨
          </h2>
          {lessons.length > 0 && (
            <span className="text-xs text-gray-500">총 {lessons.length}개</span>
          )}
        </div>

        <div className="mb-4">
          <LessonTypeFilter selected={selectedType} onChange={setSelectedType} />
        </div>

        {isLoadingList ? (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {Array.from({ length: 6 }).map((_, i) => (
              <LessonCardSkeleton key={i} />
            ))}
          </div>
        ) : listError ? (
          <div className="rounded-2xl border border-red-200 bg-red-50 p-6 text-center text-sm text-red-700">
            {listError}
            <button
              type="button"
              onClick={() => loadLessons()}
              className="ml-3 inline-flex items-center rounded-md bg-red-600 px-3 py-1 text-xs font-semibold text-white hover:bg-red-700"
            >
              다시 시도
            </button>
          </div>
        ) : lessons.length === 0 ? (
          <EmptyState />
        ) : (
          <>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {lessons.map((lesson) => (
                <LessonCard
                  key={lesson.lesson_id}
                  lesson={lesson}
                  onDeleted={handleDeleted}
                />
              ))}
            </div>
            {hasMore && (
              <div className="mt-6 text-center">
                <button
                  type="button"
                  onClick={loadMore}
                  disabled={isLoadingMore}
                  className="inline-flex items-center gap-2 rounded-xl border border-gray-200 bg-white px-6 py-2.5 text-sm font-medium text-gray-700 shadow-sm hover:bg-gray-50 disabled:opacity-50"
                >
                  {isLoadingMore ? "불러오는 중..." : "더 보기"}
                </button>
              </div>
            )}
          </>
        )}
      </section>

      {/* 크로스-레슨 인사이트 */}
      <InsightPanel lessonCount={lessons.length} />
    </div>
  );
}

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center rounded-3xl border-2 border-dashed border-gray-200 bg-gradient-to-b from-brand-50/40 to-white py-16 text-center">
      <div className="mb-4 inline-flex h-16 w-16 items-center justify-center rounded-2xl bg-brand-100 text-brand-600">
        <svg
          xmlns="http://www.w3.org/2000/svg"
          viewBox="0 0 24 24"
          fill="currentColor"
          className="h-8 w-8"
          aria-hidden
        >
          <path d="M12 2a10 10 0 1 0 10 10A10 10 0 0 0 12 2Zm-1.5 14.5v-9l7 4.5Z" />
        </svg>
      </div>
      <h3 className="text-base font-bold text-gray-900 sm:text-lg">
        첫 레슨을 복기해보세요!
      </h3>
      <p className="mt-2 max-w-sm px-6 text-sm text-gray-600">
        오늘 받은 1:1 테니스 레슨 영상의 유튜브 링크를 위에 붙여넣으면, AI가
        오답노트를 만들어 드립니다.
      </p>
    </div>
  );
}
