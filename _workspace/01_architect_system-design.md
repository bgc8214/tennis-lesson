# [01] 시스템 설계서 — 오늘의 테니스 (Phase 1 MVP)

> **작성 목적:** Phase 1 MVP의 전체 시스템 아키텍처, 기술 스택 결정 사유, 디렉토리 구조 및 환경변수를 정의한다. 인프라 비용 0원 제약 하에서 도그푸딩 검증이 가능한 최소 구성을 목표로 한다.

---

## 1. 전체 서비스 아키텍처 다이어그램

### 1.1 상위 레벨 데이터 흐름 (Phase 1 MVP)

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│                            CLIENT (Browser)                                 │
│  ┌────────────────────────────────────────────────────────────────────┐    │
│  │  Next.js 14 (App Router)  +  Tailwind CSS  +  Supabase JS Client   │    │
│  │  - / (Landing/Login)                                               │    │
│  │  - /dashboard (URL 입력 + 레슨 카드 그리드)                        │    │
│  │  - /lessons/[id] (3단 오답노트 리포트 뷰)                          │    │
│  └────────────────────────────────────────────────────────────────────┘    │
└──────────────────┬──────────────────────────────────┬───────────────────────┘
                   │                                  │
       (1) Supabase Auth                  (2) FastAPI REST 호출
       (JWT 발급/세션)                    (Authorization: Bearer <JWT>)
                   │                                  │
                   ▼                                  ▼
