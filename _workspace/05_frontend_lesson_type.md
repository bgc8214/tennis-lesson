# 05 · Frontend · Lesson Type 필터 UI 구현

## 작업 요약

레슨 카테고리(`lesson_type`)를 카드에 배지로 노출하고, 메인 페이지에서 카테고리별로 필터링할 수 있는 pill 토글 UI를 추가했다.

## 변경 파일

### 1. `frontend/src/types/lesson.ts`
- `LessonSummary` 인터페이스에 `lesson_type: string[]` 필드 추가.
- 백엔드의 `lessons.lesson_type text[]` 컬럼과 1:1 매칭. (배열 형태 — 한 레슨이 복수 카테고리를 가질 수 있음)

### 2. `frontend/src/lib/api.ts`
- `getLessons()` 시그니처에 `lesson_type?: string` 파라미터 추가.
- `URLSearchParams`에 `lesson_type` 키로 직렬화하여 `GET /api/v1/lessons?lesson_type=포핸드` 형태로 전달.

### 3. `frontend/src/components/LessonCard.tsx`
- 카드 본문 하단(고질병 미리보기 아래)에 `lesson_type` 배열을 순회하며 green-100 배경의 pill 배지로 표시.
- `lesson.lesson_type`이 비어있거나 undefined인 경우 렌더링하지 않음 (안전 가드).

### 4. `frontend/src/components/LessonTypeFilter.tsx` (신규)
- `"use client"` 컴포넌트.
- Props: `{ selected: string | null; onChange: (type: string | null) => void }`.
- 카테고리 상수: `["포핸드", "백핸드", "발리", "서브", "로브", "스텝", "풋워크", "게임레슨", "드롭샷", "어프로치"]`.
- "전체" + 10개 카테고리 pill 버튼 — 선택 시 `green-500` 배경 / 비선택 시 `gray-100`.
- 같은 버튼 재클릭 시 토글 해제(=`null`).

### 5. `frontend/src/app/page.tsx`
- `selectedType: string | null` 로컬 state 추가 (기본값 `null` = 전체).
- `loadLessons` deps에 `selectedType` 포함 → `useCallback` 재생성 → `useEffect`가 자동으로 재요청.
- `getLessons({ limit: 12, lesson_type: selectedType ?? undefined })` 형태로 호출.
- 인증된 섹션 안 "최근 레슨" 헤더 바로 아래, 카드 그리드 위에 `<LessonTypeFilter>` 배치.

## 동작 시나리오

1. 페이지 진입 → "전체" 활성, `GET /api/v1/lessons?limit=12` 호출.
2. "포핸드" 클릭 → `selectedType = "포핸드"` → `useEffect` 트리거 → `GET /api/v1/lessons?limit=12&lesson_type=포핸드` 재호출 → 그리드 갱신.
3. "포핸드" 재클릭 또는 "전체" 클릭 → `selectedType = null` → 전체 목록 복귀.
4. 각 카드 본문 하단에 해당 레슨의 카테고리 배지(green pill)가 노출됨.

## 백엔드 의존

- `GET /api/v1/lessons` 응답 `data[].lesson_type: string[]` 필드 제공 필요.
- `lesson_type` 쿼리 파라미터 지원 필요 (단일 카테고리, 배열 컬럼 contains 매칭).
- 두 항목 모두 백엔드에서 별도 작업 필요 (본 작업은 프론트엔드만 다룸).

## 미완료/후속 작업

- TypeScript 타입체크 실행은 권한 제한으로 미수행. 변경은 기존 코드 패턴과 일치하며 컴파일 이슈 없을 것으로 예상.
- 다중 카테고리 동시 선택(AND/OR 필터)은 현재 미지원 — 단일 선택 토글 방식.
- 모바일 가로 스크롤 대응이 필요하면 `LessonTypeFilter`에 `overflow-x-auto` 래퍼 추가 검토.
