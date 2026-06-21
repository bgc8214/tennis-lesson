# QA 체크리스트 — 오늘의 테니스 (Phase 1 MVP)

> 04_qa_report.md 와 1:1 매칭. 각 항목은 코드 레벨 추적/대조의 결과.
> ✅ = 통과, ❌ = Critical, ⚠️ = Medium, ℹ️ = Low

---

## 1. API 계약 vs 실제 구현 일치

### 1.1 Request body 필드 매핑

- [✅] `LessonAnalyzeRequest` — frontend `youtube_url` / `title?` / `lesson_date?` ↔ backend `models/lesson.py` 동일
- [✅] `analyze_lesson` 라우터가 `payload.youtube_url`, `payload.title`, `payload.lesson_date` 모두 정확히 소비
- [⚠️] `youtube_url`이 잘못된 형식(non-URL)일 때 → contract는 400 INVALID_YOUTUBE_URL이지만 Pydantic이 422 VALIDATION_ERROR로 응답 → **QA-M-03**

### 1.2 Response shape 매핑

- [✅] `POST /lessons/analyze` → 202 Accepted + `{data: {lesson_id, processing_status, youtube_video_id, created_at}}`
- [✅] `GET /lessons` → 200 + `{data: LessonSummary[], pagination: {limit, next_cursor, has_more}}`
- [✅] `GET /lessons/{id}` → 200 + `{data: LessonDetail}`, PROCESSING/PENDING 시 `report: null`, FAILED 시 `report.error_message` 포함
- [✅] `DELETE /lessons/{id}` → 204 No Content (본문 없음)
- [❌] `report.full_summary` — contract 응답 예시에 포함되어 있으나 backend가 생성/저장 미구현 → **QA-C-03**

### 1.3 HTTP 상태 코드

- [✅] 202 (큐잉), 200 (조회), 204 (삭제), 404 (없거나 본인 아님), 409 (중복), 422 (영상 길이 초과) 매핑 정확
- [✅] 401 UNAUTHENTICATED — JWT 미첨부/만료/변조 시 일관

### 1.4 표준 에러 응답 스키마

- [✅] `{error: {code, message, details?, request_id?}}` 포맷 — `main.py:_build_error_payload` 일치
- [✅] 에러 코드 카탈로그 — INVALID_YOUTUBE_URL, LESSON_NOT_FOUND, LESSON_ALREADY_EXISTS, VIDEO_TOO_LONG 등 모두 코드에서 사용
- [ℹ️] RATE_LIMITED 코드는 카탈로그에 있으나 backend가 매핑하지 않음 → **QA-L-02**

---

## 2. Backend ↔ Frontend 경계면 정합성

### 2.1 타입스크립트 ↔ Pydantic 응답 shape

- [✅] `LessonSummary`, `LessonDetail`, `LessonReport`, `LessonTimestamp`, `ProcessingStatus`, `TranscriptSource` 모두 1:1 매칭
- [⚠️] `LessonSummary.youtube_url` — contract Pydantic은 `HttpUrl`이지만 backend는 `str`. 런타임 영향 없음 → **QA-M-02**

### 2.2 fetchWithAuth URL 경로

- [✅] `${NEXT_PUBLIC_API_BASE_URL}/api/v1/lessons/...` — `/api/v1` prefix 정확히 포함
- [✅] `analyzeLesson` POST 경로 `/api/v1/lessons/analyze`, `getLessons` GET `/api/v1/lessons`, `getLesson` GET `/api/v1/lessons/${id}`, `deleteLesson` DELETE `/api/v1/lessons/${id}`
- [✅] Authorization 헤더 자동 주입 (token 없으면 401 throw)
- [✅] 204 응답 시 JSON parsing 우회 처리

### 2.3 Frontend가 소비하는 응답 필드 vs Backend 반환

