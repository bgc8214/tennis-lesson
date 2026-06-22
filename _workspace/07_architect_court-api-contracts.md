# [07] Phase 2 코트 전술 다이어그램 — API 계약 명세

> **버전:** v1 (Phase 2 확장)
> **Base URL:** `{NEXT_PUBLIC_API_BASE_URL}/api/v1`
> **인증:** `Authorization: Bearer <supabase_jwt>` (모든 엔드포인트)

---

## 1. 기존 엔드포인트 변경사항

### 1.1 GET /lessons/{lesson_id} — 응답 확장

기존 `report` 객체에 `court_tactics` 필드와 `court_analysis_status` 필드를 추가한다.

#### 응답 스키마 (변경된 부분만)

```json
{
  "data": {
    "lesson_id": "uuid",
    "processing_status": "DONE",
    "report": {
      "card1_problem": "...",
      "card2_cueing": "...",
      "card3_action": "...",
      "keywords": ["...", "..."],
      "steps": ["...", "..."],
      "scenarios": [{"condition": "...", "action": "..."}],
      "timestamps": [{"sec": 0, "label": "...", "quote": "...", "category": "...", "fix": "..."}],
      "full_summary": "...",
      "transcript_source": "WHISPER_STT",
      "gemini_model": "gemini-1.5-flash",
      "error_message": null,
      "completed_at": "2026-06-22T12:00:00Z",
      "progress_step": 4,
      "progress_message": null,
      "court_tactics": [
        {
          "sec": 320,
          "position": "service_line_center",
          "position_x": 0.5,
          "position_y": 0.4,
          "category": "발리",
          "tactic": "네트에 더 붙어서 치기",
          "label": "발리 위치 교정",
          "quote": "거기서 치면 너무 멀어, 한 발 더 앞으로"
        }
      ],
      "court_analysis_status": "DONE"
    }
  }
}
```

#### court_tactics 필드 규칙

| 조건 | court_tactics 값 | court_analysis_status |
|---|---|---|
| 코트 분석 미실행 | `null` | `null` |
| 코트 분석 진행중 | `null` | `"PROCESSING"` |
| 코트 분석 완료 (결과 있음) | `[{...}, ...]` | `"DONE"` |
| 코트 분석 완료 (결과 없음) | `[]` | `"DONE"` |
| 코트 분석 실패 | `null` | `"FAILED"` |

---

## 2. 새 엔드포인트

### 2.1 POST /lessons/{lesson_id}/court-analysis

코트 전술 분석을 별도로 트리거한다. 이미 Phase 1이 DONE인 레슨에 대해서만 실행 가능.

#### Request

```
POST /api/v1/lessons/{lesson_id}/court-analysis
Authorization: Bearer <jwt>
Content-Type: application/json

(Body 없음)
```

#### Path Parameters

| 파라미터 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `lesson_id` | string (UUID) | Y | 분석 대상 레슨 ID |

#### Responses

##### 202 Accepted — 분석 트리거 성공

```json
{
  "data": {
    "lesson_id": "uuid-here",
    "court_analysis_status": "PROCESSING",
    "message": "코트 분석이 시작되었습니다."
  }
}
```

##### 400 Bad Request — 레슨이 아직 완료되지 않음

```json
{
  "error": {
    "code": "LESSON_NOT_READY",
    "message": "레슨 분석이 완료된 후에만 코트 분석을 실행할 수 있습니다.",
    "details": {
      "lesson_id": "uuid-here",
      "current_status": "PROCESSING"
    }
  }
}
```

##### 404 Not Found — 레슨 미존재 또는 소유권 불일치

```json
{
  "error": {
    "code": "LESSON_NOT_FOUND",
    "message": "해당 레슨을 찾을 수 없습니다.",
    "details": {
      "lesson_id": "uuid-here"
    }
  }
}
```

##### 409 Conflict — 이미 분석 중

```json
{
  "error": {
    "code": "COURT_ANALYSIS_IN_PROGRESS",
    "message": "코트 분석이 이미 진행 중입니다.",
    "details": {
      "lesson_id": "uuid-here",
      "court_analysis_status": "PROCESSING"
    }
  }
}
```

##### 422 Unprocessable Entity — 기능 비활성화

```json
{
  "error": {
    "code": "FEATURE_DISABLED",
    "message": "코트 분석 기능이 비활성화되어 있습니다."
  }
}
```

---

## 3. TypeScript 타입 확장 (frontend/src/types/lesson.ts)

```typescript
// 기존 타입에 추가

export type CourtPosition =
  | "net_left"
  | "net_center"
  | "net_right"
  | "service_line_left"
  | "service_line_center"
  | "service_line_right"
  | "baseline_left"
  | "baseline_center"
  | "baseline_right"
  | "unknown";

export type CourtAnalysisStatus = "PROCESSING" | "DONE" | "FAILED" | null;

export interface CourtTactic {
  sec: number;
  position: CourtPosition;
  position_x: number;
  position_y: number;
  category: string;
  tactic: string;
  label: string;
  quote?: string | null;
}

// LessonReport 인터페이스 확장
export interface LessonReport {
  // ... 기존 필드 ...
  court_tactics: CourtTactic[] | null;
  court_analysis_status: CourtAnalysisStatus;
}

// court-analysis 트리거 응답
export interface CourtAnalysisResponse {
  lesson_id: string;
  court_analysis_status: CourtAnalysisStatus;
  message: string;
}
```

