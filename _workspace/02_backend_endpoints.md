# [02] Backend Endpoints — 오늘의 테니스 (Phase 1 MVP)

> **Stack:** Python 3.10+, FastAPI, Supabase(Postgres), Gemini 1.5 Flash, Whisper, yt-dlp
> **Base URL (local):** `http://localhost:8000`
> **API Prefix:** `/api/v1`
> **Auth:** `Authorization: Bearer <SUPABASE_JWT>` (HS256, secret = `SUPABASE_JWT_SECRET`)

---

## 1. 구현된 엔드포인트 목록

| Method | Path | 설명 | 인증 | 상태 코드 |
|---|---|---|---|---|
| GET    | `/health`                              | 헬스체크                       | ✗   | 200 |
| GET    | `/`                                    | 루트 안내(개발용)              | ✗   | 200 |
| GET    | `/docs`                                | Swagger UI                     | ✗   | 200 |
| GET    | `/openapi.json`                        | OpenAPI 스펙                   | ✗   | 200 |
| POST   | `/api/v1/lessons/analyze`              | 레슨 분석 큐잉(BackgroundTasks)| ✓   | 202 |
| GET    | `/api/v1/lessons`                      | 내 레슨 목록(커서 페이지네이션)| ✓   | 200 |
| GET    | `/api/v1/lessons/{lesson_id}`          | 레슨 상세 + 리포트             | ✓   | 200 |
| DELETE | `/api/v1/lessons/{lesson_id}`          | 레슨 삭제(리포트 CASCADE)       | ✓   | 204 |

### 처리 상태 흐름

```
POST /lessons/analyze
   └─ INSERT lessons (created)
   └─ INSERT lesson_reports (PENDING)
   └─ BackgroundTask 시작
        ├─ UPDATE lesson_reports → PROCESSING
        ├─ youtube-transcript-api 시도 → 성공: transcript_source=YOUTUBE_CAPTION
        │                                실패: yt-dlp + Whisper 폴백 → WHISPER_STT
        ├─ Gemini 1.5 Flash 호출 → 3카드/keywords/timestamps JSON
        └─ UPDATE lesson_reports → DONE 또는 FAILED
```

---

## 2. curl 예시

> 아래 예시에서 `$JWT`는 Supabase 클라이언트 로그인 후 받은 access_token을 의미한다.
> 로컬에서 발급받는 가장 빠른 방법은 프론트(Next.js)에서 `supabase.auth.getSession()` 후 `data.session.access_token`을 복사하는 것.

### 2.1 헬스체크

```bash
curl -sS http://localhost:8000/health
```

응답:
```json
{ "status": "ok", "app": "tennis-lesson-api", "env": "development", "version": "0.1.0" }
```

### 2.2 레슨 분석 요청 (POST /api/v1/lessons/analyze)

```bash
curl -sS -X POST http://localhost:8000/api/v1/lessons/analyze \
  -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" \
  -d '{
        "youtube_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "title": "2026-06-03 서브 레슨",
        "lesson_date": "2026-06-03"
      }'
```

응답 (202):
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

에러 사례:

```bash
# 잘못된 URL
curl -sS -X POST http://localhost:8000/api/v1/lessons/analyze \
  -H "Authorization: Bearer $JWT" -H "Content-Type: application/json" \
  -d '{"youtube_url":"https://vimeo.com/123"}'
# → 400 INVALID_YOUTUBE_URL

# 동일 영상 중복 등록
# → 409 LESSON_ALREADY_EXISTS (details.existing_lesson_id 포함)
```

### 2.3 내 레슨 목록 (GET /api/v1/lessons)

```bash
# 기본 (limit=20, 최신순)
curl -sS http://localhost:8000/api/v1/lessons \
  -H "Authorization: Bearer $JWT"

# 커서 페이지네이션 + 상태 필터
curl -sS "http://localhost:8000/api/v1/lessons?limit=10&status=DONE&cursor=2026-05-12T08:11:23.456Z" \
  -H "Authorization: Bearer $JWT"
```