- [✅] `lesson_id`, `youtube_url`, `youtube_video_id`, `title`, `lesson_date`, `thumbnail_url`, `duration_sec`, `processing_status`, `created_at`, `updated_at` — `_serialize_lesson_summary`에서 모두 정확히 매핑
- [✅] `report.{card1_problem, card2_cueing, card3_action, keywords, timestamps, transcript_source, gemini_model, error_message, completed_at}` 모두 매핑
- [❌] `report.full_summary` — frontend 타입에 있으나 backend는 항상 `null` → **QA-C-03**

### 2.4 Realtime 구독 테이블/필터

- [❌] `UrlInputForm`의 `lessons` 테이블 구독 — `payload.new.processing_status`를 읽으려 하나 lessons에 그 컬럼이 없음 → **QA-C-02**
- [❌] `UrlInputForm`의 `lesson_reports` 구독이 PROCESSING UPDATE에서도 즉시 finish() 호출 → **QA-C-01**
- [✅] `filter: "lesson_id=eq.${lessonId}"` 형식, schema `public`, table 이름 정확
- [✅] 폴링 폴백(3초/60초) 로직 동작 — `getLesson()`이 contract와 일치하는 응답 사용

---

## 3. DB 스키마 vs 코드 일치

### 3.1 테이블/컬럼명

- [✅] `lessons` SELECT/INSERT/UPDATE/DELETE — backend 코드의 컬럼명(`id, user_id, youtube_url, youtube_video_id, title, lesson_date, thumbnail_url, duration_sec, created_at, updated_at`) 모두 DDL과 일치
- [✅] `lesson_reports` SELECT/INSERT/UPDATE — backend 코드의 컬럼명(`lesson_id, card1_problem, card2_cueing, card3_action, keywords, timestamps, full_summary, processing_status, transcript_source, transcript_text, gemini_model, error_message, created_at, updated_at, completed_at`) 모두 DDL과 일치
- [❌] `lessons` 테이블에 `processing_status` 컬럼 없음 — frontend가 그 컬럼을 Realtime 구독 → **QA-C-02**

### 3.2 RLS 정책

- [✅] `profiles`, `lessons`, `lesson_reports` 모두 RLS 활성화
- [✅] `lessons_select_own/insert_own/update_own/delete_own` 정책 — `user_id = auth.uid()` 가드
- [✅] `lesson_reports_*_own` 정책 — `lesson` 조인 후 `user_id = auth.uid()` 가드
- [✅] `profiles_select_own`, `profiles_update_own` — `id = auth.uid()`. INSERT는 트리거 전용

### 3.3 FK / CASCADE

- [✅] `lessons.user_id → profiles.id ON DELETE CASCADE`
- [✅] `lesson_reports.lesson_id → lessons.id ON DELETE CASCADE` (1:1 unique)
- [✅] `profiles.id → auth.users.id ON DELETE CASCADE`

### 3.4 인덱스

- [✅] `idx_lessons_user_id_created_at_desc` — 메인 대시보드 쿼리(GET /lessons) 인덱스 히트
- [✅] `idx_lessons_user_video` — 중복 차단 쿼리 인덱스 히트
- [✅] `idx_lesson_reports_status_created_at` — 운영 쿼리용
- [✅] `idx_lesson_reports_keywords_gin` — Phase 2용 사전 마련

### 3.5 트리거

- [✅] `set_updated_at()` — 3개 테이블 모두 부착
- [✅] `handle_new_user()` — `auth.users` 가입 시 `profiles` 자동 INSERT, security definer

---

## 4. 보안 체크

### 4.1 환경변수 / 시크릿 관리

- [✅] `GEMINI_API_KEY`, `SUPABASE_*` 모두 `app/config.py`의 `Settings`에서 로드
- [✅] 코드 본문에 API 키 / URL 하드코딩 없음 (라우터/서비스 모두 `get_settings()` 경유)
- [✅] `.env.example` / `.env.local.example`만 커밋 대상으로 안내

### 4.2 user_id 추출

