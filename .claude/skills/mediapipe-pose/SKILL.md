---
name: mediapipe-pose
description: "Google MediaPipe Pose를 사용하여 테니스 플레이어의 관절 궤적을 분석하는 Vision AI 스킬. 21개 랜드마크 추출, 서브 타점 각도/라켓드롭 깊이/내전 여부 계산, 스켈레톤 오버레이 렌더링. Phase 2 Vision AI 관련 작업, 관절 분석, 자세 교정 데이터 생성, 영상 프레임 분석 시 반드시 이 스킬을 사용할 것."
---

# MediaPipe Pose Analysis

테니스 플레이어 영상에서 관절 궤적을 추출하고 PMD 정의 3가지 스윙 메트릭을 계산한다.

## MediaPipe 랜드마크 인덱스 (테니스 분석 핵심)

```python
# MediaPipe Pose 33개 랜드마크 중 테니스 분석 핵심 인덱스
LANDMARKS = {
    "LEFT_SHOULDER": 11,
    "RIGHT_SHOULDER": 12,
    "LEFT_ELBOW": 13,
    "RIGHT_ELBOW": 14,
    "LEFT_WRIST": 15,
    "RIGHT_WRIST": 16,
    "LEFT_INDEX": 19,   # 라켓 그립 대리 포인트
    "RIGHT_INDEX": 20,
    "LEFT_HIP": 23,
    "RIGHT_HIP": 24,
    "LEFT_KNEE": 25,
    "RIGHT_KNEE": 26,
}
```

## 기본 파이프라인

```python
import cv2
import mediapipe as mp
import numpy as np
from dataclasses import dataclass

mp_pose = mp.solutions.pose
mp_drawing = mp.solutions.drawing_utils

@dataclass
class FrameAnalysis:
    frame_number: int
    timestamp_sec: float
    landmarks: dict  # {name: {x, y, z, visibility}}
    metrics: dict    # {metric_name: value}

def analyze_video(video_path: str, handedness: str = "right") -> list[FrameAnalysis]:
    results = []
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS)
    
    with mp_pose.Pose(
        min_detection_confidence=0.5,
        min_tracking_confidence=0.5,
        model_complexity=1  # 0=가벼움, 1=균형, 2=정확도 최대
    ) as pose:
        frame_num = 0
        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break
            
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            pose_results = pose.process(rgb_frame)
            
            if pose_results.pose_landmarks:
                landmarks = extract_landmarks(pose_results.pose_landmarks)
                metrics = calculate_metrics(landmarks, handedness)
                results.append(FrameAnalysis(
                    frame_number=frame_num,
                    timestamp_sec=frame_num / fps,
                    landmarks=landmarks,
                    metrics=metrics
                ))
            frame_num += 1
    
    cap.release()
    return results
```

## 메트릭 1: 서브 타점 왼손 유지 각도

```python
def calc_left_arm_angle(landmarks: dict) -> float | None:
    """
    임팩트 순간 왼팔이 하늘을 향해 뻗어 있는지 측정.
    왼쪽 어깨-팔꿈치-손목 벡터의 수직 기준 각도.
    정상 범위: 140~180도 (팔이 충분히 펴져 있음)
    """
    ls = landmarks.get("LEFT_SHOULDER")
    le = landmarks.get("LEFT_ELBOW")
    lw = landmarks.get("LEFT_WRIST")
    
    if not all([ls, le, lw]):
        return None
    if any(p["visibility"] < 0.5 for p in [ls, le, lw]):
        return None
    
    v1 = np.array([le["x"] - ls["x"], le["y"] - ls["y"]])
    v2 = np.array([lw["x"] - le["x"], lw["y"] - le["y"]])
    
    cos_angle = np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2) + 1e-8)
    return float(np.degrees(np.arccos(np.clip(cos_angle, -1, 1))))
```

## 메트릭 2: 라켓 드롭 깊이

```python
def calc_racket_drop_depth(landmarks: dict, handedness: str = "right") -> float | None:
    """
    트로피 자세에서 라켓 헤드(오른손 검지 근사)가
    오른쪽 어깨보다 얼마나 아래로 떨어지는지 측정.
    음수 = 어깨보다 위, 양수 = 어깨보다 아래 (깊을수록 좋음)
    정상 범위: 0.15 이상 (정규화된 y 좌표 기준)
    """
    if handedness == "right":
        shoulder_key, index_key = "RIGHT_SHOULDER", "RIGHT_INDEX"
    else:
        shoulder_key, index_key = "LEFT_SHOULDER", "LEFT_INDEX"
    
    shoulder = landmarks.get(shoulder_key)
    racket_proxy = landmarks.get(index_key)
    
    if not all([shoulder, racket_proxy]):
        return None
    if any(p["visibility"] < 0.5 for p in [shoulder, racket_proxy]):
        return None
    
    # MediaPipe y좌표: 아래로 갈수록 증가
    return float(racket_proxy["y"] - shoulder["y"])
```

## 메트릭 3: 내전(Pronation) 감지

