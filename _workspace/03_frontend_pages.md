# [03] Frontend 구현 산출물 — 오늘의 테니스 (Phase 1 MVP)

> Next.js 14 App Router + Tailwind CSS + Supabase JS 기반 프론트엔드 구현 결과를 정리한 문서.

---

## 1. 구현된 페이지/컴포넌트 목록

### 1.1 페이지 (App Router)

| 경로 | 파일 | 역할 |
|---|---|---|
| `/` | `src/app/page.tsx` | 메인 대시보드. URL 입력 폼 + 최근 레슨 카드 그리드. 미로그인 시 로그인 유도 카드 표시. |
| `/auth` | `src/app/auth/page.tsx` | 로그인/회원가입. 매직링크 / 비밀번호 로그인 / 회원가입 3가지 모드 토글. |
| `/lessons/[id]` | `src/app/lessons/[id]/page.tsx` | 레슨 리포트 상세. PENDING/PROCESSING/DONE/FAILED 4가지 상태 분기 렌더. Supabase Realtime + 폴링으로 완료 감지. |

### 1.2 레이아웃 / 글로벌

| 파일 | 역할 |
|---|---|
| `src/app/layout.tsx` | 루트 레이아웃. ToastProvider, Header, Footer 배치. metadata/viewport 정의. |
| `src/app/globals.css` | Tailwind base + 전역 스타일. focus-visible 링, scrollbar utility. |

### 1.3 컴포넌트

| 컴포넌트 | 파일 | 역할 |
|---|---|---|
| `UrlInputForm` | `src/components/UrlInputForm.tsx` | YouTube URL 입력 → POST `/api/v1/lessons/analyze`. 202 받으면 Supabase Realtime 구독 + 폴링 폴백(3초 간격 / 60초 한도)으로 완료 감지 후 `/lessons/{id}` 이동. `LESSON_ALREADY_EXISTS` 에러 시 기존 레슨으로 라우팅. |
| `LessonCard` / `LessonCardSkeleton` | `src/components/LessonCard.tsx` | 레슨 이력 카드. 썸네일/제목/날짜/상태 배지. 우상단 호버 시 삭제 버튼 노출(confirm 후 DELETE). 스켈레톤 변형 export. |
| `ReportView` | `src/components/ReportView/index.tsx` | 리포트 좌우 2단 레이아웃 컨테이너 (lg+). 모바일에서는 세로 스택. 좌측 sticky 비디오, 우측 카드+공유. |
| `VideoPlayer` | `src/components/ReportView/VideoPlayer.tsx` | YouTube IFrame Player API 임베드. 타임스탬프 클릭 시 `seekTo()` 호출. severity(critical/normal)에 따라 빨강/노랑 좌측 보더. API 로드 실패 시 새 탭 `?t=` 폴백. |
| `NoteCards` | `src/components/ReportView/NoteCards.tsx` | 3단 카드: 1.고질병(빨강) 2.코치 큐잉(파랑, 이탤릭 따옴표) 3.액션 플랜(브랜드 그린). 키워드 태그 칩. 빈 리포트면 안내 메시지. |
| `ShareButtons` | `src/components/ReportView/ShareButtons.tsx` | 카카오톡 공유 (Kakao SDK 동적 로드, `NEXT_PUBLIC_KAKAO_JS_KEY` 필요), 텍스트 복사 (Clipboard API + execCommand 폴백). 토스트 알림. |
| `Header` | `src/components/ui/Header.tsx` | 글로벌 헤더. 로고 + 로그인/프로필 메뉴. 세션 상태 실시간 추적. 로그아웃 시 `/auth` 이동. |
| `LoadingSpinner` | `src/components/ui/LoadingSpinner.tsx` | 인라인 스피너 (sm/md/lg, optional label). |
| `Toast` / `ToastProvider` / `useToast` | `src/components/ui/Toast.tsx` | 컨텍스트 기반 토스트. success/error/info 3개 variant. 3초 자동 dismiss. |

### 1.4 라이브러리 / 타입

