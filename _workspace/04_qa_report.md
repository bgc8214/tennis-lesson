# QA 검증 리포트 — 오늘의 테니스 (Phase 1 MVP)

> **검증 일자:** 2026-06-03
> **검증 범위:** API 컨트랙트 ↔ Backend 구현 ↔ Frontend 소비 ↔ DB 스키마 4축 정합성
> **검증 방식:** 코드 레벨 추적 + 경계면 교차 비교

---

## 요약

- **Critical: 3개**
- **Medium: 5개**
- **Low: 4개**

핵심 차단 이슈는 **Realtime 구독이 PROCESSING 단계에서 조기 탈출하는 문제**, **`lessons` 테이블에 `processing_status` 컬럼이 없는 채로 frontend가 그 컬럼을 구독하는 문제**, 그리고 **Gemini가 `full_summary`를 생성하지 않는데 contract는 그 필드를 응답으로 약속하는 문제**다.
나머지는 페이지네이션 정확도, 모델 타입의 미세 차이, 스키마 캐스팅 불일치 등 운영 품질 영역.

---

## 발견 이슈 목록

### [QA-C-01] Critical — Frontend Realtime 구독이 PROCESSING 이벤트에서도 즉시 화면 전환

- **파일**:
  - `/Users/boss.back/Desktop/cursor/tennis-lesson/frontend/src/components/UrlInputForm.tsx` (76~86줄)
  - `/Users/boss.back/Desktop/cursor/tennis-lesson/backend/app/routers/lessons.py` (101~107줄)
- **문제**:
  Frontend는 `lesson_reports` 테이블에 대해 `event: "*"`로 구독한 뒤, 어떤 이벤트가 들어와도 `() => finish()`를 호출한다. 그러나 backend `_run_analysis_pipeline`은 분석 시작 직후 `lesson_reports.processing_status`를 `PENDING → PROCESSING`으로 UPDATE 한다. 이 첫 UPDATE 이벤트 즉시 frontend가 `goToLesson()`을 호출해 `/lessons/{id}`로 이동한다.
  결과: 사용자는 분석이 시작되자마자 PROCESSING 상태의 상세 페이지로 강제 이동하고, "AI가 분석 중..." 로딩 카드가 깜빡인 뒤 사라진다. 03_frontend_pages.md §4.1에서 약속한 "둘 중 먼저 DONE/FAILED 감지하면 router.push" 동작이 깨진다.
- **담당**: frontend
- **수정 방향**:
  ```ts
  .on("postgres_changes", { event: "*", ... }, (payload) => {
    const status = (payload.new as { processing_status?: string })?.processing_status;
    if (status === "DONE" || status === "FAILED") finish();
  })
  ```
  `lesson_reports` 핸들러도 `lessons` 핸들러처럼 `status === "DONE" || status === "FAILED"` 가드를 추가한다. event도 굳이 `*`일 필요 없이 `UPDATE`로 좁히는 게 좋다.

---

### [QA-C-02] Critical — `lessons` 테이블에 `processing_status` 컬럼이 없는데 frontend가 그 컬럼을 구독함

- **파일**:
  - `/Users/boss.back/Desktop/cursor/tennis-lesson/_workspace/01_architect_db-schema.sql` (79~92줄: `lessons` DDL)
  - `/Users/boss.back/Desktop/cursor/tennis-lesson/frontend/src/components/UrlInputForm.tsx` (87~100줄)
  - `/Users/boss.back/Desktop/cursor/tennis-lesson/backend/app/routers/lessons.py` (101~104줄)
- **문제**:
  DB 스키마 상 `processing_status`는 `lesson_reports`에만 존재한다. `lessons` 컬럼 목록에는 없다.
  그런데 frontend `UrlInputForm.tsx`는 `lessons` 테이블 UPDATE 이벤트를 구독하면서 `payload.new.processing_status`를 읽는다 — 그 필드는 영원히 `undefined`다.
  또한 backend `_run_analysis_pipeline`도 `sb.table("lessons").update({"updated_at": now()})`만 하고 status를 별도로 기록하지 않는다. (정상이긴 하나 frontend의 lessons 구독 로직 자체가 의미 없는 코드.)
  결국 lessons 채널은 사실상 dead code이며, 폴링/lesson_reports 구독에만 의존한다. 정합성 자체로는 동작하지만, 컨트랙트 일관성과 코드 의미가 깨진다.