```python
def calc_pronation(landmarks_sequence: list[dict], impact_frame: int,
                   handedness: str = "right") -> float | None:
    """
    임팩트 직후 5프레임에서 손목 회전 각도 변화율 계산.
    손목-팔꿈치-어깨 평면의 법선벡터 회전으로 근사.
    반환값: 도/프레임 (높을수록 내전 강함)
    정상 범위: 5~15도/프레임
    """
    if handedness == "right":
        shoulder_key, elbow_key, wrist_key = "RIGHT_SHOULDER", "RIGHT_ELBOW", "RIGHT_WRIST"
    else:
        shoulder_key, elbow_key, wrist_key = "LEFT_SHOULDER", "LEFT_ELBOW", "LEFT_WRIST"
    
    angles = []
    for i in range(impact_frame, min(impact_frame + 5, len(landmarks_sequence))):
        lm = landmarks_sequence[i]
        s, e, w = lm.get(shoulder_key), lm.get(elbow_key), lm.get(wrist_key)
        if not all([s, e, w]):
            continue
        # 팔 평면의 법선벡터 x 성분으로 회전 근사
        v_se = np.array([e["x"]-s["x"], e["y"]-s["y"], e["z"]-s["z"]])
        v_ew = np.array([w["x"]-e["x"], w["y"]-e["y"], w["z"]-e["z"]])
        normal = np.cross(v_se, v_ew)
        angles.append(normal[0])
    
    if len(angles) < 2:
        return None
    
    delta = abs(angles[-1] - angles[0])
    return float(np.degrees(delta) / len(angles))
```

## 스켈레톤 오버레이 렌더링

```python
def render_skeleton_overlay(frame: np.ndarray, pose_results) -> np.ndarray:
    annotated = frame.copy()
    mp_drawing.draw_landmarks(
        annotated,
        pose_results.pose_landmarks,
        mp_pose.POSE_CONNECTIONS,
        landmark_drawing_spec=mp_drawing.DrawingSpec(
            color=(0, 255, 0), thickness=2, circle_radius=3
        ),
        connection_drawing_spec=mp_drawing.DrawingSpec(
            color=(255, 255, 0), thickness=2
        )
    )
    return annotated
```

## 임팩트 프레임 자동 감지

```python
def detect_impact_frames(results: list[FrameAnalysis],
                         handedness: str = "right") -> list[int]:
    """
    손목 가속도가 최대인 프레임을 임팩트로 간주한다.
    (서브: 위에서 아래로 급격한 y 속도 변화)
    """
    wrist_key = "RIGHT_WRIST" if handedness == "right" else "LEFT_WRIST"
    wrist_y = []
    for r in results:
        w = r.landmarks.get(wrist_key)
        wrist_y.append(w["y"] if w else None)
    
    impact_frames = []
    for i in range(2, len(wrist_y) - 2):
        if wrist_y[i-1] is None or wrist_y[i] is None or wrist_y[i+1] is None:
            continue
        velocity = wrist_y[i] - wrist_y[i-1]
        accel = abs(velocity - (wrist_y[i-1] - wrist_y[i-2]) if wrist_y[i-2] else 0)
        if accel > 0.05:  # 임계값, 튜닝 필요
            impact_frames.append(i)
    
    return impact_frames
```

## 출력 JSON 스키마

```json
{
  "video_id": "uuid",
  "analyzed_at": "ISO8601",
  "handedness": "right",
  "total_frames": 1800,
  "fps": 30,
  "impact_frames": [245, 890],
  "metrics_summary": {
    "left_arm_angle": {"mean": 152.3, "min": 98.5, "max": 175.2, "unit": "degrees"},
    "racket_drop_depth": {"mean": 0.18, "min": -0.05, "max": 0.32, "unit": "normalized_y"},
    "pronation_rate": {"mean": 8.2, "min": 2.1, "max": 14.5, "unit": "degrees_per_frame"}
  },
  "frame_data": [
    {
      "frame_number": 245,
      "timestamp_sec": 8.17,
      "is_impact": true,
      "left_arm_angle": 135.2,
      "racket_drop_depth": 0.22,
      "pronation_rate": 11.3
    }
  ]
}
```

## 메트릭 정상 범위 기준

| 메트릭 | 정상 범위 | 문제 기준 | 코치 피드백 예시 |
|-------|---------|---------|---------------|
| 왼팔 각도 | 140~180도 | <130도 | "왼손이 너무 빨리 내려옵니다" |
| 라켓 드롭 | ≥0.15 | <0.10 | "라켓 헤드가 충분히 떨어지지 않습니다" |
| 내전율 | 5~15도/프레임 | <3도 | "손목 회전이 부족합니다" |

## 의존성

```
mediapipe>=0.10.0
opencv-python>=4.8.0
numpy>=1.24.0
```

## 참조

- 랜드마크 전체 목록: `references/mediapipe-landmarks.md`
- 메트릭 튜닝 가이드: `references/metric-tuning.md`