응답:
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
  "pagination": { "limit": 10, "next_cursor": null, "has_more": false }
}
```

### 2.4 레슨 상세 (GET /api/v1/lessons/{id})

```bash
curl -sS http://localhost:8000/api/v1/lessons/f3c1ab8e-1234-4ad7-9e21-aaaaaaaaaaaa \
  -H "Authorization: Bearer $JWT"
```

DONE 상태 응답:
```json
{
  "data": {
    "lesson_id": "f3c1ab8e-1234-4ad7-9e21-aaaaaaaaaaaa",
    "processing_status": "DONE",
    "youtube_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    "youtube_video_id": "dQw4w9WgXcQ",
    "title": "2026-06-03 서브 레슨",
    "lesson_date": "2026-06-03",
    "thumbnail_url": "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg",
    "duration_sec": 3540,
    "created_at": "2026-06-03T12:34:56.789Z",
    "updated_at": "2026-06-03T12:39:11.000Z",
    "report": {
      "card1_problem": "토스 시 왼손이 너무 빨리 내려옵니다.",
      "card2_cueing": "라켓 헤드가 떨어질 때까지 왼손 끝으로 하늘을 찌르세요.",
      "card3_action": "다음 개인 연습 시 첫 서브 20개는 무조건 왼손 고정에만 집중할 것.",
      "keywords": ["토스", "왼손유지", "라켓드롭"],
      "timestamps": [
        { "sec": 142, "label": "왼손이 일찍 떨어지는 장면", "quote": "왼손 떨어지지 마세요" }
      ],
      "transcript_source": "YOUTUBE_CAPTION",
      "gemini_model": "gemini-1.5-flash",
      "completed_at": "2026-06-03T12:39:11.000Z"
    }
  }
}
```

PROCESSING 상태에서는 `report: null` 이며, FAILED 상태에서는 `report.error_message`가 포함된다.

### 2.5 레슨 삭제 (DELETE /api/v1/lessons/{id})

```bash
curl -sS -X DELETE http://localhost:8000/api/v1/lessons/f3c1ab8e-1234-4ad7-9e21-aaaaaaaaaaaa \
  -H "Authorization: Bearer $JWT" -i
```

성공 응답: `HTTP/1.1 204 No Content` (본문 없음)

---

## 3. 로컬 개발 서버 실행 방법

### 3.1 사전 요구사항

- Python 3.10 이상 (`python --version`)
- `ffmpeg` (Whisper / yt-dlp 오디오 디코딩에 필요)
  - macOS: `brew install ffmpeg`
- Supabase 프로젝트 1개 (이미 `_workspace/01_architect_db-schema.sql` 적용된 상태여야 함)
- Google AI Studio에서 발급한 Gemini API Key

### 3.2 가상환경 + 의존성 설치

```bash
cd /Users/boss.back/Desktop/cursor/tennis-lesson/backend

python -m venv .venv
source .venv/bin/activate

pip install --upgrade pip
pip install -r requirements.txt
# 또는 PEP 621 기반:
# pip install -e .
```

> `openai-whisper`는 첫 import 시 모델 가중치를 다운로드한다(`base` 약 140MB).
> 첫 호출이 느리지만 이후 캐시(`~/.cache/whisper`)에서 로드된다.

### 3.3 환경변수 설정

```bash
cp .env.example .env
# .env 파일을 열어 아래 값을 채운다
#   SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, SUPABASE_JWT_SECRET
#   GEMINI_API_KEY
```

| 변수 | 필수 | 설명 |
|---|---|---|
| `SUPABASE_URL` | ✓ | `https://<ref>.supabase.co` |
| `SUPABASE_SERVICE_ROLE_KEY` | ✓ | RLS 우회용 service_role 키 (서버 전용, 절대 클라이언트 노출 금지) |
| `SUPABASE_JWT_SECRET` | ✓ | Supabase Auth → JWT Secret |
| `GEMINI_API_KEY` | ✓ | Google AI Studio 발급 키 |
| `WHISPER_MODEL_SIZE` | ✗ | `tiny` / `base` / `small` / `medium` (기본 `base`) |
| `CORS_ALLOW_ORIGINS` | ✗ | 콤마 구분, 기본 `http://localhost:3000` |
| `YTDLP_MAX_DURATION_SEC` | ✗ | 영상 길이 상한(초). 기본 5400 (90분) |

