/**
 * 데이터 접근 레이어.
 *
 * - 조회(getLessons, getLesson): Supabase JS 클라이언트로 직접 쿼리 → 백엔드 불필요
 * - 분석(analyzeLesson): 로컬 FastAPI 백엔드 경유 (Gemini/yt-dlp 파이프라인)
 * - 삭제(deleteLesson): Supabase JS 클라이언트로 직접 삭제
 */

import {
  ApiCallError,
  type ApiErrorResponse,
  type ApiSuccessResponse,
  type LessonAnalyzeRequest,
  type LessonAnalyzeResponse,
  type LessonDetail,
  type LessonSummary,
  type PaginatedResponse,
} from "@/types/lesson";
import { getAccessToken, getSupabaseClient } from "@/lib/supabase";

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

// ─────────────────────────────────────────────────────────────────────
// 백엔드 호출 (분석 전용)
// ─────────────────────────────────────────────────────────────────────

async function fetchWithAuth<T>(
  path: string,
  options: Omit<RequestInit, "body"> & { body?: unknown } = {},
): Promise<T> {
  const { body, headers, ...rest } = options;
  const token = await getAccessToken();

  const finalHeaders: Record<string, string> = {
    "Content-Type": "application/json",
    ...(headers as Record<string, string> | undefined),
  };
  if (token) finalHeaders.Authorization = `Bearer ${token}`;

  const url = path.startsWith("http") ? path : `${API_BASE_URL}${path}`;
  const res = await fetch(url, {
    ...rest,
    headers: finalHeaders,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });

  if (res.status === 204) return undefined as T;

  let parsed: unknown = null;
  const text = await res.text();
  if (text) {
    try { parsed = JSON.parse(text); } catch { /* noop */ }
  }

  if (!res.ok) {
    const errBody = parsed as ApiErrorResponse | null;
    if (errBody?.error) {
      throw new ApiCallError(errBody.error.message, {
        status: res.status,
        code: errBody.error.code,
        details: errBody.error.details,
      });
    }
    throw new ApiCallError(`HTTP ${res.status}`, { status: res.status });
  }

  return parsed as T;
}

/** POST /api/v1/lessons/analyze — 로컬 백엔드 필요 */
export async function analyzeLesson(
  payload: LessonAnalyzeRequest,
): Promise<LessonAnalyzeResponse> {
  const res = await fetchWithAuth<ApiSuccessResponse<LessonAnalyzeResponse>>(
    "/api/v1/lessons/analyze",
    { method: "POST", body: payload },
  );
  return res.data;
}

// ─────────────────────────────────────────────────────────────────────
// Supabase 직접 조회 (백엔드 불필요)
// ─────────────────────────────────────────────────────────────────────

/** lessons + lesson_reports 를 Supabase에서 직접 읽어 LessonSummary 로 변환 */
function extractReport(raw: unknown): Record<string, unknown> | undefined {
  if (!raw) return undefined;
  if (Array.isArray(raw)) return (raw[0] as Record<string, unknown>) ?? undefined;
  return raw as Record<string, unknown>;
}

function rowToSummary(row: Record<string, unknown>): LessonSummary {
  const rep = extractReport(row.lesson_reports);

  return {
    lesson_id: row.id as string,
    youtube_url: row.youtube_url as string,
    youtube_video_id: row.youtube_video_id as string,
    title: (row.title as string | null) ?? null,
    lesson_date: (row.lesson_date as string | null) ?? null,
    thumbnail_url: (row.thumbnail_url as string | null) ?? null,
    duration_sec: (row.duration_sec as number | null) ?? null,
    lesson_type: (row.lesson_type as string[]) ?? [],
    processing_status: ((rep?.processing_status as string) ?? "PENDING") as LessonSummary["processing_status"],
    created_at: row.created_at as string,
    updated_at: row.updated_at as string,
  };
}

/** 전체 레슨 개수 조회 */
export async function getLessonCount(lesson_type?: string): Promise<number> {
  const supabase = getSupabaseClient();
  let q = supabase
    .from("lessons")
    .select("id", { count: "exact", head: true })
    .eq("is_hidden", false);
  if (lesson_type) q = q.contains("lesson_type", [lesson_type]);
  const { count } = await q;
  return count ?? 0;
}

/** GET lessons — Supabase 직접 쿼리 */
export async function getLessons(params: {
  limit?: number;
  offset?: number;
  lesson_type?: string;
} = {}): Promise<PaginatedResponse<LessonSummary>> {
  const supabase = getSupabaseClient();
  const limit = params.limit ?? 20;
  const offset = params.offset ?? 0;

  let q = supabase
    .from("lessons")
    .select("id, youtube_url, youtube_video_id, title, lesson_date, thumbnail_url, duration_sec, lesson_type, created_at, updated_at, lesson_reports(processing_status)")
    .order("lesson_date", { ascending: false, nullsFirst: false })
    .order("created_at", { ascending: false })
    .range(offset, offset + limit);  // limit+1개 가져와서 has_more 판정

  q = q.eq("is_hidden", false);
  if (params.lesson_type) q = q.contains("lesson_type", [params.lesson_type]);

  const { data, error } = await q;

  if (error) {
    throw new ApiCallError(error.message, { status: 502, code: "UPSTREAM_ERROR" });
  }

  const rows = (data ?? []) as Record<string, unknown>[];
  const hasMore = rows.length > limit;
  const sliced = hasMore ? rows.slice(0, limit) : rows;

  return {
    data: sliced.map(rowToSummary),
    pagination: { limit, next_cursor: hasMore ? String(offset + limit) : null, has_more: hasMore },
  };
}

