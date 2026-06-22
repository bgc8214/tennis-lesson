# [07] Phase 2 코트 전술 다이어그램 — 시스템 설계서

> **작성 목적:** Phase 1 레슨 리포트에 코트 위치 기반 전술 다이어그램을 추가하여, 코치가 지적한 포지셔닝 피드백을 시각적으로 표현한다.
> **전제 조건:** Phase 1 완성 (lesson_reports 테이블에 timestamps/steps/scenarios 존재)
> **비용 영향:** YOLOv8 nano 모델(로컬 CPU), Gemini 1.5 Flash 추가 호출 1~2회/레슨

---

## 1. 기능 개요

### 1.1 목표
- 레슨 영상에서 선수의 코트 내 위치를 추출하여, "어디서 어떤 피드백을 받았는지"를 코트 다이어그램 위에 마커로 표시한다.
- 코치가 "네트에 더 붙어", "베이스라인에서 물러서지 마" 같은 위치 관련 피드백을 시각화한다.

### 1.2 Phase 2 제약
- GPU 없이 CPU에서 동작해야 함 (로컬 개발 + Railway Free tier)
- 추가 인프라 비용 최소화 (YOLOv8n + OpenCV = pip install만으로 해결)
- 기존 분석 파이프라인과 독립적으로 실행 가능 (선택적 후처리)

---

## 2. 포지션 어휘셋 (Position Vocabulary)

뒤쪽 앵글(카메라가 베이스라인 뒤에서 네트를 향해 촬영) 기준 하프코트를 9개 존으로 분할한다.

```
        ┌───────────────────────────────────────┐
        │           NET (네트 라인)              │  y = 0.0
        ├───────────┬───────────┬───────────────┤
        │ net_left  │net_center │  net_right    │  y = 0.0 ~ 0.25
        │ (0.17,    │ (0.5,     │ (0.83,       │
        │  0.12)    │  0.12)    │  0.12)       │
        ├───────────┼───────────┼───────────────┤
        │ svc_left  │svc_center │  svc_right   │  y = 0.25 ~ 0.55
        │ (0.17,    │ (0.5,     │ (0.83,       │  (서비스 라인 부근)
        │  0.4)     │  0.4)     │  0.4)        │
        ├───────────┼───────────┼───────────────┤
        │ base_left │base_center│  base_right  │  y = 0.55 ~ 1.0
        │ (0.17,    │ (0.5,     │ (0.83,       │  (베이스라인 부근)
        │  0.77)    │  0.77)    │  0.77)       │
        └───────────┴───────────┴───────────────┘
                                                   y = 1.0 (카메라 위치)
```

### 2.1 어휘 목록

| position (enum) | position_x | position_y | 설명 |
|---|---|---|---|
| `net_left` | 0.17 | 0.12 | 네트 좌측 |
| `net_center` | 0.50 | 0.12 | 네트 중앙 |
| `net_right` | 0.83 | 0.12 | 네트 우측 |
| `service_line_left` | 0.17 | 0.40 | 서비스라인 좌측 |
| `service_line_center` | 0.50 | 0.40 | 서비스라인 중앙 |
| `service_line_right` | 0.83 | 0.40 | 서비스라인 우측 |
| `baseline_left` | 0.17 | 0.77 | 베이스라인 좌측 |
| `baseline_center` | 0.50 | 0.77 | 베이스라인 중앙 |
| `baseline_right` | 0.83 | 0.77 | 베이스라인 우측 |
| `unknown` | 0.50 | 0.50 | 판별 불가 |

### 2.2 좌표 규칙

- `position_x`: 0.0 = 코트 좌측 사이드라인, 1.0 = 코트 우측 사이드라인
- `position_y`: 0.0 = 네트, 1.0 = 베이스라인(카메라 쪽)
- SVG 렌더링 시 이 좌표를 직접 사용하여 마커를 배치한다.
- 좌표는 position enum의 디폴트 값을 기본으로 하되, YOLO 감지 결과로 보정할 수 있다.

---

## 3. 처리 흐름 (Court Analysis Pipeline)

