# [01] API 컨트랙트 — 오늘의 테니스 (Phase 1 MVP)

> **Base URL:** `{NEXT_PUBLIC_API_BASE_URL}/api/v1`
> **인증:** 모든 엔드포인트는 Supabase JWT 필수. `Authorization: Bearer <access_token>` 헤더 첨부.
> **콘텐츠 타입:** `application/json` 통일.
> **시간 형식:** ISO 8601 UTC (예: `"2026-06-03T12:34:56.789Z"`).
> **OpenAPI:** `GET {API_BASE}/docs` (Swagger UI), `GET {API_BASE}/openapi.json`.

---

## 0. 공통 규약

### 0.1 인증 헤더

```
Authorization: Bearer <supabase_access_token>
Content-Type: application/json
```

JWT 검증 실패 → `401 Unauthorized`. 다른 사용자 리소스 접근 → `403 Forbidden` (실제로는 RLS로 인해 `404 Not Found` 응답이 일반적).

### 0.2 표준 에러 응답

모든 4xx/5xx 응답은 다음 스키마를 따른다.

```json
{
  "error": {
    "code": "LESSON_NOT_FOUND",
    "message": "해당 레슨을 찾을 수 없습니다.",
    "details": {
      "lesson_id": "f3c1ab8e-1234-4ad7-9e21-aaaaaaaaaaaa"
    },
    "request_id": "req_01HXYZ..."
  }
}
```

| 필드 | 설명 |
|---|---|
| `error.code` | 머신 판독용 상수 (UPPER_SNAKE_CASE) |
| `error.message` | 사용자 노출용 한국어 메시지 |
| `error.details` | 컨텍스트별 부가 정보 (선택) |
| `error.request_id` | 트레이싱 ID. 서버 로그와 매칭용 |

### 0.3 에러 코드 카탈로그

| HTTP | code | 의미 |
|---|---|---|
| 400 | `INVALID_YOUTUBE_URL` | URL 형식 오류 또는 video id 추출 실패 |
| 400 | `VALIDATION_ERROR` | Pydantic 스키마 검증 실패 (필드별 details 포함) |
| 401 | `UNAUTHENTICATED` | JWT 미첨부 / 만료 / 변조 |
| 403 | `FORBIDDEN` | 권한 없음 (드물게 발생) |
| 404 | `LESSON_NOT_FOUND` | 존재하지 않거나 본인 소유 아님 |
| 409 | `LESSON_ALREADY_EXISTS` | 동일 user + video_id 의 분석 진행 중/완료 건 존재 |
| 422 | `TRANSCRIPT_UNAVAILABLE` | 자막도 없고 STT도 실패 |
| 422 | `VIDEO_TOO_LONG` | YTDLP_MAX_DURATION_SEC 초과 |
| 429 | `RATE_LIMITED` | Gemini 무료 티어 한도 초과 등 외부 API 제한 |
| 500 | `INTERNAL_ERROR` | 분류 안 된 서버 에러 |
| 502 | `UPSTREAM_ERROR` | YouTube/Gemini/Supabase 등 외부 의존 실패 |
| 503 | `SERVICE_UNAVAILABLE` | 점검/일시 중단 |

### 0.4 페이지네이션 규약 (목록 조회)

쿼리 파라미터: `limit` (default 20, max 50), `cursor` (created_at 기준 ISO 8601 문자열).

응답 메타:

```json
{
  "data": [ /* ... */ ],
  "pagination": {
    "limit": 20,
    "next_cursor": "2026-05-12T08:11:23.456Z",
    "has_more": true
  }
}
```

---

## 1. POST `/api/v1/lessons/analyze`

YouTube URL을 받아 분석 작업을 큐잉한다. **비동기 처리**: 즉시 `202 Accepted`로 `lesson_id`를 반환하고, 클라이언트는 폴링(`GET /lessons/{id}`) 또는 Supabase Realtime 구독으로 완료를 감지한다.

### 1.1 Request

```http
POST /api/v1/lessons/analyze HTTP/1.1
Host: api.example.com
Authorization: Bearer eyJhbGciOi...
Content-Type: application/json
```

```json
{
  "youtube_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
  "title": "2026-06-03 서브 레슨",
  "lesson_date": "2026-06-03"
}
```

| 필드 | 타입 | 필수 | 비고 |
|---|---|---|---|
| `youtube_url` | string (URL) | Y | youtube.com / youtu.be / shorts 모두 허용 |
| `title` | string | N | 비우면 영상 메타에서 자동 추출 시도 |
| `lesson_date` | string (YYYY-MM-DD) | N | 비우면 오늘 날짜 사용 |

### 1.2 Response — 202 Accepted