- **담당**: frontend (lessons 구독 제거 또는 `lessons.updated_at`만 보고 폴링 트리거로 사용) + 문서 (architect 06 응답 예시는 `processing_status`를 lessons 응답에 포함하지만 그것은 join 계산값임을 명시 필요)
- **수정 방향**:
  - 가장 단순: `lessons` 채널 구독을 제거하고 `lesson_reports`에만 의존한다.
  - 혹은 lessons 핸들러 내부에서 `processing_status` 체크 대신 `getLesson()`을 호출해 최신 상태를 재조회한다.

---

### [QA-C-03] Critical — `report.full_summary` 필드가 contract에는 있지만 Gemini 파이프라인이 생성하지 않음

- **파일**:
  - `/Users/boss.back/Desktop/cursor/tennis-lesson/_workspace/01_architect_api-contracts.md` (3.2 응답 예시 236줄: `full_summary` 포함)
  - `/Users/boss.back/Desktop/cursor/tennis-lesson/backend/app/services/gemini_service.py` (45~78줄: response_schema 및 _normalize_report_dict 어디에도 full_summary 없음)
  - `/Users/boss.back/Desktop/cursor/tennis-lesson/backend/app/routers/lessons.py` (170~186줄: lesson_reports UPDATE에 full_summary 없음)
- **문제**:
  Contract §3.2는 DONE 응답에 `report.full_summary`를 포함하며 Pydantic 모델/타입스크립트 타입도 그 필드를 요구한다. 그러나 backend 파이프라인은 어디에서도 `full_summary`를 생성/저장하지 않는다. `_serialize_report`는 DB의 NULL 값을 그대로 반환한다.
  프론트는 `LessonReport.full_summary: string | null` 로 타입을 받기 때문에 런타임 에러는 없지만, "전체 요약 마크다운" 기능은 완전히 비어 있다. 컨트랙트 위반이며, 03_frontend_pages.md에서 ReportView가 그것을 사용하지 않는 것으로 보아 사실상 미구현 기능.
- **담당**: backend (Gemini 프롬프트/스키마/저장 모두 보강) 또는 architect (Phase 2로 이연시키고 contract에서 제거)
- **수정 방향**:
  Phase 1에서 살리려면:
  1. `gemini_service._build_response_schema`에 `full_summary: {"type":"string"}` 추가, REPORT_SYSTEM_PROMPT에도 `full_summary` 항목 명시.
  2. `_normalize_report_dict`에 `full_summary` 정규화 추가.
  3. `lessons.py` line 173 부근 lesson_reports UPDATE 페이로드에 `"full_summary": report.get("full_summary")` 추가.

  Phase 2로 미루려면 contract와 두 Pydantic/TS 모델에서 `full_summary`를 optional 명시 + 응답 예시에서 제거한다.

---

### [QA-M-01] Medium — `GET /api/v1/lessons` 의 status 필터가 limit+1 슬라이스 *후* Python에서 적용됨

- **파일**: `/Users/boss.back/Desktop/cursor/tennis-lesson/backend/app/routers/lessons.py` (361~419줄)
- **문제**:
  쿼리는 `lessons`를 `created_at desc`로 `limit + 1` 잘라온 뒤 Python에서 `status_filter`로 거른다. 만약 한 페이지(limit=20)에서 모두 PENDING이고 사용자가 `?status=DONE`을 요청하면, 응답 데이터는 `[]`이지만 `has_more=False`로 판정되어 다음 페이지가 있는데도 사용자가 더 못 보게 된다. 또한 `next_cursor`도 빈 배열 기준으로 계산되어 페이지네이션이 망가진다.
  Contract §0.4의 페이지네이션 규약(커서 기반 무한 스크롤)을 깨는 동작.
- **담당**: backend
- **수정 방향**:
  status 필터를 SQL 레벨에서 적용한다. `lesson_reports(processing_status)` 조인 결과를 Supabase의 `.filter("lesson_reports.processing_status", "eq", status_filter)` 또는 inner join으로 처리하고, `limit+1` 슬라이스를 그 *이후*에 한다. 또는 Phase 1 한정으로는 status 파라미터를 비활성화한다고 명시.

---

### [QA-M-02] Medium — `LessonSummary` Pydantic 모델의 `youtube_url`/`thumbnail_url` 타입이 contract와 불일치

- **파일**:
  - `/Users/boss.back/Desktop/cursor/tennis-lesson/_workspace/01_architect_api-contracts.md` (§6, 543~553줄: `youtube_url: HttpUrl`, `thumbnail_url: Optional[HttpUrl]`)
  - `/Users/boss.back/Desktop/cursor/tennis-lesson/backend/app/models/lesson.py` (35~39줄: `youtube_url: str`, `thumbnail_url: Optional[str]`)