/** GET lessons/:id — Supabase 직접 쿼리 */
export async function getLesson(id: string): Promise<LessonDetail> {
  const supabase = getSupabaseClient();

  const { data, error } = await supabase
    .from("lessons")
    .select("id, user_id, youtube_url, youtube_video_id, title, lesson_date, thumbnail_url, duration_sec, lesson_type, created_at, updated_at, lesson_reports(*)")
    .eq("id", id)
    .limit(1)
    .single();

  if (error || !data || (data as Record<string, unknown>).is_hidden === true) {
    throw new ApiCallError("해당 레슨을 찾을 수 없습니다.", { status: 404, code: "LESSON_NOT_FOUND" });
  }

  const row = data as Record<string, unknown>;
  const rep = extractReport(row.lesson_reports);

  const summary = rowToSummary(row);

  return {
    ...summary,
    report: rep
      ? {
          card1_problem: (rep.card1_problem as string | null) ?? null,
          card2_cueing: (rep.card2_cueing as string | null) ?? null,
          card3_action: (rep.card3_action as string | null) ?? null,
          keywords: (rep.keywords as string[]) ?? [],
          timestamps: (rep.timestamps as LessonDetail["report"] extends null ? never : NonNullable<LessonDetail["report"]>["timestamps"]) ?? [],
          full_summary: (rep.full_summary as string | null) ?? null,
          transcript_source: (rep.transcript_source as LessonDetail["report"] extends null ? never : NonNullable<LessonDetail["report"]>["transcript_source"]) ?? "UNKNOWN",
          gemini_model: (rep.gemini_model as string | null) ?? null,
          error_message: (rep.error_message as string | null) ?? null,
          completed_at: (rep.completed_at as string | null) ?? null,
          progress_step: (rep.progress_step as number) ?? 0,
          progress_message: (rep.progress_message as string | null) ?? null,
          transcript_text: (rep.transcript_text as string | null) ?? null,
          court_tactics: (rep.court_tactics as import("@/types/lesson").CourtTactic[] | null) ?? null,
          court_analysis_status: (rep.court_analysis_status as import("@/types/lesson").CourtAnalysisStatus | null) ?? null,
        }
      : null,
  };
}

/** DELETE lessons/:id — Supabase 직접 삭제 */
export async function deleteLesson(id: string): Promise<void> {
  const supabase = getSupabaseClient();
  const { error } = await supabase.from("lessons").delete().eq("id", id);
  if (error) {
    throw new ApiCallError(error.message, { status: 502, code: "UPSTREAM_ERROR" });
  }
}

export interface KeywordTimestampEntry {
  lesson_id: string;
  lesson_title: string | null;
  lesson_date: string | null;
  thumbnail_url: string | null;
  youtube_video_id: string;
  youtube_url: string;
  created_at: string;
  timestamps: { sec: number; category?: string | null; label: string; quote?: string | null; fix?: string | null }[];
}

/** 특정 키워드가 등장한 레슨 목록 + 관련 타임스탬프 */
export async function getLessonsByKeyword(keyword: string): Promise<KeywordTimestampEntry[]> {
  const supabase = getSupabaseClient();

  const { data, error } = await supabase
    .from("lessons")
    .select("id, title, lesson_date, thumbnail_url, youtube_video_id, youtube_url, created_at, lesson_reports(keywords, timestamps, processing_status)")
    .order("created_at", { ascending: false });

  if (error) throw new ApiCallError(error.message, { status: 502, code: "UPSTREAM_ERROR" });

  const rows = (data ?? []) as Record<string, unknown>[];
  const result: KeywordTimestampEntry[] = [];

  for (const row of rows) {
    const rep = extractReport(row.lesson_reports);
    if (!rep || rep.processing_status !== "DONE") continue;

    const keywords = (rep.keywords as string[]) ?? [];
    if (!keywords.map((k) => k.toLowerCase()).includes(keyword.toLowerCase())) continue;

    const allTimestamps = (rep.timestamps as { sec: number; label: string; quote?: string }[]) ?? [];
    // 키워드와 관련된 타임스탬프 필터 (label/quote에 키워드 포함), 없으면 전체
    const filtered = allTimestamps.filter(
      (ts) =>
        ts.label?.toLowerCase().includes(keyword.toLowerCase()) ||
        ts.quote?.toLowerCase().includes(keyword.toLowerCase()),
    );

    result.push({
      lesson_id: row.id as string,
      lesson_title: (row.title as string | null) ?? null,
      lesson_date: (row.lesson_date as string | null) ?? null,
      thumbnail_url: (row.thumbnail_url as string | null) ?? null,
      youtube_video_id: row.youtube_video_id as string,
      youtube_url: row.youtube_url as string,
      created_at: row.created_at as string,
      timestamps: filtered.length > 0 ? filtered : allTimestamps.slice(0, 3),
    });
  }

  return result;
}
