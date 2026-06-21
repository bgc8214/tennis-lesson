# 05. Backend - lesson_type (레슨 카테고리) 기능 구현 요약

작성일: 2026-06-04
담당: Backend Engineer

---

## 1. 목적

업로드된 레슨 영상이 어떤 종류(포핸드/백핸드/발리 등)인지 Gemini가 자동 분류하고,
사용자가 마이페이지/리스트에서 카테고리별로 모아볼 수 있도록 한다.

복합 레슨(예: "포핸드 + 백핸드 코스 연습")을 위해 단일 값이 아닌 **TEXT 배열**로 저장한다.

---

## 2. 변경된 파일 목록

| # | 경로 | 변경 내용 |
|---|---|---|
| 1 | `_workspace/05_lesson_type_migration.sql` (신규) | `lessons.lesson_type TEXT[]` 컬럼 + GIN 인덱스 추가 SQL |
| 2 | `backend/app/services/gemini_service.py` | `MERGE_PROMPT_TEMPLATE`에 `lesson_type` 필드, `_coerce_lesson_type` 헬퍼, 단일 청크 분기와 최종 반환 dict에 lesson_type 추가, `ALLOWED_LESSON_TYPES` 화이트리스트 |
| 3 | `backend/app/routers/lessons.py` | `_run_analysis_pipeline`에서 `report["lesson_type"]`을 `lessons` 테이블에 UPDATE / `GET /lessons`에 `lesson_type` 쿼리 파라미터 / select에 `lesson_type` 추가 / `_serialize_lesson_summary` 응답에 `lesson_type` 포함 |
| 4 | `backend/app/models/lesson.py` | `LessonType` Literal 타입, `LessonSummary.lesson_type: List[str]` 필드 추가 |

---

## 3. SQL Migration

파일: `_workspace/05_lesson_type_migration.sql`

```sql
ALTER TABLE lessons
  ADD COLUMN IF NOT EXISTS lesson_type TEXT[] DEFAULT '{}';

CREATE INDEX IF NOT EXISTS idx_lessons_lesson_type
  ON lessons USING GIN (lesson_type);

UPDATE lessons SET lesson_type = '{}' WHERE lesson_type IS NULL;
```

- 타입: `TEXT[]` (PostgreSQL 배열)
- 기본값: 빈 배열 `'{}'`
- 인덱스: GIN — `@>`(contains), `&&`(overlaps) 연산을 빠르게 처리. Supabase python client의 `.contains("lesson_type", [...])` 가 그대로 활용됨.
- 적용 방법: Supabase SQL Editor에 붙여넣고 RUN.

---

## 4. 가능한 lesson_type 값 (화이트리스트)

총 10종. `gemini_service.ALLOWED_LESSON_TYPES`와 `models/lesson.LessonType` 양쪽에서 동기화 유지.

| 값 | 설명 |
|---|---|
| 포핸드 | Forehand 그라운드 스트로크 |
| 백핸드 | Backhand 그라운드 스트로크 (한손/양손 무관) |
| 발리 | Volley (포발리/백발리 통합) |
| 서브 | Serve (1st/2nd 통합) |
| 로브 | Lob |
| 스텝 | 좌우/전후 무빙 등 발 움직임 위주 |
| 풋워크 | 스플릿스텝/캐리오카 등 풋워크 드릴 |
| 게임레슨 | 실전 포인트/패턴 플레이 위주 레슨 |
| 드롭샷 | Drop shot / 슬라이스 짧게 떨구기 |
| 어프로치 | Approach shot / 네트 대시 빌드업 |

- LLM이 화이트리스트 외 값을 뱉으면 `_coerce_lesson_type`에서 자동 필터링.
- 최대 3개까지 저장 (과도한 라벨링 방지).
- 분류 불가능한 영상은 빈 배열 `[]`로 저장 (필터링에 안 잡혀도 정상).

---

## 5. API 변경

### GET `/api/v1/lessons` — 신규 쿼리 파라미터

| 파라미터 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `lesson_type` | string | optional | 단일 카테고리명. 해당 값이 `lesson_type` 배열에 포함된 레슨만 반환. (예: `?lesson_type=포핸드`) |

요청 예:
```
GET /api/v1/lessons?lesson_type=포핸드&limit=20
GET /api/v1/lessons?lesson_type=서브&status=DONE
```

내부 구현: Supabase `.contains("lesson_type", [lesson_type])` → PostgreSQL `lesson_type @> ARRAY['포핸드']`.

### 응답 스키마 변화

`LessonSummary` (그리고 `LessonDetail`)에 `lesson_type: string[]` 필드 추가.

```json
{
  "data": [
    {
      "lesson_id": "...",
      "title": "코치 김OO 포핸드 레슨",
      "lesson_type": ["포핸드"],
      "processing_status": "DONE",
      ...
    },
    {
      "lesson_id": "...",
      "title": "백핸드 슬라이스 + 어프로치",
      "lesson_type": ["백핸드", "어프로치"],
      ...
    }
  ],
  "pagination": { ... }
}
```

- 분석 미완료(PENDING/PROCESSING) 상태 레슨은 `lesson_type: []`.
- 분석 완료 후 `_run_analysis_pipeline`이 `lessons` row를 UPDATE.

---

## 6. 분석 파이프라인 변경 흐름

```
┌──────────────┐
│ POST analyze │ → lessons row 생성 (lesson_type DEFAULT '{}')
└──────┬───────┘
       │
       ▼
┌─────────────────────────────────┐
│ _run_analysis_pipeline (BG)     │
│ - gemini_service.generate_...() │
│   → returns {..., lesson_type}  │  ← 신규
│ - lesson_reports UPDATE (DONE)  │
│ - lessons UPDATE                │  ← lesson_type 포함
└─────────────────────────────────┘
```

`gemini_service.generate_lesson_report()` 반환 dict 변화:
```python
{
  "card1_problem": ...,
  "card2_cueing":  ...,
  "card3_action":  ...,
  "full_summary":  ...,
  "keywords":      [...3...],
  "lesson_type":   ["포핸드"],   # 신규 (0~3개)
  "timestamps":    [...],
  "gemini_model":  "...",
}
```

---

## 7. 미반영(향후 과제)

- 다중 카테고리 OR 필터 (`?lesson_type=포핸드,서브`) — 필요 시 `.overlaps()` 사용
- 카테고리별 통계 (대시보드용 GROUP BY) 엔드포인트
- 사용자가 lesson_type을 수동 수정/추가하는 PATCH API