```json
{
  "data": {
    "lesson_id": "f3c1ab8e-1234-4ad7-9e21-aaaaaaaaaaaa",
    "processing_status": "PENDING",
    "youtube_video_id": "dQw4w9WgXcQ",
    "created_at": "2026-06-03T12:34:56.789Z"
  }
}
```

### 1.3 에러 사례

| HTTP | code | 시나리오 |
|---|---|---|
| 400 | `INVALID_YOUTUBE_URL` | `https://vimeo.com/...` 등 비-YouTube URL |
| 409 | `LESSON_ALREADY_EXISTS` | 동일 영상 분석 중/완료. 응답 details에 기존 `lesson_id` 포함 |
| 422 | `VIDEO_TOO_LONG` | duration > YTDLP_MAX_DURATION_SEC |

```json
{
  "error": {
    "code": "LESSON_ALREADY_EXISTS",
    "message": "이미 분석된 레슨이 있습니다.",
    "details": {
      "existing_lesson_id": "f3c1ab8e-1234-4ad7-9e21-aaaaaaaaaaaa",
      "youtube_video_id": "dQw4w9WgXcQ"
    },
    "request_id": "req_01HXYZ..."
  }
}
```

---

## 2. GET `/api/v1/lessons`

내 레슨 목록을 최신순(`created_at desc`)으로 반환한다.

### 2.1 Request

```http
GET /api/v1/lessons?limit=20&cursor=2026-05-12T08:11:23.456Z HTTP/1.1
Authorization: Bearer eyJhbGciOi...
```

| 쿼리 | 타입 | 필수 | 기본 |
|---|---|---|---|
| `limit` | int (1~50) | N | 20 |
| `cursor` | string (ISO 8601) | N | — |
| `status` | `PENDING` \| `PROCESSING` \| `DONE` \| `FAILED` | N | (모두) |

### 2.2 Response — 200 OK

```json
{
  "data": [
    {
      "lesson_id": "f3c1ab8e-1234-4ad7-9e21-aaaaaaaaaaaa",
      "youtube_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
      "youtube_video_id": "dQw4w9WgXcQ",
      "title": "2026-06-03 서브 레슨",
      "lesson_date": "2026-06-03",
      "thumbnail_url": "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg",
      "duration_sec": 3540,
      "processing_status": "DONE",
      "created_at": "2026-06-03T12:34:56.789Z",
      "updated_at": "2026-06-03T12:39:11.000Z"
    }
  ],
  "pagination": {
    "limit": 20,
    "next_cursor": "2026-05-12T08:11:23.456Z",
    "has_more": true
  }
}
```

> Phase 1 목록은 카드 그리드용으로 가벼운 메타만 반환한다. 3카드 본문은 상세 엔드포인트에서.

---

## 3. GET `/api/v1/lessons/{lesson_id}`

레슨 상세 + 3단 오답노트 리포트.

### 3.1 Request

```http
GET /api/v1/lessons/f3c1ab8e-1234-4ad7-9e21-aaaaaaaaaaaa HTTP/1.1
Authorization: Bearer eyJhbGciOi...
```

### 3.2 Response — 200 OK (DONE)

```json
{
  "data": {
    "lesson_id": "f3c1ab8e-1234-4ad7-9e21-aaaaaaaaaaaa",
    "youtube_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    "youtube_video_id": "dQw4w9WgXcQ",
    "title": "2026-06-03 서브 레슨",
    "lesson_date": "2026-06-03",
    "thumbnail_url": "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg",
    "duration_sec": 3540,
    "processing_status": "DONE",
    "created_at": "2026-06-03T12:34:56.789Z",
    "updated_at": "2026-06-03T12:39:11.000Z",
    "report": {
      "card1_problem": "토스 시 왼손이 너무 빨리 내려옵니다.",
      "card2_cueing": "라켓 헤드가 떨어질 때까지 왼손 끝으로 하늘을 찌르세요.",
      "card3_action": "다음 개인 연습 시 첫 서브 20개는 무조건 왼손 고정에만 집중할 것.",
      "keywords": ["토스", "왼손유지", "라켓드롭"],
      "timestamps": [
        {
          "sec": 142,
          "label": "왼손이 일찍 떨어지는 장면",
          "quote": "왼손 떨어지지 마세요"
        },
        {
          "sec": 387,
          "label": "라켓드롭 부족",
          "quote": "더 떨어뜨리고 던져요"
        }
      ],
      "full_summary": "## 오늘의 핵심\n- 서브 토스 시 왼손 유지가 핵심...",
      "transcript_source": "YOUTUBE_CAPTION",
      "gemini_model": "gemini-1.5-flash",
      "completed_at": "2026-06-03T12:39:11.000Z"
    }
  }
}
```