┌──────────────────────────────┐   ┌─────────────────────────────────────────┐
│        Supabase Cloud        │   │         FastAPI Backend (Python)        │
│  ┌────────────────────────┐  │   │  ┌───────────────────────────────────┐  │
│  │ Auth (이메일/소셜)     │  │   │  │  Routers (api/v1/lessons/*)       │  │
│  ├────────────────────────┤  │   │  ├───────────────────────────────────┤  │
│  │ PostgreSQL             │◄─┼───┼──│  Service Layer                    │  │
│  │ - profiles             │  │   │  │  - JWT 검증 (Supabase JWKS)        │  │
│  │ - lessons              │  │   │  │  - lesson_orchestrator            │  │
│  │ - lesson_reports       │  │   │  └───────────────────────────────────┘  │
│  ├────────────────────────┤  │   │                  │                      │
│  │ Row Level Security     │  │   │       ┌──────────┴──────────┐           │
│  └────────────────────────┘  │   │       ▼                     ▼           │
└──────────────────────────────┘   │  ┌──────────┐         ┌──────────────┐  │
                                   │  │ Pipeline │         │ Background   │  │
                                   │  │ Steps    │         │ Task (async) │  │
                                   │  └──────────┘         └──────────────┘  │
                                   └────────────────┬────────────────────────┘
                                                    │
                ┌───────────────────────────────────┼───────────────────────────────┐
                ▼                                   ▼                               ▼
   ┌────────────────────────┐         ┌────────────────────────┐      ┌────────────────────────┐
   │ youtube-transcript-api │  fail   │  yt-dlp (audio only)   │      │ Gemini 1.5 Flash API   │
   │ → ko 자막 우선         │ ──────► │ → openai-whisper STT   │ ──►  │ (free tier, 15 RPM)    │
   │ (성공률 ~70%)          │         │ (in-memory wav buffer) │      │ → 3-card JSON 응답     │
   └────────────────────────┘         └────────────────────────┘      └────────────────────────┘
```

### 1.2 단일 레슨 분석 시퀀스 (POST /api/v1/lessons/analyze)

```text
Client                FastAPI               Supabase           youtube-transcript-api / yt-dlp           Gemini

  │ POST analyze (URL)   │                       │                          │                              │
  ├─────────────────────►│                       │                          │                              │
  │                      │ 1. JWT 검증           │                          │                              │
  │                      │ 2. INSERT lessons     │                          │                              │
  │                      │   (status=PENDING)    │                          │                              │
  │                      ├──────────────────────►│                          │                              │
  │                      │                       │                          │                              │
  │ 202 Accepted (lesson_id)                     │                          │                              │
  │◄─────────────────────┤                       │                          │                              │
  │                      │  (BackgroundTask 시작)                           │                              │
  │                      │                                                  │                              │
  │                      │ 3. transcript fetch ────────────────────────────►│                              │
  │                      │◄────────────────── transcript text or 404 ───────┤                              │
  │                      │                                                  │                              │
  │                      │ 4. (404일 때) yt-dlp -f bestaudio ───────────────►│                              │
  │                      │ 5. whisper.transcribe(audio_buffer)              │                              │
  │                      │                                                  │                              │
  │                      │ 6. Gemini 호출 (system + user prompt) ─────────────────────────────────────────►│
  │                      │◄────────────────── 3-card JSON response ───────────────────────────────────────┤
  │                      │                                                  │                              │
  │                      │ 7. UPSERT lesson_reports                                                        │
  │                      │    UPDATE lessons SET status=DONE, title=...                                    │
  │                      ├──────────────────────►│                          │                              │
  │                                                                                                        │
  │ (Client polls GET /lessons/{id} or subscribes to Supabase Realtime channel)                            │
```

---

## 2. 기술 스택 결정 사유

### 2.1 Frontend — Next.js 14 (App Router) + Tailwind CSS

| 결정 | 사유 |
|---|---|
| **Next.js 14 App Router** | (1) 서버 컴포넌트로 Supabase 세션 SSR 처리하여 초기 렌더 빠름. (2) Vercel 배포 시 무료 티어로 인프라 비용 0원. (3) `app/` 디렉토리 라우팅이 `/lessons/[id]` 같은 동적 페이지에 자연스러움. |
| **Tailwind CSS** | (1) 디자인 시스템 별도 구축 부담 없이 모바일 반응형 빠르게 작성. (2) 카드형 UI(7.2 와이어프레임)에 적합한 유틸리티 우선 접근. |
| **Supabase JS (`@supabase/ssr`)** | Auth 토큰을 쿠키 기반 SSR과 클라이언트 양쪽에서 공유. RLS와 결합해 백엔드 API 키 노출 없이 직접 SELECT 가능. |

### 2.2 Backend — Python FastAPI

| 결정 | 사유 |
|---|---|
| **Python FastAPI** | (1) `youtube-transcript-api`, `yt-dlp`, `openai-whisper`, `google-generativeai` 모두 Python 생태계가 성숙. Node 포팅 시 wrapper 비용 큼. (2) Pydantic 기반 타입 안전 + 자동 OpenAPI 스펙 → 프론트 타입 동기화 용이. (3) `BackgroundTasks`로 별도 큐 인프라 없이 비동기 분석 처리 가능 (Phase 1 한정). |
| **uvicorn + gunicorn** | 단일 프로세스 dev (`uvicorn`) → 추후 멀티워커 운영 (`gunicorn -k uvicorn.workers.UvicornWorker`). |
| **httpx** | Gemini, Supabase REST 호출 시 async 일관성. |

### 2.3 AI — Gemini 1.5 Flash (무료 티어)

| 결정 | 사유 |
|---|---|
| **Gemini 1.5 Flash** | (1) 무료 티어 분당 15 RPM / 일 1,500 요청 → 도그푸딩(주 3~5회) 충분. (2) 1M 토큰 컨텍스트로 1시간짜리 자막 전체 주입 가능. (3) `response_mime_type="application/json"` + `response_schema`로 JSON 출력 안정성 확보. |
| **youtube-transcript-api** | 자막 존재 시 비용 0, 처리 0.5초. 1차 시도 채널. |
| **yt-dlp + openai-whisper (small)** | 자막 없을 때만 fallback. `whisper-small` 모델로 한국어 STT 품질/속도 균형. CPU에서도 1시간 영상 5~10분 내 처리. |

### 2.4 DB / Auth / Storage — Supabase

| 결정 | 사유 |
|---|---|
| **Supabase (PostgreSQL)** | (1) Auth + DB + RLS + Realtime이 한 번에 묶여 Phase 1에 최적. (2) 무료 티어 500MB DB, 50K MAU → 초기 충분. (3) JSONB 컬럼으로 keywords/timestamps 유연하게 저장. |
| **RLS (Row Level Security)** | 백엔드를 거치지 않는 클라이언트 직접 SELECT를 허용해도 보안 유지. 프론트에서 레슨 카드 그리드를 RLS만으로 안전하게 조회. |
| **Cloudflare R2 / 영상 저장** | **Phase 1에서는 사용하지 않음.** 영상은 YouTube에 이미 호스팅되어 있고, 오디오는 in-memory로만 처리하여 영구 저장 안 함. → Phase 3에서 도입. |

---

## 3. Phase 1 구현 범위 vs Phase 2/3 미루는 범위

### 3.1 Phase 1 (MVP) — 이번에 구현

- [x] Supabase 이메일 매직링크 로그인
- [x] YouTube URL 입력 → 분석 트리거
- [x] `youtube-transcript-api`로 한글 자막 1차 시도
- [x] 실패 시 `yt-dlp`로 오디오 스트림만 다운로드 → `whisper-small` STT
- [x] Gemini 1.5 Flash로 3단 오답노트(고질병/코치큐잉/액션플랜) JSON 생성
- [x] `lessons` / `lesson_reports` 저장
- [x] 대시보드: 내 레슨 카드 그리드, 검색/정렬 없음
- [x] 레슨 상세: 3카드 + 키워드 태그 + 타임스탬프 리스트(클릭 시 YouTube `?t=` 링크로 이동)
- [x] 레슨 삭제

### 3.2 Phase 2 — 의도적으로 미룸

- [ ] **Vision AI / MediaPipe 관절 분석** — Phase 2 핵심. Phase 1에서는 영상 다운로드 자체를 안 하므로 자연스레 분리.
- [ ] **결제 / 구독 (4,900원 / 9,900원)** — Toss Payments / Stripe 연동.
- [ ] **고질병 누적 대시보드 / 추이 차트** — 데이터 누적 후 의미 있음.
- [ ] **카카오톡 공유 / OG 이미지 생성** — Phase 1에서는 "텍스트 복사" 버튼만.
- [ ] **타임스탬프 클릭 시 영상 인라인 점프** — Phase 1은 외부 YouTube로 새 탭 오픈.

### 3.3 Phase 3 — 의도적으로 미룸

- [ ] **FFmpeg.wasm 온디바이스 오디오 추출 + 직접 업로드** — 유튜브 의존도 해소.
- [ ] **In-Memory 무저장 파이프라인 강화** (Phase 1도 in-memory지만, 정식 명세화는 Phase 3)
- [ ] **B2B 코치 대시보드 / 멀티 테넌시**
- [ ] **모바일 네이티브 앱**
- [ ] **Cloudflare R2 도입** — 자체 업로드가 시작되는 시점부터.
- [ ] **백그라운드 작업 큐 (Celery / Redis)** — Phase 1은 FastAPI BackgroundTasks로 충분, Phase 3 트래픽 발생 시 분리.

---

## 4. 프로젝트 디렉토리 구조

```text
tennis-lesson/
├── README.md
├── pmd.md
├── CLAUDE.md
├── .gitignore
├── .env.example
├── docker-compose.yml                  # (옵션) 로컬 통합 실행
│
├── _workspace/                         # 설계 산출물 (커밋 X 또는 별도 보관)
│   ├── 00_input/
│   ├── 01_architect_system-design.md
│   ├── 01_architect_db-schema.sql
│   └── 01_architect_api-contracts.md
│
├── frontend/                           # Next.js 14 App Router
│   ├── package.json
│   ├── next.config.mjs
│   ├── tailwind.config.ts
│   ├── tsconfig.json
│   ├── .env.local.example
│   ├── public/
│   │   └── logo.svg
│   └── src/
│       ├── app/
│       │   ├── layout.tsx              # 전역 레이아웃 + Supabase 세션 프로바이더
│       │   ├── page.tsx                # 랜딩 (로그인 안 된 경우)
│       │   ├── globals.css
│       │   ├── (auth)/
│       │   │   ├── login/page.tsx
│       │   │   └── callback/route.ts   # Supabase OAuth 콜백
│       │   ├── dashboard/
│       │   │   └── page.tsx            # URL 입력 + 레슨 카드 그리드
│       │   └── lessons/
│       │       └── [id]/page.tsx       # 3단 오답노트 리포트 뷰
│       ├── components/
│       │   ├── ui/                     # 버튼, 카드, 인풋 등 atomic
│       │   ├── lesson/
│       │   │   ├── LessonInputForm.tsx
│       │   │   ├── LessonCard.tsx
│       │   │   ├── LessonGrid.tsx
│       │   │   ├── ReportCardProblem.tsx
│       │   │   ├── ReportCardCueing.tsx
│       │   │   ├── ReportCardAction.tsx
│       │   │   └── TimestampList.tsx
│       │   └── layout/
│       │       ├── Header.tsx
│       │       └── ProfileMenu.tsx
│       ├── lib/
│       │   ├── supabase/
│       │   │   ├── client.ts           # createBrowserClient
│       │   │   ├── server.ts           # createServerClient (RSC용)
│       │   │   └── middleware.ts       # 세션 갱신 미들웨어
│       │   ├── api/
│       │   │   ├── client.ts           # FastAPI fetch wrapper (JWT 자동 첨부)
│       │   │   └── lessons.ts          # 레슨 도메인 호출 함수
│       │   └── utils/
│       │       ├── youtube.ts          # URL 검증/videoId 추출
│       │       └── format.ts           # 날짜/시간 포맷
│       ├── types/
│       │   ├── lesson.ts               # API 컨트랙트와 1:1 매칭
│       │   ├── report.ts
│       │   └── api.ts                  # ApiError, ApiResponse 등
│       └── middleware.ts               # 인증 보호 라우팅
│
├── backend/                            # Python FastAPI
│   ├── pyproject.toml
│   ├── poetry.lock                     # 또는 requirements.txt
│   ├── .env.example
│   ├── Dockerfile
│   ├── README.md
│   └── app/
│       ├── __init__.py
│       ├── main.py                     # FastAPI 인스턴스, CORS, 라우터 등록
│       ├── config.py                   # pydantic-settings, .env 로드
│       ├── api/
│       │   ├── __init__.py
│       │   ├── deps.py                 # get_current_user, get_supabase
│       │   └── v1/
│       │       ├── __init__.py
│       │       ├── router.py           # v1 통합 라우터
│       │       └── endpoints/
│       │           ├── __init__.py
│       │           ├── health.py
│       │           └── lessons.py      # POST/GET/DELETE /lessons
│       ├── core/
│       │   ├── __init__.py
│       │   ├── auth.py                 # JWT 검증 (Supabase JWKS)
│       │   ├── exceptions.py           # 도메인 예외 + 핸들러
│       │   └── logging.py
│       ├── schemas/                    # Pydantic 모델 (= API 컨트랙트)
│       │   ├── __init__.py
│       │   ├── lesson.py               # LessonCreate, LessonOut 등
│       │   ├── report.py               # ReportOut, CardSchema
│       │   └── common.py               # ErrorResponse, Pagination
│       ├── services/
│       │   ├── __init__.py
│       │   ├── lesson_service.py       # 레슨 CRUD 오케스트레이션
│       │   ├── transcript_service.py   # youtube-transcript-api 래퍼
│       │   ├── audio_service.py        # yt-dlp 오디오 스트림 추출
│       │   ├── stt_service.py          # whisper 추론
│       │   └── gemini_service.py       # Gemini 1.5 Flash 호출 + 프롬프트
│       ├── pipelines/
│       │   ├── __init__.py
│       │   └── analyze_pipeline.py     # transcript → (fallback STT) → Gemini → DB
│       ├── repositories/
│       │   ├── __init__.py
│       │   ├── supabase_client.py      # service_role + anon 분기 클라이언트
│       │   ├── lesson_repo.py
│       │   └── report_repo.py
│       ├── prompts/
│       │   └── lesson_report_v1.md     # Gemini 시스템 프롬프트 (버전 관리)
│       └── utils/
│           ├── __init__.py
│           ├── youtube.py              # URL 정규화, videoId 추출
│           └── time.py
│       └── tests/
│           ├── conftest.py
│           ├── test_lessons_api.py
│           ├── test_transcript_service.py
│           └── test_gemini_service.py
│
└── infra/
    ├── supabase/
    │   ├── migrations/
    │   │   └── 20260603_init.sql       # 01_architect_db-schema.sql 내용
    │   └── seed.sql
    └── scripts/
        ├── start_backend.sh
        └── start_frontend.sh
```

---

## 5. 환경변수 (.env.example)

### 5.1 루트 `/.env.example` (전역 공유 변수)

```dotenv
# === Supabase (Frontend & Backend 공통) ===
NEXT_PUBLIC_SUPABASE_URL=https://<your-project-ref>.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=eyJhbGciOi...

# === 환경 구분 ===
APP_ENV=development           # development | staging | production
LOG_LEVEL=INFO
```

### 5.2 `frontend/.env.local.example`

```dotenv
# Supabase (브라우저 노출 가능, anon key)
NEXT_PUBLIC_SUPABASE_URL=https://<your-project-ref>.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=eyJhbGciOi...

# FastAPI 백엔드 베이스 URL
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000

# 사이트 URL (Auth 콜백 redirect 용)
NEXT_PUBLIC_SITE_URL=http://localhost:3000
```

### 5.3 `backend/.env.example`

```dotenv
# === 앱 기본 ===
APP_ENV=development
APP_NAME=tennis-lesson-api
APP_HOST=0.0.0.0
APP_PORT=8000
LOG_LEVEL=INFO

# === CORS ===
CORS_ALLOW_ORIGINS=http://localhost:3000

# === Supabase ===
SUPABASE_URL=https://<your-project-ref>.supabase.co
SUPABASE_ANON_KEY=eyJhbGciOi...                 # 클라이언트 위임용 (선택)
SUPABASE_SERVICE_ROLE_KEY=eyJhbGciOi...         # 서버 전용 (RLS 우회 INSERT/UPDATE)
SUPABASE_JWT_SECRET=super-long-jwt-secret       # JWT 검증 (HS256)
# 또는 JWKS URL 사용 시:
# SUPABASE_JWKS_URL=https://<ref>.supabase.co/auth/v1/.well-known/jwks.json

# === Google Gemini (무료 티어) ===
GEMINI_API_KEY=AIza...
GEMINI_MODEL=gemini-1.5-flash
GEMINI_MAX_OUTPUT_TOKENS=2048
GEMINI_TEMPERATURE=0.4

# === Whisper (로컬 추론) ===
WHISPER_MODEL=small                              # tiny | base | small | medium
WHISPER_DEVICE=cpu                               # cpu | cuda
WHISPER_LANGUAGE=ko

# === yt-dlp ===
YTDLP_FORMAT=bestaudio/best
YTDLP_MAX_DURATION_SEC=5400                      # 90분 제한 (도그푸딩 안전선)

# === 분석 파이프라인 ===
ANALYZE_TIMEOUT_SEC=600                          # 10분
TRANSCRIPT_PREFERRED_LANGUAGES=ko,ko-KR,en
```

---

## 6. 운영/보안 메모 (Phase 1 한정)

1. **JWT 검증 전략**: 백엔드는 Supabase가 발급한 JWT를 `SUPABASE_JWT_SECRET`(HS256)로 검증한다. 검증 후 `sub` 클레임을 `user_id`로 사용한다.
2. **DB 쓰기 권한**: 백엔드는 `SERVICE_ROLE_KEY`로 직접 INSERT/UPDATE한다. 프론트는 anon key + RLS로 SELECT/DELETE만 한다 (정합성 단순화 목적).
3. **시크릿 관리**: `.env.local` / `.env`는 절대 커밋하지 않는다. `.env.example`만 커밋. Vercel / Railway 등 호스팅 환경변수에 동일 키를 등록한다.
4. **무료 티어 한도 모니터링**: Gemini 무료 티어는 분당 15회 / 일 1,500회. 도그푸딩 단계에서는 충분하지만, 한도 초과 시 503으로 graceful fail 처리한다.
5. **Whisper 로컬 추론 비용**: 자체 서버 CPU 사용. Phase 1은 도그푸딩이라 1일 5건 미만 → 인프라 비용 0원 유지 가능. 트래픽 증가 시 Phase 2/3에서 분리.