- [✅] backend `analyze_lesson`은 `user_id: str = Depends(get_current_user_id)` — JWT의 `sub`에서만 추출
- [✅] `LessonAnalyzeRequest`에 `user_id` 필드 없음 — body 주입 차단
- [✅] `get_lesson`/`delete_lesson`도 라우터 레이어에서 `row.user_id != user_id` 명시 재확인 (RLS + 라우터 이중 방어)

### 4.3 Frontend 키 노출

- [✅] frontend `.env.local.example`은 `NEXT_PUBLIC_SUPABASE_ANON_KEY`만 정의 (anon, RLS 보호)
- [✅] frontend 코드에 `service_role` 키 사용 없음
- [✅] backend `database.py`는 `SUPABASE_SERVICE_ROLE_KEY`만 사용, 서버 측 한정

### 4.4 JWT 검증

- [✅] HS256 + `audience="authenticated"` + `verify_aud=True`
- [✅] 헤더 형식 `Bearer <token>` 강제, sub 누락 시 401

### 4.5 CORS

- [✅] `CORS_ALLOW_ORIGINS` 환경변수로 화이트리스트, 기본 `http://localhost:3000`

---

## 5. 핵심 플로우 코드 추적

### 5.1 YouTube URL 입력 → 분석 요청

- [✅] `UrlInputForm.handleSubmit` → `analyzeLesson({youtube_url})` 호출
- [✅] `lib/api.ts:analyzeLesson` → POST `/api/v1/lessons/analyze` + JWT
- [✅] backend `analyze_lesson` → video_id 추출 → 메타 조회 → 길이 가드 → 중복 검사 → lessons + lesson_reports INSERT → BackgroundTask 큐잉 → 202 응답
- [✅] 응답 `lesson_id` 정확히 frontend에 전달

### 5.2 폴링/Realtime 대기

- [❌] frontend `lesson_reports` 채널이 PROCESSING UPDATE에서도 즉시 navigate → **QA-C-01**
- [❌] frontend `lessons` 채널이 존재하지 않는 컬럼 구독 → **QA-C-02**
- [✅] 폴링 폴백(getLesson 3초 간격, 60초 timeout)은 `processing_status === DONE/FAILED`만 navigate — 정합

### 5.3 리포트 표시

- [✅] `/lessons/[id]` 페이지가 `getLesson()` 호출 → `LessonDetail` 수신
- [✅] `ReportView/NoteCards`가 `report.card1_problem/card2_cueing/card3_action/keywords` 직접 소비, 빈 데이터 시 `error_message` 안내
- [❌] `report.full_summary` 항상 NULL → 전체 요약 영역 미동작 → **QA-C-03**

### 5.4 데이터 끊김 지점 점검

- [❌] PROCESSING UPDATE → frontend가 즉시 navigate → 사용자가 결과를 못 보고 PROCESSING 페이지로 이동 (QA-C-01)
- [✅] `/lessons/[id]`에서도 자체 폴링/Realtime으로 결과 도달은 가능 — 사용자 경험은 손상되지만 데이터 끊김은 없음
- [✅] 401/403 시 ApiCallError로 변환 → 프론트 토스트/에러 화면

---

## 6. 운영/품질

- [⚠️] `GET /lessons?status=DONE` 페이지네이션 — Python-side 필터로 인한 빈 페이지 가능 → **QA-M-01**
- [⚠️] `analyze_lesson`에 `response_model` 미지정 — OpenAPI 스키마 자동 동기화 부재 → **QA-M-05**
- [ℹ️] `transcript_text` 컬럼이 응답에 노출되지 않는 점은 contract에 명시되지 않음 → **QA-L-03**
- [ℹ️] `types/api.ts` vs `types/lesson.ts` 분리 미적용 → **QA-L-01**

---

## 7. 최종 게이트

- ❌ Critical 3건 미해결 시 Phase 1 릴리즈 불가 (QA-C-01, QA-C-02, QA-C-03)
- ⚠️ Medium 5건은 릴리즈 직후 핫픽스 또는 Phase 1.1 대상
- ℹ️ Low 4건은 Phase 2 백로그