```
Phase 1 DONE
     │
     ▼
┌──────────────────────────────────────────────────────────────────┐
│  court_service.analyze_court_tactics(lesson_id)                   │
│                                                                  │
│  1. lesson_reports에서 timestamps 조회 (15~20개)                 │
│     │                                                            │
│  2. youtube_url + timestamps → clip 다운로드                     │
│     yt-dlp --download-sections "*sec-20 - sec+20"                │
│     (각 timestamp 전후 20초, 총 40초 클립)                       │
│     최대 10개 클립만 다운로드 (비용/시간 제어)                    │
│     │                                                            │
│  3. 클립별 선수 위치 추출 (CPU)                                  │
│     YOLOv8n (ultralytics) → person bbox 감지                     │
│     1초에 2프레임 샘플링 → 중앙값(median) 위치 산출              │
│     bbox bottom-center = 선수 발 위치로 추정                     │
│     │                                                            │
│  4. 코트 좌표 변환 (휴리스틱)                                    │
│     프레임 내 선수 위치(px) → 정규화 좌표(0~1)                   │
│     가정: 카메라는 뒤쪽 앵글, 코트가 프레임의 대부분 차지         │
│     변환식: x_norm = bbox_cx / frame_width                       │
│             y_norm = bbox_bottom / frame_height                   │
│     가장 가까운 position enum으로 스냅                            │
│     │                                                            │
│  5. Gemini 합산 호출                                             │
│     입력: timestamps(label, quote, category) + 추출된 위치 정보  │
│     출력: court_tactics JSON 배열                                 │
│     │                                                            │
│  6. lesson_reports.court_tactics 업데이트                         │
└──────────────────────────────────────────────────────────────────┘
```

### 3.1 단계별 상세

#### Step 2: 클립 다운로드

```python
# 의사 코드
for ts in timestamps[:10]:  # 최대 10개
    start = max(0, ts["sec"] - 20)
    end = ts["sec"] + 20
    yt-dlp -f "bestvideo[height<=480]" \
           --download-sections f"*{start}-{end}" \
           --force-keyframes-at-cuts \
           -o "{tmp_dir}/clip_{ts['sec']:04d}.mp4" \
           {youtube_url}
```

- 480p로 제한하여 다운로드 크기/디코딩 비용 절감
- `--force-keyframes-at-cuts`: 정확한 시간 분할

#### Step 3: 선수 위치 추출

```python
from ultralytics import YOLO
import cv2

model = YOLO("yolov8n.pt")  # 6.3MB, CPU 추론 ~50ms/frame

def extract_player_position(clip_path: str) -> tuple[float, float]:
    cap = cv2.VideoCapture(clip_path)
    fps = cap.get(cv2.CAP_PROP_FPS)
    frame_interval = max(1, int(fps / 2))  # 1초에 2프레임
    
    positions = []
    frame_idx = 0
    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break
        if frame_idx % frame_interval == 0:
            results = model(frame, classes=[0], conf=0.5)  # person만
            for box in results[0].boxes:
                cx = (box.xyxy[0][0] + box.xyxy[0][2]) / 2
                bottom = box.xyxy[0][3]
                positions.append((cx.item(), bottom.item()))
        frame_idx += 1
    cap.release()
    
    if not positions:
        return (0.5, 0.5)  # unknown
    
    # 중앙값으로 안정적 위치 추정
    xs = sorted([p[0] for p in positions])
    ys = sorted([p[1] for p in positions])
    median_x = xs[len(xs) // 2]
    median_y = ys[len(ys) // 2]
    
    # 정규화
    h, w = frame.shape[:2]
    return (median_x / w, median_y / h)
```

#### Step 4: Position Enum 스냅

```python
POSITION_GRID = {
    "net_left": (0.17, 0.12),
    "net_center": (0.50, 0.12),
    "net_right": (0.83, 0.12),
    "service_line_left": (0.17, 0.40),
    "service_line_center": (0.50, 0.40),
    "service_line_right": (0.83, 0.40),
    "baseline_left": (0.17, 0.77),
    "baseline_center": (0.50, 0.77),
    "baseline_right": (0.83, 0.77),
}

def snap_to_position(x: float, y: float) -> str:
    min_dist = float("inf")
    best = "unknown"
    for name, (gx, gy) in POSITION_GRID.items():
        dist = (x - gx) ** 2 + (y - gy) ** 2
        if dist < min_dist:
            min_dist = dist
            best = name
    # 너무 먼 경우 unknown
    if min_dist > 0.15:  # 임계값
        return "unknown"
    return best
```