### 3.3 Response — 200 OK (PENDING / PROCESSING)

`report`는 `null`이고 `processing_status`만 갱신된다.

```json
{
  "data": {
    "lesson_id": "f3c1ab8e-1234-4ad7-9e21-aaaaaaaaaaaa",
    "youtube_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    "youtube_video_id": "dQw4w9WgXcQ",
    "title": "2026-06-03 서브 레슨",
    "lesson_date": "2026-06-03",
    "thumbnail_url": "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg",
    "duration_sec": 3540,
    "processing_status": "PROCESSING",
    "created_at": "2026-06-03T12:34:56.789Z",
    "updated_at": "2026-06-03T12:35:10.000Z",
    "report": null
  }
}
```

### 3.4 Response — 200 OK (FAILED)

```json
{
  "data": {
    "lesson_id": "f3c1ab8e-1234-4ad7-9e21-aaaaaaaaaaaa",
    "processing_status": "FAILED",
    "report": {
      "card1_problem": null,
      "card2_cueing": null,
      "card3_action": null,
      "keywords": [],
      "timestamps": [],
      "transcript_source": "UNKNOWN",
      "error_message": "자막을 가져올 수 없고 STT 추출도 실패했습니다."
    },
    "youtube_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    "youtube_video_id": "dQw4w9WgXcQ",
    "title": "2026-06-03 서브 레슨",
    "lesson_date": "2026-06-03",
    "thumbnail_url": "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg",
    "duration_sec": 3540,
    "created_at": "2026-06-03T12:34:56.789Z",
    "updated_at": "2026-06-03T12:39:11.000Z"
  }
}
```

### 3.5 에러 사례

| HTTP | code | 시나리오 |
|---|---|---|
| 404 | `LESSON_NOT_FOUND` | 존재하지 않거나 본인 소유 아님 |

---

## 4. DELETE `/api/v1/lessons/{lesson_id}`

레슨 + 연결된 리포트를 영구 삭제한다 (`ON DELETE CASCADE`).

### 4.1 Request

```http
DELETE /api/v1/lessons/f3c1ab8e-1234-4ad7-9e21-aaaaaaaaaaaa HTTP/1.1
Authorization: Bearer eyJhbGciOi...
```

### 4.2 Response — 204 No Content

(본문 없음)

### 4.3 에러 사례

| HTTP | code | 시나리오 |
|---|---|---|
| 404 | `LESSON_NOT_FOUND` | 존재하지 않거나 본인 소유 아님 |
| 409 | `LESSON_BUSY` | (선택적) 분석 진행 중인 레슨 삭제 차단 정책 적용 시 |

---

## 5. TypeScript 타입 정의

> 프론트(`frontend/src/types/`)에서 그대로 사용. FastAPI Pydantic 모델과 1:1 동기화한다.

### 5.1 `types/api.ts` — 공통

```ts
export type ProcessingStatus = "PENDING" | "PROCESSING" | "DONE" | "FAILED";

export type TranscriptSource = "YOUTUBE_CAPTION" | "WHISPER_STT" | "UNKNOWN";

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
```

### 5.2 `types/lesson.ts`

```ts
export interface LessonSummary {
  lesson_id: string;
  youtube_url: string;
  youtube_video_id: string;
  title: string | null;
  lesson_date: string | null;        // YYYY-MM-DD
  thumbnail_url: string | null;
  duration_sec: number | null;
  processing_status: ProcessingStatus;
  created_at: string;                // ISO 8601
  updated_at: string;
}

export interface LessonAnalyzeRequest {
  youtube_url: string;
  title?: string;
  lesson_date?: string;              // YYYY-MM-DD
}

export interface LessonAnalyzeResponse {
  lesson_id: string;
  processing_status: ProcessingStatus;
  youtube_video_id: string;
  created_at: string;
}

export interface LessonDetail extends LessonSummary {
  report: LessonReport | null;
}
```

### 5.3 `types/report.ts`

```ts
export interface LessonTimestamp {
  sec: number;
  label: string;
  quote?: string;
}

export interface LessonReport {
  card1_problem: string | null;
  card2_cueing: string | null;
  card3_action: string | null;
  keywords: string[];
  timestamps: LessonTimestamp[];
  full_summary: string | null;
  transcript_source: TranscriptSource;
  gemini_model: string | null;
  error_message?: string | null;
  completed_at?: string | null;
}
```

### 5.4 클라이언트 호출 예시

