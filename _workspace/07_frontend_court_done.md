# [07] 코트 전술 다이어그램 프론트엔드 구현 완료

> **완료일:** 2026-06-22
> **TypeScript 빌드:** PASS (tsc --noEmit 에러 없음)

---

## 구현 파일 목록

### 1. 타입 확장 (수정)

**`frontend/src/types/lesson.ts`**

- `CourtPosition` 타입 추가 (9개 존 + unknown)
- `CourtAnalysisStatus` 타입 추가 ("PROCESSING" | "DONE" | "FAILED" | null)
- `CourtTactic` 인터페이스 추가 (sec, position, position_x, position_y, category, tactic, label, quote)
- `LessonReport` 인터페이스에 `court_tactics`, `court_analysis_status` 필드 추가

### 2. 신규 컴포넌트

**`frontend/src/components/ReportView/CourtDiagram.tsx`**

- `CourtDiagram` (메인 섹션 컴포넌트)
- `CourtSVG` (정적 하프코트 SVG, viewBox 300x400)
- `TacticMarker` (SVG 원형 마커, 카테고리별 색상)
- `TacticTooltip` (선택된 마커 상세 팝오버)
- `TacticCard` (스크롤 리스트 카드 아이템)
- `formatTime` (sec -> MM:SS 유틸)
- `getCategoryColor` / `getCategoryBadgeClass` (카테고리별 색상 매핑)

### 3. 기존 컴포넌트 수정

**`frontend/src/components/ReportView/index.tsx`**

- `CourtDiagram` import 및 NoteCards 아래 조건부 렌더링 추가
- export 목록에 `CourtDiagram` 추가

---

## 상태별 UI 처리

| 조건 | 렌더링 |
|------|--------|
| `court_analysis_status === null/undefined` | 섹션 미표시 (null 반환) |
| `court_analysis_status === "PROCESSING"` | 로딩 스피너 + "코트 전술을 분석 중입니다..." |
| `court_analysis_status === "FAILED"` | 에러 아이콘 + "코트 분석에 실패했습니다" |
| `court_analysis_status === "DONE"` + 빈 배열 | "코트 전술 데이터가 없습니다" |
| `court_analysis_status === "DONE"` + 데이터 | SVG 다이어그램 + 카드 리스트 |

---

## 카테고리 색상 매핑

| category | 마커 색상 | 배지 클래스 |
|----------|-----------|-------------|
| 포핸드 | #ef4444 (red-500) | bg-red-100 text-red-700 |
| 백핸드 | #3b82f6 (blue-500) | bg-blue-100 text-blue-700 |
| 발리 | #22c55e (green-500) | bg-green-100 text-green-700 |
| 서브 | #a855f7 (purple-500) | bg-purple-100 text-purple-700 |
| 풋워크/스텝 | #f97316 (orange-500) | bg-orange-100 text-orange-700 |
| 기타 | #6b7280 (gray-500) | bg-gray-100 text-gray-700 |

---

## 반응형 전략

- SVG: `width="100%"` + `viewBox="0 0 300 400"` (고정 비율)
- 다이어그램: `max-w-sm mx-auto`
- 카드 리스트: `max-h-64 sm:max-h-80 overflow-y-auto`
- 섹션: `rounded-2xl border shadow-sm p-4 sm:p-6`

---

## API 연동 참고

- `GET /lessons/{id}` 응답의 `report.court_tactics` 와 `report.court_analysis_status` 사용
- 기존 폴링 로직(4초 간격)이 court_analysis_status 변경도 자동 감지
- Supabase Realtime 구독이 lesson_reports 변경 시 자동 재조회
