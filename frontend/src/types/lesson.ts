/**
 * API 컨트랙트와 1:1 매칭되는 타입 정의.
 * 변경 시 _workspace/01_architect_api-contracts.md 와 동기화 필요.
 */

export type ProcessingStatus = "PENDING" | "PROCESSING" | "DONE" | "FAILED";

/** 17문서 U-1: 레슨 소스 유형. youtube(링크 분석) | upload(영상 파일 직접 업로드) */
export type SourceType = "youtube" | "upload";

export type TranscriptSource =
  | "YOUTUBE_CAPTION"
  | "WHISPER_STT"
  | "UNKNOWN";

export type CourtPosition =
  | "net_left"
  | "net_center"
  | "net_right"
  | "service_line_left"
  | "service_line_center"
  | "service_line_right"
  | "baseline_left"
  | "baseline_center"
  | "baseline_right"
  | "unknown";

export type CourtAnalysisStatus = "PROCESSING" | "DONE" | "FAILED" | null;

export interface CourtTactic {
  sec: number;
  position: CourtPosition;
  position_x: number;
  position_y: number;
  to_position?: string | null;
  to_position_x?: number | null;
  to_position_y?: number | null;
  category: string | null;
  tactic: string;
  label: string;
  quote?: string | null;
}

export type ApiErrorCode =
  | "INVALID_YOUTUBE_URL"
  | "VALIDATION_ERROR"
  | "UNAUTHENTICATED"
  | "FORBIDDEN"
  | "LESSON_NOT_FOUND"
  | "LESSON_ALREADY_EXISTS"
  | "TRANSCRIPT_UNAVAILABLE"
  | "VIDEO_TOO_LONG"
  | "RATE_LIMITED"
  | "INTERNAL_ERROR"
  | "UPSTREAM_ERROR"
  | "SERVICE_UNAVAILABLE";

export interface ApiError {
  code: ApiErrorCode;
  message: string;
  details?: Record<string, unknown>;
  request_id?: string;
}

export interface ApiErrorResponse {
  error: ApiError;
}

export interface ApiSuccessResponse<T> {
  data: T;
}

export interface PaginationMeta {
  limit: number;
  next_cursor: string | null;
  has_more: boolean;
}

export interface PaginatedResponse<T> {
  data: T[];
  pagination: PaginationMeta;
}

export interface LessonTimestamp {
  sec: number;
  type?: "교정" | "드릴" | "전술";
  category?: string | null;
  label: string;
  quote?: string | null;
  problem?: string | null;
  fix?: string | null;
  importance?: "high" | "medium" | "low";
  confidence?: number | null;
  severity?: "critical" | "normal";
  /** 검증 게이트(quote vs STT 전사 원문 fuzzy match) 통과 점수. 0~1, 높을수록
   * 코치 발언 원문과 가깝게 일치. whisper 검증 경로에서만 존재. */
  match_score?: number | null;
}

/** 09문서 1-6: AI 보조 설명 — quote 없어 검증 게이트 대상이 아님.
 * "코치가 실제로 한 말"이 아니라 AI 일반 지식 보충이므로, 렌더링 시
 * 코치 인용 영역과 시각적으로 분리하고 "AI 보조 설명" 라벨을 반드시 노출할 것. */
export interface AiContextNote {
  title: string;
  note: string;
}

/** 15문서 2-A: 인용(quote) 원문을 신뢰하고 노출해도 되는지 판단하는 등급.
 * 골든셋 3건 사람 검토 결과 quote 정밀도 13~20%로 실증되어, 판정 로직 없이
 * 모든 whisper/gemini 경로가 항상 "low"를 반환한다 — null은 구버전(마이그레이션
 * 이전) 레슨이므로 이 역시 "신뢰 불가"로 취급할 것. "low"/null이면 quote 원문
 * 대신 모먼트 내비게이션(시각+카테고리+AI 추정 라벨)으로 렌더링해야 함. */
export type TranscriptQuality = "high" | "low" | null;

/** 13문서 대체카드: 카드/타임스탬프별 사용자 반응. target key → up|down. */
export type ReactionValue = "up" | "down";
export type ReactionsMap = Record<string, ReactionValue>;

export interface LessonReport {
  card1_problem: string | null;
  card2_cueing: string | null;
  card3_action: string | null;
  keywords: string[];
  timestamps: LessonTimestamp[];
  ai_context?: AiContextNote[];
  transcript_quality?: TranscriptQuality;
  full_summary: string | null;
  transcript_source: TranscriptSource;
  transcript_text?: string | null;
  gemini_model: string | null;
  error_message?: string | null;
  completed_at?: string | null;
  progress_step?: number;
  progress_message?: string | null;
  court_tactics?: CourtTactic[] | null;
  court_analysis_status?: CourtAnalysisStatus;
  /** 13문서 대체카드: 셀프 음성 메모 강등 후 채택된 저마찰 대체 기능. */
  reactions?: ReactionsMap;
  quick_note?: string | null;
}

export interface LessonSummary {
  lesson_id: string;
  // 17문서 U-1: 업로드 레슨은 유튜브 링크가 없으므로 nullable.
  youtube_url: string | null;
  youtube_video_id: string | null;
  source_type: SourceType;
  file_hash?: string | null;
  title: string | null;
  lesson_date: string | null;
  thumbnail_url: string | null;
  duration_sec: number | null;
  processing_status: ProcessingStatus;
  lesson_type: string[];
  created_at: string;
  updated_at: string;
}

export interface LessonAnalyzeRequest {
  youtube_url: string;
  title?: string;
  lesson_date?: string;
  analyze_court?: boolean;
}

export interface LessonAnalyzeResponse {
  lesson_id: string;
  processing_status: ProcessingStatus;
  youtube_video_id: string;
  created_at: string;
}

/** 17문서 U-1: POST /lessons/analyze-upload 요청/응답 */
export interface LessonAnalyzeUploadRequest {
  audio: Blob;
  title?: string;
  duration_sec: number;
  file_hash: string;
}

export interface LessonAnalyzeUploadResponse {
  lesson_id: string;
  processing_status: ProcessingStatus;
  created_at: string;
}

export interface LessonDetail extends LessonSummary {
  report: LessonReport | null;
}

/** API 호출 시 발생하는 도메인 에러. lib/api.ts 의 ApiCallError 와 매칭. */
export class ApiCallError extends Error {
  status: number;
  code?: ApiErrorCode | string;
  details?: Record<string, unknown>;

  constructor(
    message: string,
    options: {
      status: number;
      code?: ApiErrorCode | string;
      details?: Record<string, unknown>;
    },
  ) {
    super(message);
    this.name = "ApiCallError";
    this.status = options.status;
    this.code = options.code;
    this.details = options.details;
  }
}