```ts
// frontend/src/lib/api/lessons.ts
import type {
  LessonAnalyzeRequest,
  LessonAnalyzeResponse,
  LessonDetail,
  LessonSummary,
  PaginatedResponse,
  ApiSuccessResponse,
} from "@/types";

export async function analyzeLesson(
  body: LessonAnalyzeRequest,
  accessToken: string
): Promise<LessonAnalyzeResponse> {
  const res = await fetch(`${process.env.NEXT_PUBLIC_API_BASE_URL}/api/v1/lessons/analyze`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${accessToken}`,
    },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw await toApiError(res);
  const json: ApiSuccessResponse<LessonAnalyzeResponse> = await res.json();
  return json.data;
}

export async function listLessons(
  accessToken: string,
  params: { limit?: number; cursor?: string } = {}
): Promise<PaginatedResponse<LessonSummary>> {
  const qs = new URLSearchParams();
  if (params.limit) qs.set("limit", String(params.limit));
  if (params.cursor) qs.set("cursor", params.cursor);
  const res = await fetch(
    `${process.env.NEXT_PUBLIC_API_BASE_URL}/api/v1/lessons?${qs.toString()}`,
    { headers: { Authorization: `Bearer ${accessToken}` } }
  );
  if (!res.ok) throw await toApiError(res);
  return await res.json();
}

export async function getLesson(id: string, accessToken: string): Promise<LessonDetail> {
  const res = await fetch(`${process.env.NEXT_PUBLIC_API_BASE_URL}/api/v1/lessons/${id}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
  if (!res.ok) throw await toApiError(res);
  const json: ApiSuccessResponse<LessonDetail> = await res.json();
  return json.data;
}

export async function deleteLesson(id: string, accessToken: string): Promise<void> {
  const res = await fetch(`${process.env.NEXT_PUBLIC_API_BASE_URL}/api/v1/lessons/${id}`, {
    method: "DELETE",
    headers: { Authorization: `Bearer ${accessToken}` },
  });
  if (!res.ok && res.status !== 204) throw await toApiError(res);
}

async function toApiError(res: Response): Promise<Error> {
  try {
    const body = (await res.json()) as ApiErrorResponse;
    const err = new Error(body.error.message);
    (err as any).code = body.error.code;
    (err as any).status = res.status;
    (err as any).details = body.error.details;
    return err;
  } catch {
    return new Error(`HTTP ${res.status}`);
  }
}
```

---

## 6. 백엔드 Pydantic 스키마 매핑

> 참고용 Pydantic 모델 윤곽. 실제 코드는 `backend/app/schemas/`에 분할 배치.

```python
# backend/app/schemas/lesson.py
from datetime import date, datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field, HttpUrl

ProcessingStatus = Literal["PENDING", "PROCESSING", "DONE", "FAILED"]
TranscriptSource = Literal["YOUTUBE_CAPTION", "WHISPER_STT", "UNKNOWN"]


class LessonAnalyzeRequest(BaseModel):
    youtube_url: HttpUrl
    title: Optional[str] = Field(default=None, max_length=200)
    lesson_date: Optional[date] = None


class LessonAnalyzeResponse(BaseModel):
    lesson_id: UUID
    processing_status: ProcessingStatus
    youtube_video_id: str
    created_at: datetime


class LessonSummary(BaseModel):
    lesson_id: UUID
    youtube_url: HttpUrl
    youtube_video_id: str
    title: Optional[str]
    lesson_date: Optional[date]
    thumbnail_url: Optional[HttpUrl]
    duration_sec: Optional[int]
    processing_status: ProcessingStatus
    created_at: datetime
    updated_at: datetime


class LessonTimestamp(BaseModel):
    sec: int = Field(ge=0)
    label: str
    quote: Optional[str] = None


class LessonReport(BaseModel):
    card1_problem: Optional[str]
    card2_cueing: Optional[str]
    card3_action: Optional[str]
    keywords: list[str] = []
    timestamps: list[LessonTimestamp] = []
    full_summary: Optional[str] = None
    transcript_source: TranscriptSource = "UNKNOWN"
    gemini_model: Optional[str] = None
    error_message: Optional[str] = None
    completed_at: Optional[datetime] = None


class LessonDetail(LessonSummary):
    report: Optional[LessonReport] = None


# 공통 응답 래퍼
class ApiError(BaseModel):
    code: str
    message: str
    details: Optional[dict] = None
    request_id: Optional[str] = None


class ApiErrorResponse(BaseModel):
    error: ApiError
```

---

## 7. 변경 이력 / 버전 관리

- **v1 (2026-06-03):** 초기 Phase 1 MVP 컨트랙트.
- 향후 Phase 2에서 `/api/v1/lessons/{id}/vision-report` 등 추가 예정. v1 호환성 유지.
