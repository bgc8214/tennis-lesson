"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { getLessonsByKeyword, type KeywordTimestampEntry } from "@/lib/api";

function formatTime(sec: number): string {
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

export default function InsightKeywordPage() {
  const params = useParams<{ keyword: string }>();
  const keyword = decodeURIComponent(params?.keyword ?? "");

  const [entries, setEntries] = useState<KeywordTimestampEntry[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    if (!keyword) return;
    getLessonsByKeyword(keyword)
      .then(setEntries)
      .finally(() => setIsLoading(false));
  }, [keyword]);

  return (
    <div className="space-y-6">
      {/* 헤더 */}
      <div>
        <Link
          href="/"
          className="inline-flex items-center gap-1 text-xs text-gray-500 hover:text-gray-700"
        >
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="h-3.5 w-3.5" aria-hidden>
            <path fillRule="evenodd" d="M12.78 5.22a.75.75 0 0 1 0 1.06L8.06 11l4.72 4.72a.75.75 0 1 1-1.06 1.06l-5.25-5.25a.75.75 0 0 1 0-1.06l5.25-5.25a.75.75 0 0 1 1.06 0Z" clipRule="evenodd" />
          </svg>
          대시보드
        </Link>
        <div className="mt-2 flex items-center gap-3">
          <h1 className="text-2xl font-extrabold text-gray-900">
            #{keyword}
          </h1>
          {!isLoading && (
            <span className="rounded-full bg-gray-100 px-3 py-1 text-sm text-gray-500">
              {entries.length}개 레슨에서 반복
            </span>
          )}
        </div>
        <p className="mt-1 text-sm text-gray-500">
          이 고질병이 나온 모든 레슨과 코치 피드백 순간을 확인하세요.
        </p>
      </div>

      {/* 레슨 목록 */}
      {isLoading ? (
        <div className="space-y-4">
          {[1, 2].map((i) => (
            <div key={i} className="h-40 animate-pulse rounded-2xl bg-gray-100" />
          ))}
        </div>
      ) : entries.length === 0 ? (
        <div className="rounded-2xl border border-gray-200 bg-gray-50 p-8 text-center text-sm text-gray-500">
          관련 레슨을 찾을 수 없습니다.
        </div>
      ) : (
        <div className="space-y-4">
          {entries.map((entry) => (
            <div
              key={entry.lesson_id}
              className="overflow-hidden rounded-2xl border border-gray-200 bg-white shadow-sm"
            >
              {/* 레슨 헤더 */}
              <div className="flex items-center gap-4 border-b border-gray-100 p-4">
                {entry.thumbnail_url && (
                  <img
                    src={entry.thumbnail_url}
                    alt=""
                    className="h-14 w-24 shrink-0 rounded-lg object-cover"
                  />
                )}
                <div className="min-w-0 flex-1">
                  <Link
                    href={`/lessons/${entry.lesson_id}`}
                    className="block truncate font-bold text-gray-900 hover:text-brand-600"
                  >
                    {entry.lesson_title ?? "레슨"}
                  </Link>
                  <p className="mt-0.5 text-xs text-gray-400">
                    {entry.lesson_date ?? new Date(entry.created_at).toLocaleDateString()}
                  </p>
                </div>
              </div>

              {/* 타임스탬프 목록 */}
              <ul className="divide-y divide-gray-100">
                {entry.timestamps.map((ts, i) => (
                  <li key={`${ts.sec}-${i}`}>
                    <Link
                      href={`/lessons/${entry.lesson_id}?t=${ts.sec}`}
                      className="flex items-start gap-4 px-4 py-3 transition-colors hover:bg-brand-50"
                    >
                      <span className="mt-0.5 shrink-0 rounded bg-gray-900 px-2 py-0.5 font-mono text-xs font-semibold text-white">
                        {formatTime(ts.sec)}
                      </span>
                      <div className="min-w-0 flex-1">
                        <span className="flex items-center gap-1.5 flex-wrap">
                          {ts.category && (
                            <span className="inline-block rounded-full bg-brand-100 px-2 py-0.5 text-xs font-semibold text-brand-700">
                              {ts.category}
                            </span>
                          )}
                          <span className="text-sm font-medium text-gray-800">{ts.label}</span>
                        </span>
                        {ts.quote && (
                          <span className="mt-0.5 block text-xs italic text-gray-500">
                            &ldquo;{ts.quote}&rdquo;
                          </span>
                        )}
                        {ts.fix && (
                          <span className="mt-1 flex items-start gap-1 text-xs text-brand-700">
                            <span className="shrink-0">→</span>
                            <span>{ts.fix}</span>
                          </span>
                        )}
                      </div>
                      <span className="shrink-0 text-xs font-medium text-brand-600">
                        ▶ 이 순간 보기
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
