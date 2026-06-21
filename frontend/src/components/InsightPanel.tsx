"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { getSupabaseClient } from "@/lib/supabase";

interface KeywordStat {
  keyword: string;
  lesson_count: number;
  total_mentions: number;
}

interface InsightPanelProps {
  lessonCount: number;
}

export function InsightPanel({ lessonCount }: InsightPanelProps) {
  const [stats, setStats] = useState<KeywordStat[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    if (lessonCount < 3) return;

    const supabase = getSupabaseClient();
    (async () => {
      try {
        const { data } = await supabase.rpc("get_keyword_stats", { p_limit: 8 });
        if (data) setStats(data as KeywordStat[]);
      } finally {
        setIsLoading(false);
      }
    })();
  }, [lessonCount]);

  if (lessonCount < 3) return null;

  const topProblems = stats.slice(0, 3);
  const allKeywords = stats.slice(0, 8);
  const maxMentions = allKeywords[0]?.total_mentions ?? 1;

  return (
    <section className="rounded-3xl border border-brand-200 bg-brand-50 p-5 sm:p-6">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-base font-bold text-gray-900 sm:text-lg">
          나의 테니스 패턴
        </h2>
        <span className="text-xs text-gray-500">레슨 {lessonCount}개 분석 기반</span>
      </div>

      {isLoading ? (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div className="h-32 animate-pulse rounded-2xl bg-brand-100" />
          <div className="h-32 animate-pulse rounded-2xl bg-brand-100" />
        </div>
      ) : stats.length === 0 ? (
        <p className="text-center text-sm text-gray-500">
          완료된 레슨이 쌓이면 패턴이 분석됩니다.
        </p>
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          {/* 반복 고질병 */}
          <div className="rounded-2xl bg-white p-4 shadow-sm">
            <h3 className="mb-3 text-xs font-bold uppercase tracking-widest text-red-500">
              반복 고질병 TOP 3
            </h3>
            {topProblems.length === 0 ? (
              <p className="text-xs text-gray-400">데이터 부족</p>
            ) : (
              <ol className="space-y-2.5">
                {topProblems.map((item, i) => (
                  <li key={item.keyword}>
                    <Link
                      href={`/insights/${encodeURIComponent(item.keyword)}`}
                      className="flex items-center gap-3 rounded-lg p-1 transition-colors hover:bg-red-50"
                    >
                      <span className="inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-red-100 text-xs font-bold text-red-600">
                        {i + 1}
                      </span>
                      <div className="min-w-0 flex-1">
                        <span className="block truncate text-sm font-semibold text-gray-800">
                          {item.keyword}
                        </span>
                        <span className="text-xs text-gray-400">
                          {item.lesson_count}개 레슨에서 반복
                        </span>
                      </div>
                      <span className="shrink-0 text-xs text-brand-500">→</span>
                    </Link>
                  </li>
                ))}
              </ol>
            )}
          </div>

          {/* 키워드 빈도 바 */}
          <div className="rounded-2xl bg-white p-4 shadow-sm">
            <h3 className="mb-3 text-xs font-bold uppercase tracking-widest text-blue-500">
              코치가 자주 한 말
            </h3>
            {allKeywords.length === 0 ? (
              <p className="text-xs text-gray-400">데이터 부족</p>
            ) : (
              <ul className="space-y-2">
                {allKeywords.map((item) => (
                  <li key={item.keyword}>
                    <Link
                      href={`/insights/${encodeURIComponent(item.keyword)}`}
                      className="flex items-center gap-2 rounded p-0.5 transition-colors hover:bg-blue-50"
                    >
                      <span className="w-12 shrink-0 truncate text-right text-xs text-gray-500">
                        #{item.keyword}
                      </span>
                      <div className="flex-1 overflow-hidden rounded-full bg-gray-100">
                        <div
                          className="h-2 rounded-full bg-brand-400 transition-all duration-500"
                          style={{
                            width: `${Math.round((item.total_mentions / maxMentions) * 100)}%`,
                          }}
                        />
                      </div>
                      <span className="w-6 shrink-0 text-xs text-gray-400">
                        {item.total_mentions}
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      )}
    </section>
  );
}