- **문제**:
  Contract 6 섹션의 Pydantic 모델은 `HttpUrl`을 사용하는데 실제 구현은 `str`이다. 다만 응답 직렬화는 라우터에서 `dict`를 직접 만들어 `Response`에 담기 때문에 Pydantic 검증을 거치지 않는다. 즉 런타임 영향은 없다.
  Contract 명세와 Pydantic 모델이 어긋나 있어 OpenAPI 스펙 문서와 실제가 어긋날 수 있다.
- **담당**: backend (둘 중 하나로 통일) 또는 architect (Pydantic 모델 정의를 `str`로 갱신)
- **수정 방향**:
  실용적으로는 `str`이 안전하다. URL 검증은 라우터의 `extract_video_id`에서 충분하다. Contract의 Pydantic 모델 예시를 `str`로 수정하는 것을 권장.

---

### [QA-M-03] Medium — `LessonAnalyzeRequest.youtube_url` 검증 실패 시 응답 코드가 `INVALID_YOUTUBE_URL`이 아닌 `VALIDATION_ERROR`로 떨어짐

- **파일**:
  - `/Users/boss.back/Desktop/cursor/tennis-lesson/backend/app/models/lesson.py` (17줄: `youtube_url: HttpUrl`)
  - `/Users/boss.back/Desktop/cursor/tennis-lesson/backend/main.py` (109~120줄: RequestValidationError → 422 VALIDATION_ERROR)
  - `/Users/boss.back/Desktop/cursor/tennis-lesson/_workspace/01_architect_api-contracts.md` (§1.3: 비-YouTube URL → 400 INVALID_YOUTUBE_URL)
- **문제**:
  Pydantic이 `HttpUrl` 검증에서 실패하면(예: `not-a-url`) 422 `VALIDATION_ERROR`가 응답된다. Contract는 비-YouTube URL/잘못된 URL은 400 `INVALID_YOUTUBE_URL`을 약속한다.
  현재 흐름:
  - `https://vimeo.com/...` → Pydantic 통과 → 라우터에서 `extract_video_id` 실패 → 400 `INVALID_YOUTUBE_URL` ✅
  - `not-a-url` → Pydantic 422 `VALIDATION_ERROR` ❌ (contract와 다름)
  - 빈 문자열 → Pydantic 422 ❌
- **담당**: backend
- **수정 방향**:
  옵션 A: `youtube_url: str`으로 받고 라우터 진입 직후 `extract_video_id`로 일괄 처리해 모두 400 `INVALID_YOUTUBE_URL`로 리턴.
  옵션 B: Contract에 "Pydantic 형식 위반은 422 VALIDATION_ERROR" 예외를 명시.

---

### [QA-M-04] Medium — `transcript_source` enum 값이 첫 PROCESSING 단계 응답에서 contract와 일치하지 않을 가능성

- **파일**:
  - `/Users/boss.back/Desktop/cursor/tennis-lesson/backend/app/routers/lessons.py` (327~335줄: report shell INSERT 시 `transcript_source: "UNKNOWN"`)
  - `/Users/boss.back/Desktop/cursor/tennis-lesson/_workspace/01_architect_api-contracts.md` (§3.3 PROCESSING 응답 예시: `report: null`)
- **문제**:
  Contract §3.3은 PROCESSING 시 `report: null`을 약속한다. 그러나 PENDING/PROCESSING 단계에서도 `lesson_reports` shell 행이 실제로는 존재한다. backend `get_lesson`은 `proc_status in ("DONE","FAILED")`일 때만 report 객체를 직렬화하고 그 외엔 `null`을 반환한다 — 이 부분은 contract와 일치한다 ✅.
  단, FAILED 상태에서 `report.transcript_source`가 contract 예시(§3.4)는 `"UNKNOWN"`이지만 backend가 `transcript_source: transcript_source`(즉 `"WHISPER_STT"` 시도 후 실패하면 그대로 유지)를 저장할 수 있어 미세 차이.
- **담당**: minor — backend는 `_run_analysis_pipeline`의 transcript-fail 분기에서 `"UNKNOWN"`을 명시 저장(✅ 138~144줄에서 그렇게 함). 그래서 contract 일치. 본 항목은 Medium → 실제로 통과 항목.
- **수정 방향**: 통과. 확인용으로만 기록.

---

### [QA-M-05] Medium — `analyze_lesson` 라우터가 `LessonAnalyzeResponse` Pydantic 응답 모델을 사용하지 않고 dict를 직접 반환