| 파일 | 내용 |
|---|---|
| `src/lib/api.ts` | `fetchWithAuth` 래퍼 + `analyzeLesson` / `getLessons` / `getLesson` / `deleteLesson`. 표준 에러 응답을 `ApiCallError` 로 변환. |
| `src/lib/supabase.ts` | `createBrowserClient` 싱글턴 + `getAccessToken()` 헬퍼. |
| `src/types/lesson.ts` | API 컨트랙트 1:1 매핑 타입(LessonSummary/LessonDetail/LessonReport/LessonTimestamp 등) + `ApiCallError` 클래스. |

### 1.5 설정 파일

| 파일 | 역할 |
|---|---|
| `package.json` | 의존성 + 스크립트 |
| `tsconfig.json` | strict TS, `@/*` alias |
| `tailwind.config.ts` | brand 컬러 팔레트(green-500 베이스), Pretendard/시스템 폰트, fade-in 애니메이션 |
| `next.config.ts` | reactStrictMode, YouTube 썸네일 호스트 허용 |
| `postcss.config.js` | tailwindcss + autoprefixer |
| `.env.local.example` | 필요한 환경변수 템플릿 |
| `.gitignore` | Node/Next 표준 |

---

## 2. 로컬 개발 서버 실행 방법

### 2.1 사전 준비

- Node.js 18.18+ (또는 20+)
- 백엔드 FastAPI 서버가 `http://localhost:8000` 에서 동작 중이어야 함 (선택: 미실행 시 API 호출만 실패하고 UI 자체는 렌더됨)
- Supabase 프로젝트가 생성되어 있어야 함

### 2.2 단계

```bash
cd /Users/boss.back/Desktop/cursor/tennis-lesson/frontend

# 1. 환경변수 파일 복사 후 값 채우기
cp .env.local.example .env.local
# .env.local 편집 — Supabase URL, anon key, API base URL 입력

# 2. 의존성 설치
npm install

# 3. 개발 서버 실행
npm run dev
```

브라우저에서 `http://localhost:3000` 접속.

### 2.3 기타 스크립트

```bash
npm run build        # 프로덕션 빌드
npm run start        # 프로덕션 서버 (build 후)
npm run type-check   # TypeScript 타입 체크
npm run lint         # next lint
```

---

## 3. 환경변수 설정 방법

`frontend/.env.local` 파일에 다음 키를 작성한다 (`.env.local.example` 복사 후 수정).

| 키 | 필수 | 예시 / 설명 |
|---|---|---|
| `NEXT_PUBLIC_SUPABASE_URL` | Y | `https://xxx.supabase.co` — Supabase 대시보드 → Project Settings → API |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Y | `eyJhbGciOi...` — anon public key |
| `NEXT_PUBLIC_API_BASE_URL` | Y | `http://localhost:8000` — FastAPI 베이스 URL |
| `NEXT_PUBLIC_SITE_URL` | Y | `http://localhost:3000` — Auth 매직링크 redirect 대상 |
| `NEXT_PUBLIC_KAKAO_JS_KEY` | N | 카카오 개발자 콘솔 JavaScript 키 (없으면 카카오 공유 버튼이 안내 토스트만 표시) |

> `NEXT_PUBLIC_` 프리픽스가 붙은 변수만 클라이언트 번들에 포함된다. anon key 는 RLS 로 보호되므로 공개되어도 무방.

### 3.1 Supabase 측 추가 설정

1. **Auth → URL Configuration**: Site URL 에 `http://localhost:3000` 등록, Redirect URLs 에 `http://localhost:3000/auth` 추가.
2. **Auth → Providers**: Email Provider 활성화 (Magic Link / Password 모두 사용).
3. **Realtime**: `lessons`, `lesson_reports` 테이블에서 Realtime publication 활성화 (Database → Replication). 미활성화여도 폴링 폴백으로 동작.
4. **RLS**: `01_architect_db-schema.sql` 의 정책이 적용되어 있어야 본인 레슨만 SELECT/DELETE 가능.

---

## 4. 주요 동작 흐름

### 4.1 분석 요청 (UrlInputForm)

