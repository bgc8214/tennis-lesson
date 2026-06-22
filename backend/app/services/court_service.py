"""코트 전술 분석 서비스.

YouTube 영상에서 선수 위치를 추출하고 Gemini로 전술 분석을 수행한다.
파이프라인: 클립 다운로드 → YOLOv8 위치 추출 → Gemini 전술 생성
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import subprocess
import tempfile
from typing import Any, Callable, Dict, List, Optional, Tuple

from app.config import get_settings

logger = logging.getLogger(__name__)

# ─── Position Vocabulary ─────────────────────────────────────────────

POSITION_GRID: Dict[str, Tuple[float, float]] = {
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

SNAP_THRESHOLD = 0.2  # euclidean distance threshold for "unknown"


def _settings():
    s = get_settings()
    return {
        "max_clips": s.COURT_ANALYSIS_MAX_CLIPS,
        "clip_duration": s.COURT_ANALYSIS_CLIP_DURATION // 2,  # ±half
        "video_height": s.COURT_ANALYSIS_VIDEO_HEIGHT,
        "yolo_conf": s.COURT_ANALYSIS_YOLO_CONF,
        "fps_sample": s.COURT_ANALYSIS_FPS_SAMPLE,
    }

# ─── Gemini Prompt ───────────────────────────────────────────────────

COURT_TACTICS_PROMPT = """당신은 테니스 코트 전술 분석 전문가입니다.

아래는 테니스 레슨 영상의 타임스탬프별 코치 피드백과 선수의 추정 위치입니다.
각 피드백에 대해 코트 위치 기반 전술 분석 결과를 JSON 배열로 출력하세요.

입력:
{input_data}