- **파일**: `/Users/boss.back/Desktop/cursor/tennis-lesson/backend/app/routers/lessons.py` (213~349줄)
- **문제**:
  `@router.post("/analyze")`에 `response_model`이 지정되어 있지 않고 반환 타입도 `Dict[str, Any]`다. `created_at`은 Supabase가 반환한 ISO 문자열을 그대로 통과시킨다. Pydantic 검증/직렬화 단계가 없어 OpenAPI 응답 스키마가 contract §1.2와 자동 동기화되지 않는다.
  같은 문제가 `list_lessons`, `get_lesson`, `delete_lesson`에도 적용된다.
  현재 동작 자체는 문제없으나, Swagger UI 응답 예시가 비어 있고, 향후 모델 변경 시 라우터 코드와 컨트랙트가 어긋나도 잡히지 않는다.
- **담당**: backend
- **수정 방향**:
  `response_model=ApiSuccess[LessonAnalyzeResponse]` 같은 제네릭 래퍼를 정의하거나, `response_model_exclude_none=True`와 함께 명시한다. Phase 1 마감 직전이라면 우선 OpenAPI 문서에 example 응답을 수동으로 등록한다.

---

### [QA-L-01] Low — 컨트랙트의 `types/api.ts`와 `types/lesson.ts` 분리가 frontend에선 단일 파일로 합쳐짐

- **파일**:
  - `/Users/boss.back/Desktop/cursor/tennis-lesson/_workspace/01_architect_api-contracts.md` (§5.1, 5.2: 두 파일로 분리)
  - `/Users/boss.back/Desktop/cursor/tennis-lesson/frontend/src/types/lesson.ts` (모든 타입을 한 파일에 모음)
- **문제**: 위치만 다를 뿐 정의는 동일. 모듈 구성 차이.
- **담당**: frontend (선택)
- **수정 방향**: Phase 2에서 `types/api.ts`로 분리 권장. Phase 1은 그대로 두어도 무방.

---

### [QA-L-02] Low — `RATE_LIMITED` (429) 처리 경로가 backend에 없음

- **파일**:
  - `/Users/boss.back/Desktop/cursor/tennis-lesson/_workspace/01_architect_api-contracts.md` (§0.3: 429 RATE_LIMITED)
  - `/Users/boss.back/Desktop/cursor/tennis-lesson/backend/app/services/gemini_service.py`
- **문제**:
  Gemini 무료 티어 한도(분당 15 RPM, 일 1500) 초과 시 contract는 429 RATE_LIMITED를 응답하기로 했다. 그러나 현재 `_run_analysis_pipeline`은 모든 Gemini 예외를 잡아 `processing_status=FAILED`로 기록만 하고, HTTP 응답에는 영향이 없다 (이 시점엔 이미 202로 응답한 후이므로 정상).
  대신 동기 호출 영역에서 RATE_LIMITED 매핑이 없다. 분석 큐잉 시점은 Gemini를 호출하지 않으므로 실제로는 발생 시나리오가 거의 없다 — 그럼에도 contract에 적힌 코드 카탈로그와의 거리감 정도.
- **담당**: backend (선택) 또는 architect (Phase 1 비대상으로 표시)
- **수정 방향**: Phase 1에서는 RATE_LIMITED를 contract 카탈로그에서 "Phase 2 적용"으로 마킹하거나, `_run_analysis_pipeline`이 Gemini 429를 감지해 `error_message="Gemini 사용량 초과로 분석 실패"`로 정리한다.

---

### [QA-L-03] Low — `transcript_text` 컬럼이 응답에 노출되지 않는 게 contract와 일치하지만 명시 부족

- **파일**:
  - `/Users/boss.back/Desktop/cursor/tennis-lesson/_workspace/01_architect_db-schema.sql` (120줄: `transcript_text text`)
  - `/Users/boss.back/Desktop/cursor/tennis-lesson/backend/app/routers/lessons.py` (68~82줄: `_serialize_report`에 transcript_text 미포함 ✅)
- **문제**: 정상이지만 contract에 "transcript_text는 디버깅용으로 응답에 포함되지 않는다"는 명시가 없다.
- **담당**: architect (선택)
- **수정 방향**: contract에 "private fields not exposed" 섹션 추가.

---

### [QA-L-04] Low — `lesson_reports.full_summary` 컬럼은 DDL에 존재하지만 backend는 read-only로만 다룸