#### Step 5: Gemini 합산

```
입력 프롬프트:
  "아래는 테니스 레슨 영상의 타임스탬프별 코치 피드백과 선수 위치 정보입니다.
   각 피드백에 대해 코트 위치 기반 전술 조언을 생성하세요.
   
   [{sec: 320, label: "...", quote: "...", position: "service_line_center", x: 0.5, y: 0.4}]
   
   출력 형식: court_tactics JSON 배열..."
```

---

## 4. 데이터 모델 (court_tactics 스키마)

### 4.1 단일 항목 구조

```json
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
```

### 4.2 필드 정의

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `sec` | integer | Y | 영상 내 시각 (초) |
| `position` | string (enum) | Y | 9개 존 + unknown |
| `position_x` | float (0.0~1.0) | Y | SVG x좌표 |
| `position_y` | float (0.0~1.0) | Y | SVG y좌표 |
| `category` | string | Y | 기술 카테고리 (포핸드/백핸드/발리/서브 등) |
| `tactic` | string | Y | Gemini가 생성한 전술 요약 (1문장) |
| `label` | string | Y | 마커에 표시할 짧은 라벨 |
| `quote` | string | N | 코치 발언 원문 |

---

## 5. 프론트엔드 컴포넌트 명세

### 5.1 CourtDiagram.tsx

```
┌─────────────────────────────────────────┐
│  SVG 하프코트 (뒤쪽 앵글, 탑뷰)        │
│                                         │
│    ┌─────────────────────────────┐      │
│    │         네트 라인            │      │
│    ├───────────┬─────┬───────────┤      │
│    │           │     │           │      │
│    │     (마커)│  ●  │           │      │
│    │           │     │           │      │
│    ├───────서비스─라인────────────┤      │
│    │           │     │           │      │
│    │   ●       │     │     ●     │      │
│    │           │     │           │      │
│    ├─────────베이스라인───────────┤      │
│    └─────────────────────────────┘      │
│                                         │
│  [마커 클릭 시 전술 카드 팝오버]         │
│  ┌─────────────────────────┐            │
│  │ 🎯 발리 위치 교정        │            │
│  │ "네트에 더 붙어서 치기"   │            │
│  │ 코치: "거기서 치면..."   │            │
│  │ [▶ 3:20 영상 보기]       │            │
│  └─────────────────────────┘            │
└─────────────────────────────────────────┘
```

### 5.2 컴포넌트 구조

```
CourtDiagramSection (섹션 래퍼)
├── CourtDiagram (SVG 코트 + 마커)
│   ├── CourtSVG (정적 코트 도면)
│   └── TacticMarker[] (position_x, position_y 기반 배치)
├── TacticCard (선택된 마커의 상세 카드)
│   ├── 카테고리 배지
│   ├── tactic 텍스트
│   ├── quote 인용
│   └── YouTube 타임스탬프 링크
└── TacticList (모바일: 카드 리스트 뷰)
```

### 5.3 반응형 전략

- **Desktop (>= 768px)**: 코트 SVG + 사이드 패널 (카드)
- **Mobile (< 768px)**: 코트 SVG (축소) + 하단 슬라이드업 카드

### 5.4 색상/카테고리 매핑

| category | 마커 색상 | Tailwind |
|---|---|---|
| 포핸드 | 빨강 | `fill-red-500` |
| 백핸드 | 파랑 | `fill-blue-500` |
| 발리 | 초록 | `fill-green-500` |
| 서브 | 보라 | `fill-purple-500` |
| 풋워크/스텝 | 주황 | `fill-orange-500` |
| 기타 | 회색 | `fill-gray-500` |

---

## 6. 비용/성능 분석

### 6.1 처리 시간 예상 (CPU 기준)