---

## 4. Pydantic 모델 확장 (backend/app/models/report.py)

```python
from typing import Literal, Optional

CourtPosition = Literal[
    "net_left", "net_center", "net_right",
    "service_line_left", "service_line_center", "service_line_right",
    "baseline_left", "baseline_center", "baseline_right",
    "unknown",
]

CourtAnalysisStatus = Literal["PROCESSING", "DONE", "FAILED"]


class CourtTactic(BaseModel):
    """코트 위치 기반 전술 마커."""
    sec: int = Field(ge=0)
    position: CourtPosition
    position_x: float = Field(ge=0.0, le=1.0)
    position_y: float = Field(ge=0.0, le=1.0)
    category: str
    tactic: str
    label: str
    quote: Optional[str] = None
```

---

## 5. 에러 코드 추가

| 코드 | HTTP 상태 | 설명 |
|---|---|---|
| `LESSON_NOT_READY` | 400 | Phase 1 분석이 DONE이 아닌 상태에서 코트 분석 시도 |
| `COURT_ANALYSIS_IN_PROGRESS` | 409 | 이미 코트 분석 진행 중 |
| `FEATURE_DISABLED` | 422 | `COURT_ANALYSIS_ENABLED=false`일 때 |

---

## 6. 직렬화 변경 (_serialize_report 수정)

```python
def _serialize_report(row: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not row:
        return None
    return {
        # ... 기존 필드 ...
        "card1_problem": row.get("card1_problem"),
        "card2_cueing": row.get("card2_cueing"),
        "card3_action": row.get("card3_action"),
        "keywords": row.get("keywords") or [],
        "steps": row.get("steps") or [],
        "scenarios": row.get("scenarios") or [],
        "timestamps": row.get("timestamps") or [],
        "full_summary": row.get("full_summary"),
        "transcript_source": row.get("transcript_source") or "UNKNOWN",
        "gemini_model": row.get("gemini_model"),
        "error_message": row.get("error_message"),
        "completed_at": row.get("completed_at"),
        "progress_step": row.get("progress_step") or 0,
        "progress_message": row.get("progress_message"),
        # Phase 2 추가
        "court_tactics": row.get("court_tactics"),  # JSONB → 이미 list/None
        "court_analysis_status": row.get("court_analysis_status"),
    }
```

---

## 7. Gemini 프롬프트 (court_service용)

```
COURT_TACTICS_PROMPT = '''
당신은 테니스 코트 전술 분석 전문가입니다.

아래는 테니스 레슨 영상의 타임스탬프별 코치 피드백과 선수의 추정 위치입니다.
각 피드백에 대해 코트 위치 기반 전술 분석 결과를 JSON 배열로 출력하세요.

입력:
{input_data}

출력 형식:
[
  {{
    "sec": 정수,
    "position": "9�� 존 중 하나 또는 unknown",
    "position_x": 0.0~1.0,
    "position_y": 0.0~1.0,
    "category": "기술 카테고리",
    "tactic": "이 위치에서 해야 할 전술적 행동 1문장",
    "label": "마커에 표시할 짧은 라벨 (4~8자)",
    "quote": "코치 발언 원문 (없으면 null)"
  }}
]

규칙:
1) 모든 문자열은 한국어.
2) position은 다음 중 하나: net_left, net_center, net_right, service_line_left, service_line_center, service_line_right, baseline_left, baseline_center, baseline_right, unknown
3) position_x: 0.0=좌측, 1.0=우측. position_y: 0.0=네트, 1.0=베이스라인(카메라쪽)
4) 선수 위치 정보가 있으면 우선 사용, 없거나 unknown이면 quote/label에서 추론
5) tactic은 "어디서 어떻게 해야 한다"는 위치 기반 전술 조언
6) 순수 JSON 배열만 출력. 마크다운 펜스 금지.
7) 최대 10개 항목.
'''
```

---

## 8. 프론트엔드 API 호출 (lib/api.ts 확장)

```typescript
// 코트 분석 트리거
export async function triggerCourtAnalysis(lessonId: string): Promise<CourtAnalysisResponse> {
  const res = await apiFetch(`/api/v1/lessons/${lessonId}/court-analysis`, {
    method: "POST",
  });
  if (!res.ok) throw await parseApiError(res);
  const json = await res.json();
  return json.data;
}
```

---

## 9. 폴링/실시간 연동 전략

코트 분석은 Phase 1과 동일하게 GET 폴링으로 상태를 확인한다:

1. `POST /lessons/{id}/court-analysis` 호출 후 202 수신
2. 프론트에서 5초 간격으로 `GET /lessons/{id}` 폴링
3. `report.court_analysis_status === "DONE"` 확인 시 폴링 중단, 다이어그램 렌더링
4. `"FAILED"` 시 "코트 분석 실패" UI 표시 + 재시도 버튼 제공