- **파일**:
  - `/Users/boss.back/Desktop/cursor/tennis-lesson/_workspace/01_architect_db-schema.sql` (115줄)
  - `/Users/boss.back/Desktop/cursor/tennis-lesson/backend/app/routers/lessons.py` (76줄: `_serialize_report`에서 read만)
- **문제**: QA-C-03과 동일 원인. Phase 1에서 항상 NULL이 응답되어 신규 사용자가 "전체 요약" 영역을 보지 못한다.
- **담당**: backend
- **수정 방향**: QA-C-03 참조.

---

## 통과 항목

- [x] **DB 스키마의 모든 테이블에 RLS 활성화** — `profiles / lessons / lesson_reports` 모두 `enable row level security` 적용 (DDL 232~234줄).
- [x] **ON DELETE CASCADE FK 제약** — `lesson_reports.lesson_id` → `lessons.id` 및 `lessons.user_id` → `profiles.id` 모두 `on delete cascade` (DDL 81, 103줄).
- [x] **service_role 키가 frontend에 노출되지 않음** — frontend `.env.local.example`에 `NEXT_PUBLIC_SUPABASE_ANON_KEY`만 정의, backend가 별도 환경변수로 service_role 보유.
- [x] **JWT 검증이 `aud="authenticated"`까지 강제** — `app/auth.py` 46~53줄.
- [x] **user_id를 클라이언트 body에서 받지 않고 JWT sub에서 추출** — `analyze_lesson`이 `Depends(get_current_user_id)` 사용, `LessonAnalyzeRequest`에 user_id 필드 부재.
- [x] **본인 리소스 가드** — `get_lesson`/`delete_lesson` 모두 `row.user_id != user_id` 체크 (lessons.py 460~469, 512~520줄).
- [x] **HTTP 상태 코드 매핑** — POST 202, GET 200, DELETE 204, 404/409/422 등 contract 일치.
- [x] **표준 에러 응답 포맷** — `main.py`의 `_build_error_payload`가 `{"error": {code, message, details, request_id}}` 정확히 매핑.
- [x] **Frontend `fetchWithAuth`의 base URL과 prefix** — `${API_BASE_URL}/api/v1/lessons/...` 정확히 사용 (api.ts 84~125줄).
- [x] **Frontend 타입과 backend 응답 shape 일치** — `LessonDetail`, `LessonReport`, `LessonTimestamp`, `LessonSummary` 모두 contract 1:1 매핑.
- [x] **Frontend Realtime 구독 테이블/필터 — lesson_reports 부분** — `filter: "lesson_id=eq.${lessonId}"`, schema `public`, table `lesson_reports`, DB DDL과 일치.
- [x] **`409 LESSON_ALREADY_EXISTS` 응답 시 `details.existing_lesson_id` 포함** — backend lessons.py 280~285줄, frontend UrlInputForm 154~163줄에서 정확히 소비.
- [x] **204 No Content 처리** — frontend `fetchWithAuth`가 `res.status === 204` 분기 처리 (api.ts 56~57줄), backend `delete_lesson`이 `Response(status_code=204)` 반환.
- [x] **하드코딩된 시크릿 없음** — `config.py`가 모든 키를 `Settings`로 환경변수에서 로드, 코드 본문에 API 키 노출 없음.
- [x] **CORS 화이트리스트 환경변수화** — `CORS_ALLOW_ORIGINS` 환경변수, 기본값 `http://localhost:3000`.
- [x] **JSONB 컬럼 형식 가드** — `lesson_reports_keywords_is_array`, `lesson_reports_timestamps_is_array` CHECK 제약.
- [x] **`updated_at` 자동 갱신 트리거** — 3개 테이블 모두 `set_updated_at()` 트리거 부착.
- [x] **`auth.users → profiles` 자동 생성** — `handle_new_user` security definer 트리거.
- [x] **`lessons` 인덱스** — `(user_id, created_at desc)`, `(user_id, youtube_video_id)` 모두 존재 — 대시보드 쿼리/중복 차단 모두 인덱스 히트.
- [x] **Cursor 페이지네이션** — `limit + 1` 패턴으로 `has_more` 판정, contract와 일치.
- [x] **빈 상태/에러 상태 UI** — `NoteCards`가 `card1/card2/card3` 모두 비어있으면 `error_message` 또는 안내 카드를 노출.
- [x] **Whisper 임시파일 정리** — `tempfile.TemporaryDirectory` + `os.remove` + `del result` (stt_service.py 80~107줄).
- [x] **YouTube video_id 정규식 일관** — backend `_VIDEO_ID_RE = ^[A-Za-z0-9_-]{11}$`, contract와 일치.