출력 형식:
[
  {{
    "sec": 정수,
    "position": "9개 존 중 하나 또는 unknown",
    "position_x": 0.0~1.0,
    "position_y": 0.0~1.0,
    "to_position": "이동 목적지 존 (이동 지시가 있을 때만, 없으면 null)",
    "to_position_x": 0.0~1.0 또는 null,
    "to_position_y": 0.0~1.0 또는 null,
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
6) to_position: "들어와", "나가", "앞으로", "뒤로" 등 이동 지시가 quote에 있을 때만 목적지 존 지정. 단순 기술 지적이면 null.
7) 순수 JSON 배열만 출력. 마크다운 펜스 금지.
8) 최대 10개 항목.
"""


# ─── Utility ─────────────────────────────────────────────────────────


def _strip_fence(text: str) -> str:
    """Remove markdown code fences from LLM output."""
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z0-9_-]*\s*\n?", "", t)
        if t.endswith("```"):
            t = t[:-3]
        t = t.strip()
    return t


def _parse_json_array(raw: str) -> List[Dict[str, Any]]:
    """Parse a JSON array from raw text, stripping fences."""
    raw = _strip_fence(raw)
    try:
        result = json.loads(raw)
        if isinstance(result, list):
            return result
        return []
    except json.JSONDecodeError:
        pass

    # Try to find the first [ ... ] block
    start = raw.find("[")
    if start == -1:
        raise RuntimeError(f"JSON array 파싱 실패: {raw[:200]}")

    depth = 0
    in_str = False
    escape = False
    for i, ch in enumerate(raw[start:], start):
        if escape:
            escape = False
            continue
        if ch == "\\" and in_str:
            escape = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                candidate = raw[start : i + 1]
                try:
                    result = json.loads(candidate)
                    if isinstance(result, list):
                        return result
                except json.JSONDecodeError:
                    pass
                break

    raise RuntimeError(f"JSON array 파싱 실패: {raw[:200]}")


def snap_to_position(x: float, y: float) -> Tuple[str, float, float]:
    """Snap normalized coordinates to nearest position enum.

    Returns (position_name, grid_x, grid_y).
    If distance exceeds threshold, returns ("unknown", x, y).
    """
    min_dist = float("inf")
    best_name = "unknown"
    best_x, best_y = x, y

    for name, (gx, gy) in POSITION_GRID.items():
        dist = math.sqrt((x - gx) ** 2 + (y - gy) ** 2)
        if dist < min_dist:
            min_dist = dist
            best_name = name
            best_x, best_y = gx, gy

    if min_dist > SNAP_THRESHOLD:
        return ("unknown", x, y)

    return (best_name, best_x, best_y)


# ─── Clip Download ───────────────────────────────────────────────────


def _download_clip(youtube_url: str, sec: int, tmp_dir: str, idx: int) -> Optional[str]:
    """Download a short video clip around the given timestamp using yt-dlp."""
    cfg = _settings()
    start = max(0, sec - cfg["clip_duration"])
    end = sec + cfg["clip_duration"]
    output_path = os.path.join(tmp_dir, f"clip_{idx:04d}.mp4")

    cmd = [
        "yt-dlp",
        "-f", f"bestvideo[height<={cfg['video_height']}]",
        "--download-sections", f"*{start}-{end}",
        "--force-keyframes-at-cuts",
        "-o", output_path,
        "--no-playlist",
        "--quiet",
        "--no-warnings",
        youtube_url,
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            logger.warning("yt-dlp clip download failed (sec=%d): %s", sec, result.stderr[:200])
            return None
        if os.path.exists(output_path) and os.path.getsize(output_path) > 1024:
            return output_path
        return None
    except subprocess.TimeoutExpired:
        logger.warning("yt-dlp clip download timed out (sec=%d)", sec)
        return None
    except Exception as e:
        logger.warning("yt-dlp clip download error (sec=%d): %s", sec, e)
        return None


# ─── YOLO Position Extraction ────────────────────────────────────────


def _extract_player_position(clip_path: str) -> Tuple[float, float]:
    """Extract median player position from a video clip using YOLOv8n.

    Returns normalized (x, y) coordinates where:
      x: 0.0 = left, 1.0 = right
      y: 0.0 = top (net), 1.0 = bottom (baseline/camera)

    Falls back to (0.5, 0.5) if no person detected.
    """
    # Lazy imports to avoid slow startup
    from ultralytics import YOLO
    import cv2

    model = YOLO("yolo11n.pt")

    cap = cv2.VideoCapture(clip_path)
    if not cap.isOpened():
        return (0.5, 0.5)

    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps <= 0:
        fps = 30.0
    frame_interval = max(1, int(fps / _settings()["fps_sample"]))

    positions: List[Tuple[float, float]] = []
    frame_idx = 0
    frame_width = 0
    frame_height = 0

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break
        if frame_idx % frame_interval == 0:
            h, w = frame.shape[:2]
            frame_width = w
            frame_height = h
            results = model(frame, classes=[0], conf=_settings()["yolo_conf"], verbose=False)
            for box in results[0].boxes:
                xyxy = box.xyxy[0]
                cx = (xyxy[0].item() + xyxy[2].item()) / 2.0
                bottom = xyxy[3].item()
                positions.append((cx, bottom))
        frame_idx += 1

    cap.release()

    if not positions or frame_width == 0 or frame_height == 0:
        return (0.5, 0.5)

    # Median position for stability
    xs = sorted([p[0] for p in positions])
    ys = sorted([p[1] for p in positions])
    median_x = xs[len(xs) // 2]
    median_y = ys[len(ys) // 2]

    # Normalize
    norm_x = median_x / frame_width
    norm_y = median_y / frame_height

    # Clamp to [0, 1]
    norm_x = max(0.0, min(1.0, norm_x))
    norm_y = max(0.0, min(1.0, norm_y))

    return (norm_x, norm_y)


# ─── Gemini Court Tactics Generation ─────────────────────────────────


def _call_gemini_court_tactics(input_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Call Gemini to generate court tactics from position + timestamp data."""
    settings = get_settings()
    if not settings.GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not configured")

    from google import genai
    from google.genai import types

    client = genai.Client(api_key=settings.GEMINI_API_KEY)

    prompt = COURT_TACTICS_PROMPT.format(input_data=json.dumps(input_data, ensure_ascii=False))

    response = client.models.generate_content(
        model=settings.GEMINI_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(temperature=0.3, max_output_tokens=8192),
    )

    raw = response.text or ""
    logger.info("Gemini court tactics response length: %d", len(raw))

    tactics = _parse_json_array(raw)
    return _validate_tactics(tactics)