```
[입력] → POST /api/v1/lessons/analyze
       → 202 Accepted (lesson_id, status=PENDING)
       → Supabase Realtime 구독 시작 (lesson_reports.lesson_id=eq.{id})
       → 동시에 3초 간격 폴링 (60초 타임아웃 시 강제 이동)
       → 둘 중 먼저 DONE/FAILED 감지하면 router.push(`/lessons/${id}`)
```

### 4.2 레슨 상세 로딩 (lessons/[id])

```
[페이지 진입] → GET /api/v1/lessons/{id}
              → status === DONE  : <ReportView/> 렌더
              → status === FAILED: 실패 안내 + 재시도 CTA
              → status === PENDING/PROCESSING:
                  스피너 + 4초 간격 폴링 + Realtime 구독
                  완료되면 자동으로 ReportView 로 전환
```

### 4.3 인증 가드

- `/` 페이지에서 미로그인 사용자는 URL 입력 폼 대신 로그인 CTA 노출.
- `/lessons/[id]` 진입 시 미로그인이면 API 호출이 401 → 에러 화면.
- 더 강한 가드(미들웨어 기반 라우팅 보호)는 Phase 2 에서 SSR 도입 시 추가 예정.

---

## 5. 디자인 원칙 적용 사항

- **모바일 퍼스트**: 모든 컴포넌트가 375px 기준으로 1차 설계. 데스크톱은 `sm:` `lg:` 브레이크포인트로 확장 (예: ReportView 의 `lg:grid-cols-[1.1fr_1fr]`).
- **브랜드 컬러**: Tailwind `brand-*` 팔레트(green-500 계열)를 모든 액션 버튼/포커스 링에 일관 적용.
- **상태 처리**: 모든 버튼이 hover / disabled / loading 3가지 상태 시각화 (LoadingSpinner 활용).
- **빈 상태**: 대시보드 빈 상태 온보딩 ("첫 레슨을 복기해보세요!"), 레슨 빈 리포트 안내, FAILED 안내 등 3종.
- **로딩 상태**: LessonCardSkeleton (대시보드), 인라인 스피너 (입력/삭제), 진행 중 placeholder (상세).
- **접근성**: aria-live, role=status, focus-visible ring, 모든 이미지에 alt.

---

## 6. 알려진 제약 / 후속 작업

| 항목 | 현황 | 후속 |
|---|---|---|
| SSR 인증 보호 | 클라이언트 가드만 사용 | Phase 2 에서 `middleware.ts` + `@supabase/ssr` server client 도입 |
| 무한 스크롤 / 페이지네이션 | limit=12 단일 페이지 | 데이터 누적 후 cursor 기반 무한 스크롤 추가 |
| Vision AI / 스켈레톤 오버레이 | Phase 2 범위 — VideoPlayer 에 토글 placeholder 미포함 | Phase 2에서 toggle UI 추가 |
| 결제 / 구독 UI | 미구현 | Phase 2 |
| OG 이미지 | 기본 metadata 만 | Phase 2 에서 동적 OG 이미지 |
| E2E 테스트 | 없음 | Playwright 도입 검토 |

---

## 7. 파일 인벤토리 (총 18개)

```
frontend/
├── package.json
├── tsconfig.json
├── tailwind.config.ts
├── next.config.ts
├── postcss.config.js
├── .env.local.example
├── .gitignore
├── README.md
└── src/
    ├── app/
    │   ├── layout.tsx
    │   ├── page.tsx
    │   ├── globals.css
    │   ├── auth/page.tsx
    │   └── lessons/[id]/page.tsx
    ├── components/
    │   ├── UrlInputForm.tsx
    │   ├── LessonCard.tsx
    │   ├── ReportView/
    │   │   ├── index.tsx
    │   │   ├── VideoPlayer.tsx
    │   │   ├── NoteCards.tsx
    │   │   └── ShareButtons.tsx
    │   └── ui/
    │       ├── Header.tsx
    │       ├── LoadingSpinner.tsx
    │       └── Toast.tsx
    ├── lib/
    │   ├── api.ts
    │   └── supabase.ts
    └── types/
        └── lesson.ts
```
