# 오늘의 테니스 — Frontend (Next.js 14)

Phase 1 MVP 프론트엔드. App Router + Tailwind + Supabase Auth.

## 빠른 시작

```bash
cd frontend
cp .env.local.example .env.local   # 값 채우기
npm install
npm run dev                         # http://localhost:3000
```

## 환경변수

`.env.local` 에 다음 값을 채워야 합니다.

| 키 | 필수 | 설명 |
|---|---|---|
| `NEXT_PUBLIC_SUPABASE_URL` | Y | Supabase 프로젝트 URL |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Y | Supabase anon key |
| `NEXT_PUBLIC_API_BASE_URL` | Y | FastAPI 백엔드 URL (기본 `http://localhost:8000`) |
| `NEXT_PUBLIC_SITE_URL` | Y | 자기 자신의 URL (Auth 콜백 redirect 용) |
| `NEXT_PUBLIC_KAKAO_JS_KEY` | N | 카카오톡 공유 사용 시 |

## 스크립트

- `npm run dev` — 개발 서버
- `npm run build` — 프로덕션 빌드
- `npm run start` — 프로덕션 서버
- `npm run type-check` — TypeScript 타입 체크

## 디렉토리 구조

```
src/
├── app/
│   ├── layout.tsx
│   ├── page.tsx                ← 대시보드 (URL 입력 + 레슨 카드)
│   ├── globals.css
│   ├── auth/page.tsx           ← 로그인/회원가입
│   └── lessons/[id]/page.tsx   ← 레슨 리포트 상세
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