### 3.4 서버 실행

```bash
# 개발 모드 (자동 리로드)
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

기동 후:
- Swagger UI:    http://localhost:8000/docs
- OpenAPI JSON:  http://localhost:8000/openapi.json
- 헬스체크:      http://localhost:8000/health

### 3.5 디렉토리 구조

```
backend/
├── pyproject.toml
├── requirements.txt
├── .env.example
├── main.py                       # FastAPI 진입점
└── app/
    ├── __init__.py
    ├── config.py                 # pydantic-settings 환경 설정
    ├── database.py               # Supabase 클라이언트 싱글톤
    ├── auth.py                   # JWT 검증 의존성 (get_current_user_id)
    ├── models/
    │   ├── lesson.py             # LessonAnalyzeRequest/Response 등
    │   └── report.py             # LessonReport, LessonTimestamp
    ├── routers/
    │   └── lessons.py            # 4개 엔드포인트 + BackgroundTask
    └── services/
        ├── youtube_service.py    # 자막 / video_id / 메타
        ├── stt_service.py        # yt-dlp + Whisper (임시파일 후 즉시 삭제)
        └── gemini_service.py     # Gemini 1.5 Flash + JSON 파싱
```

### 3.6 빠른 동작 확인 시퀀스

```bash
# 1) 서버 기동
uvicorn main:app --reload

# 2) 헬스체크
curl http://localhost:8000/health

# 3) 분석 요청 (JWT 필요)
JWT="..." # supabase 로그인 후 access_token
curl -X POST http://localhost:8000/api/v1/lessons/analyze \
  -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" \
  -d '{"youtube_url":"https://www.youtube.com/watch?v=<id>"}'

# 4) 폴링으로 상태 확인
LESSON_ID="..." # 위 응답의 lesson_id
curl http://localhost:8000/api/v1/lessons/$LESSON_ID \
  -H "Authorization: Bearer $JWT"
```

---

## 4. 에러 응답 포맷

모든 4xx/5xx는 다음 형태:

```json
{
  "error": {
    "code": "LESSON_NOT_FOUND",
    "message": "해당 레슨을 찾을 수 없습니다.",
    "details": { "lesson_id": "..." },
    "request_id": "req_<hex>"
  }
}
```

| HTTP | code |
|---|---|
| 400 | `INVALID_YOUTUBE_URL`, `VALIDATION_ERROR` |
| 401 | `UNAUTHENTICATED` |
| 404 | `LESSON_NOT_FOUND` |
| 409 | `LESSON_ALREADY_EXISTS` |
| 422 | `VALIDATION_ERROR`, `VIDEO_TOO_LONG` |
| 500 | `INTERNAL_ERROR` |
| 502 | `UPSTREAM_ERROR` |

---

## 5. 보안 / 운영 메모

1. **시크릿 비공개**: `.env`는 절대 커밋 금지. `.env.example`만 커밋 대상.
2. **service_role 키 보호**: 클라이언트(브라우저)에 절대 노출 금지. 백엔드 컨테이너의 환경변수로만 주입.
3. **JWT 검증**: HS256으로 `aud=authenticated` 까지 검증한다. 만료/변조 시 401.
4. **RLS 정책**: 백엔드는 service_role로 RLS를 우회하지만, 라우터 레이어에서 `user_id` 매칭을 명시적으로 재확인한다(상세/삭제).
5. **메모리 정리**: STT 처리 후 `tempfile.TemporaryDirectory` 자동 정리 + `os.remove` + `del result`로 큰 numpy 배열을 즉시 회수.
6. **무료 티어 한도**: Gemini 1.5 Flash 분당 15 RPM, 일 1,500 요청. 한도 초과 시 502/429로 graceful fail 후 `lesson_reports.status=FAILED` 기록.