| 단계 | 시간 (10개 클립) |
|---|---|
| yt-dlp 클립 다운로드 | ~60초 |
| YOLOv8n 추론 (40초 클립 x 10, 2fps) | ~40초 |
| Gemini 합산 호출 | ~10초 |
| **합계** | ~110초 |

### 6.2 비용

| 항목 | 비용 |
|---|---|
| YOLOv8n (ultralytics, AGPL) | 무료 (비상업적 사용) |
| OpenCV | 무료 |
| yt-dlp 비디오 클립 다운로드 | 대역폭만 (YouTube 무료) |
| Gemini 1.5 Flash 추가 1회 호출 | 무료 티어 내 |
| **합계** | 0원 |

### 6.3 리스크

| 리스크 | 완화 방안 |
|---|---|
| 카메라 앵글이 뒤쪽이 아닌 경우 | position = "unknown" 폴백, 프론트에서 "위치 판별 불가" 표시 |
| YOLO가 선수를 못 찾는 경우 | timestamps의 quote에서 위치 키워드("네트", "베이스라인") 파싱으로 보완 |
| 레슨 영상이 코트 전체가 안 보이는 경우 | Gemini가 quote 기반으로만 position 추론 (YOLO 결과 무시) |
| ultralytics AGPL 라이선스 | Phase 2는 도그푸딩. 상용화 시 Enterprise 라이선스 또는 대체 모델 검토 |

---

## 7. 기존 시스템과의 통합 포인트

### 7.1 ��이프라인 확장

```python
# backend/app/routers/lessons.py _run_analysis_pipeline 수정 방향

def _run_analysis_pipeline(lesson_id: str, youtube_url: str) -> None:
    # ... 기존 Phase 1 파이프라인 ...
    
    # Phase 1 완료 후 court_tactics 분석 (선택적, 별도 에러 핸들링)
    try:
        from app.services.court_service import analyze_court_tactics
        analyze_court_tactics(lesson_id, youtube_url)
    except Exception as e:
        logger.warning("[%s] court analysis skipped: %s", lesson_id, e)
        # court_tactics 실패해도 전체 리포트 DONE 상태 유지
```

### 7.2 별도 트리거 API

이미 Phase 1이 DONE인 레슨에 대해 나중에 코트 분석만 별도 실행할 수 있는 엔드포인트 제공.

### 7.3 프론트 통합

`lessons/[id]` 페이지의 기존 리포트 섹션 아래에 `CourtDiagramSection` 추가.
`court_tactics`가 null이거나 빈 배열이면 섹션 자체를 렌더링하지 않는다.

---

## 8. 설정 추가 (config.py)

```python
# === Court Analysis (Phase 2) ===
COURT_ANALYSIS_ENABLED: bool = True          # 기능 플래그
COURT_ANALYSIS_MAX_CLIPS: int = 10           # 최대 분석 클립 수
COURT_ANALYSIS_CLIP_DURATION: int = 40       # 클립 길이(초): sec+-20
COURT_ANALYSIS_VIDEO_HEIGHT: int = 480       # 다운로드 해상도 제한
COURT_ANALYSIS_YOLO_CONF: float = 0.5        # YOLO 신뢰도 임계값
COURT_ANALYSIS_FPS_SAMPLE: int = 2           # 초당 샘플링 프레임 수
```

---

## 9. 새로 추가할 파일 목록

### Backend
- `backend/app/services/court_service.py` — 코트 분석 파이프라인 메인
- `backend/app/services/yolo_service.py` — YOLO 추론 래퍼
- `backend/app/services/court_geometry.py` — 좌표 변환 + position snap

### Frontend
- `frontend/src/components/court/CourtDiagram.tsx` — SVG 코트 + 마커
- `frontend/src/components/court/CourtSVG.tsx` — 정적 코트 도면
- `frontend/src/components/court/TacticMarker.tsx` — 개별 마커
- `frontend/src/components/court/TacticCard.tsx` — 전술 상세 카드

### Dependencies (pip)
- `ultralytics>=8.0` (YOLOv8)
- `opencv-python-headless>=4.8` (cv2, headless = 서버 환경)
