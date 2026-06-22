# QA 리포트: 코트 전술 다이어그램 기능 통합 검증

- 검증일: 2026-06-22
- 검증자: QA 에이전트
- 범위: court_service.py / lessons.py / report.py / config.py / requirements.txt / CourtDiagram.tsx / lesson.ts

---

## 요약

Critical 이슈 없음. 총 5개 이슈 발견(Medium 2, Low 3). 핵심 end-to-end 플로우는 정상 동작.

---

## 1. 백엔드-프론트 인터페이스 일치 검증

### court_tactics JSON 필드 3자 교차 비교

| 필드 | court_service._validate_tactics | report.py CourtTactic | lesson.ts CourtTactic |
|------|--------------------------------|----------------------|----------------------|
| sec | int | int, ge=0 | number |
| position | str (9zone or "unknown") | CourtPosition Literal | CourtPosition union |
| position_x | float, round(2) | float, ge=0 le=1 | number |
| position_y | float, round(2) | float, ge=0 le=1 | number |
| category | Optional[str] or None | Optional[str] = None | **string** (non-nullable) |
| tactic | str | str (required) | string |
| label | str | str (required) | string |
| quote | Optional[str] or None | Optional[str] = None | string \| null (optional) |

**결과: category 필드에 타입 불일치 발견 (Medium - #ISSUE-001)**

나머지 7개 필드는 3자 일치 확인.

---

## 2. CourtDiagram.tsx 렌더링 로직

### 마커 좌표 계산

SVG viewBox="0 0 300 400", 코트 플레이 영역 rect x=30 y=20 width=240 height=360.

```
cx = 30 + tactic.position_x * 240  (line 97)
cy = 20 + tactic.position_y * 360  (line 98)
```

- position_x=0.0 => cx=30 (좌측 경계), position_x=1.0 => cx=270 (우측 경계): 정확
- position_y=0.0 => cy=20 (네트 y=20 일치), position_y=1.0 => cy=380 (베이스라인 y=380 일치): 정확
- court_service의 POSITION_GRID 값(예: baseline_center=(0.50, 0.77))도 이 범위 내: 정확

**결과: 좌표 계산 로직 정확, PASS**

### 상태별 분기 처리 (4종)

| 상태 | 처리 |
|------|------|
| "PROCESSING" | LoadingSpinner 렌더링 (line 254) |
| "FAILED" | 에러 UI 렌더링 (line 268) |
| null / undefined | return null (line 288) |
| "DONE" + 빈 배열 | 빈 데이터 안내 메시지 (line 294) |
| "DONE" + 데이터 있음 | 다이어그램 + 카드 리스트 렌더링 |

**결과: 4가지 상태 전부 처리, PASS**

### 빈 배열 처리

line 294: `if (!tactics || tactics.length === 0)` 로 빈 배열 처리 후 안내 메시지 반환. **PASS**

---

## 3. court_service.py 핵심 로직

### snap_to_position 함수

- POSITION_GRID에 9개 zone 정의 (net_left/center/right, service_line_left/center/right, baseline_left/center/right)
- 유클리드 거리 계산 후 SNAP_THRESHOLD(0.2) 초과 시 ("unknown", x, y) 반환
- _validate_tactics에서 valid_positions = set(POSITION_GRID.keys()) | {"unknown"}로 10가지 허용값 검증
- **결과: 9 zone + unknown 처리 정확, PASS**

### 타임스탬프 최대 10개 제한

- analyze_court_tactics: `selected_timestamps = timestamps[:MAX_CLIPS]` (line 386), MAX_CLIPS=10
- _validate_tactics: `for item in tactics[:MAX_CLIPS]` (line 304)로 Gemini 응답도 10개 상한
- **결과: PASS**

### tempfile.TemporaryDirectory 사용

- line 394: `with tempfile.TemporaryDirectory(prefix="tennis-court-") as tmp_dir:` 컨텍스트 매니저로 사용
- with 블록 종료 시 자동 삭제 보장 (예외 발생 포함)
- **결과: PASS**

### YOLOv8 lazy import

- line 213-214: `from ultralytics import YOLO` + `import cv2` 가 _extract_player_position 함수 본문 내에서 호출될 때 import
- 서버 시작 시 ultralytics 로딩 없음
- **결과: PASS**

### 클립별 try/except (부분 실패 허용)

- lines 412-428: 각 클립에 대해 `try: clip_path = _download_clip(...) ... except Exception as e: logger.warning(...)` 로 래핑
- 실패 시 기본값 position="unknown" 유지, Gemini에 quote 기반 추론 위임
- **결과: PASS**

---

## 4. COURT_ANALYSIS_ENABLED 피처 플래그

### config.py 기본값

- line 53: `COURT_ANALYSIS_ENABLED: bool = False  # 기본값 False (점진적 롤아웃)`
- **결과: PASS**

### _run_analysis_pipeline 플래그 체크

- line 222: `if get_settings().COURT_ANALYSIS_ENABLED and report.get("timestamps"):` 로 Phase 1 완료 후 court_service 호출 차단
- line 671: `trigger_court_analysis` 엔드포인트에도 동일 플래그 체크 (line 671)
- **결과: PASS**

---

## 5. requirements.txt

| 패키지 | 요구 버전 | 상태 |
|--------|----------|------|
| ultralytics | >=8.0 | 추가 확인, PASS |
| opencv-python-headless | >=4.8 | 추가 확인, PASS |

**결과: PASS**

---

## 발견 이슈 목록

### ISSUE-001 (Medium) — CourtTactic.category 타입 불일치

- **파일**: `/frontend/src/types/lesson.ts:33`
- **내용**: `category: string` (non-nullable)으로 선언되어 있으나, 백엔드 `report.py:35` (`category: Optional[str] = None`)와 `court_service.py:328` (`category = str(...) or None`)에서 null이 반환될 수 있음
- **영향**: TypeScript 타입 체커가 null 가능성을 탐지하지 못함. 런타임 크래시는 없음 (CourtDiagram.tsx의 getCategoryColor/getCategoryBadgeClass가 `string | null | undefined` 파라미터를 받아 처리함)
- **수정 담당**: frontend
- **권고 수정**: `category: string | null;` 로 변경 (optional이 아닌 nullable)

---

### ISSUE-002 (Medium) — court_service.py 상수가 config.py 설정값을 미사용

- **파일**: `/backend/app/services/court_service.py:36-41`
- **내용**: MAX_CLIPS(10), CLIP_HALF_DURATION(20, total=40), VIDEO_HEIGHT(480), YOLO_CONF(0.5), FPS_SAMPLE(2)가 모두 모듈 레벨 상수로 하드코딩되어 있음. config.py에 COURT_ANALYSIS_MAX_CLIPS, COURT_ANALYSIS_CLIP_DURATION 등 동일 목적의 ENV 변수가 존재하나 서비스가 이를 읽지 않음
- **현재 영향**: 두 값이 동일하여 기능 차이 없음. 단, 운영 환경에서 ENV 변수를 조정해도 court_service.py의 동작이 바뀌지 않음
- **수정 담당**: backend
- **권고 수정**: analyze_court_tactics 진입부에서 settings를 읽어 상수 대신 settings 값 사용

---

### ISSUE-003 (Low) — YOLO 모델명 docstring 불일치

- **파일**: `/backend/app/services/court_service.py:4, 204, 216`
- **내용**: 파일 헤더 docstring(line 4)과 함수 docstring(line 204)에 "YOLOv8n"으로 명시되어 있으나, 실제 로드하는 모델은 `yolo11n.pt` (line 216)
- **영향**: 기능 동작에 영향 없음. 문서 혼동 유발
- **수정 담당**: backend
- **권고 수정**: docstring을 YOLO11n으로 교체

---

### ISSUE-004 (Low) — BackgroundTasks 기본값 패턴

- **파일**: `/backend/app/routers/lessons.py:661`
- **내용**: `background_tasks: BackgroundTasks = BackgroundTasks()` 로 기본값 선언. FastAPI는 BackgroundTasks 타입을 특수 처리하여 요청마다 새 인스턴스를 주입하므로 실제 기능 문제는 없음
- **영향**: 없음. 코드 스타일 비일관성
- **수정 담당**: backend
- **권고 수정**: `background_tasks: BackgroundTasks` (기본값 제거)

---

### ISSUE-005 (Low) — google-generativeai 버전 하한 부족

- **파일**: `/backend/requirements.txt:6`
- **내용**: `google-generativeai>=0.5.0` 으로 고정되어 있으나, `from google import genai` + `genai.Client` 패턴은 0.8.0+ (또는 별도 `google-genai` 패키지)에서만 사용 가능. court_service.py와 gemini_service.py 모두 해당 패턴 사용
- **영향**: 기존 환경에서는 동작 중이므로 운영 영향 없음. 새 환경 구축 시 0.5.x 설치되면 ImportError 발생 가능
- **수정 담당**: backend
- **권고 수정**: `google-generativeai>=0.8.0` 으로 하한 상향 또는 `google-genai>=0.5.0` 추가

---

## 검증 결과 요약

| 검증 항목 | 결과 |
|----------|------|
| 1-1. court_service JSON 필드 (8개) | PASS (category 타입 제외 7개 일치) |
| 1-2. report.py CourtTactic 모델 정합 | PASS |
| 1-3. lessons.py _serialize_report court_tactics 직렬화 | PASS |
| 2-1. SVG 마커 좌표 계산 | PASS |
| 2-2. 4가지 상태 처리 | PASS |
| 2-3. 빈 배열 처리 | PASS |
| 3-1. snap_to_position 9 zone + unknown | PASS |
| 3-2. 타임스탬프 10개 제한 | PASS |
| 3-3. tempfile.TemporaryDirectory 자동 정리 | PASS |
| 3-4. YOLOv8 lazy import | PASS |
| 3-5. 클립별 try/except 부분 실패 허용 | PASS |
| 4-1. COURT_ANALYSIS_ENABLED 기본값 False | PASS |
| 4-2. _run_analysis_pipeline 플래그 체크 | PASS |
| 5-1. ultralytics 추가 | PASS |
| 5-2. opencv-python-headless 추가 | PASS |

Critical 이슈: 0건 / High 이슈: 0건 / Medium 이슈: 2건 / Low 이슈: 3건