def _validate_tactics(tactics: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Validate and sanitize Gemini output."""
    valid_positions = set(POSITION_GRID.keys()) | {"unknown"}
    result = []

    for item in tactics[:_settings()["max_clips"]]:
        if not isinstance(item, dict):
            continue

        try:
            sec = int(item.get("sec", 0))
        except (TypeError, ValueError):
            continue

        position = str(item.get("position", "unknown")).strip()
        if position not in valid_positions:
            position = "unknown"

        try:
            pos_x = float(item.get("position_x", 0.5))
            pos_y = float(item.get("position_y", 0.5))
        except (TypeError, ValueError):
            pos_x, pos_y = 0.5, 0.5

        pos_x = max(0.0, min(1.0, pos_x))
        pos_y = max(0.0, min(1.0, pos_y))

        tactic = str(item.get("tactic", "")).strip()
        label = str(item.get("label", "")).strip()
        category = str(item.get("category", "")).strip() or None
        quote = item.get("quote")
        if quote is not None:
            quote = str(quote).strip() or None

        # 이동 화살표 필드
        to_pos = str(item.get("to_position", "") or "").strip()
        to_pos = to_pos if to_pos in valid_positions and to_pos != "unknown" else None
        try:
            to_x = float(item["to_position_x"]) if item.get("to_position_x") is not None else None
            to_y = float(item["to_position_y"]) if item.get("to_position_y") is not None else None
            if to_x is not None:
                to_x = round(max(0.0, min(1.0, to_x)), 2)
            if to_y is not None:
                to_y = round(max(0.0, min(1.0, to_y)), 2)
        except (TypeError, ValueError):
            to_x, to_y = None, None

        if not to_pos:
            to_x, to_y = None, None

        if not tactic or not label:
            continue

        result.append({
            "sec": sec,
            "position": position,
            "position_x": round(pos_x, 2),
            "position_y": round(pos_y, 2),
            "to_position": to_pos,
            "to_position_x": to_x,
            "to_position_y": to_y,
            "category": category,
            "tactic": tactic,
            "label": label,
            "quote": quote,
        })

    return result


# ─── Main Entry Point ────────────────────────────────────────────────

ProgressCallback = Callable[[int, str], None]


def analyze_court_tactics(
    youtube_url: str,
    timestamps: List[Dict[str, Any]],
    on_progress: Optional[ProgressCallback] = None,
) -> List[Dict[str, Any]]:
    """Analyze court tactics from video timestamps.

    Args:
        youtube_url: YouTube video URL.
        timestamps: List of timestamp dicts from Phase 1 report.
            Each has: sec, label, quote, category, fix
        on_progress: Optional callback(step, message).

    Returns:
        List of court tactic dicts ready for DB storage.
    """
    settings = get_settings()

    if not timestamps:
        logger.info("No timestamps provided, skipping court analysis")
        return []

    def _notify(step: int, message: str) -> None:
        if on_progress is None:
            return
        try:
            on_progress(step, message)
        except Exception:
            pass

    # Limit to configured max clips
    selected_timestamps = timestamps[:_settings()["max_clips"]]
    total = len(selected_timestamps)

    _notify(5, f"코트 분석 시작... ({total}개 타임스탬프)")

    # Phase A: Download clips and extract positions
    gemini_input: List[Dict[str, Any]] = []

    with tempfile.TemporaryDirectory(prefix="tennis-court-") as tmp_dir:
        for idx, ts in enumerate(selected_timestamps):
            sec = int(ts.get("sec", 0))
            label = str(ts.get("label", "")).strip()
            quote = ts.get("quote")
            category = str(ts.get("category", "")).strip() or None

            entry: Dict[str, Any] = {
                "sec": sec,
                "label": label,
                "quote": quote,
                "category": category,
                "position": "unknown",
                "position_x": 0.5,
                "position_y": 0.5,
            }

            # Try to download clip and extract position
            try:
                clip_path = _download_clip(youtube_url, sec, tmp_dir, idx)
                if clip_path:
                    norm_x, norm_y = _extract_player_position(clip_path)
                    position_name, grid_x, grid_y = snap_to_position(norm_x, norm_y)
                    entry["position"] = position_name
                    entry["position_x"] = round(grid_x, 2)
                    entry["position_y"] = round(grid_y, 2)
                    logger.info(
                        "Clip %d (sec=%d): position=%s (%.2f, %.2f)",
                        idx, sec, position_name, grid_x, grid_y,
                    )
                else:
                    logger.info("Clip %d (sec=%d): download failed, using fallback", idx, sec)
            except Exception as e:
                logger.warning("Clip %d (sec=%d): YOLO extraction failed: %s", idx, sec, e)
                # Keep entry with unknown position - Gemini will infer from quote

            gemini_input.append(entry)
            _notify(5, f"코트 분석 중... ({idx + 1}/{total} 클립 처리)")

    # Phase B: Call Gemini for tactic generation
    _notify(6, "전술 분석 생성 중...")

    try:
        tactics = _call_gemini_court_tactics(gemini_input)
    except Exception as e:
        logger.error("Gemini court tactics call failed: %s", e)
        # Fallback: return basic entries without Gemini enrichment
        tactics = []
        for entry in gemini_input:
            if entry.get("position") != "unknown" or entry.get("quote"):
                tactics.append({
                    "sec": entry["sec"],
                    "position": entry["position"],
                    "position_x": entry["position_x"],
                    "position_y": entry["position_y"],
                    "category": entry.get("category") or "기타",
                    "tactic": entry.get("label") or "위치 확인 필요",
                    "label": (entry.get("label") or "피드백")[:8],
                    "quote": entry.get("quote"),
                })

    logger.info("Court tactics analysis complete: %d tactics generated", len(tactics))
    return tactics
