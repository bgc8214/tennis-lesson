"""google-genai SDK 기반 오답노트 리포트 생성 서비스.

전략: 전체 오디오 다운로드 → 짧은 청크로 분할 → 청크별 병렬 분석 → 최종 합산
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import tempfile
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Dict, List, Optional

from app.config import get_settings
from app.services.yt_dlp_helpers import build_youtube_ydl_opts

logger = logging.getLogger(__name__)

CHUNK_SECONDS = 20       # 청크당 20초 — Gemini가 청크 내부 local_start_sec를 추정
MAX_CHUNKS = 200         # 최대 ~67분
MAX_WORKERS = 10         # 병렬 Gemini 호출 수
MIN_FEEDBACK_CONFIDENCE = 0.65
MAX_TIMELINE_ITEMS = 45
TIMELINE_DEDUP_WINDOW_SEC = 25
TIMELINE_MIN_GAP_SEC = 35
YOUTUBE_URL_SEGMENT_SECONDS = 5 * 60
YOUTUBE_URL_FALLBACK_DURATION_SEC = 75 * 60
YOUTUBE_URL_MAX_DURATION_SEC = 3 * 60 * 60

# ─── 프롬프트 ─────────────────────────────────────────────────────────

CHUNK_PROMPT = (
    '당신은 테니스 레슨 전문 분석가입니다.\n'
    '아래는 여성 코치가 남성 수강생에게 1:1 테니스 레슨을 진행하는 오디오 클립입니다.\n\n'
    '등장인물:\n'
    '- 코치(여성): 지시·교정·시범·설명을 하는 쪽. 주로 짧고 단호한 말투.\n'
    '- 수강생(남성): 질문하거나 "네", "아" 등으로 반응하는 쪽.\n\n'
    '코치가 수강생에게 한 명확한 테니스 피드백만 유형별로 분류하여 JSON으로 출력하세요.\n\n'
    'feedback으로 인정하는 것:\n'
    '- 잘못된 동작 지적: "타점이 뒤야", "라켓이 늦어", "몸이 열려"\n'
    '- 교정 지시: "앞에서 맞춰", "왼손 더 버텨", "라켓 먼저 빼"\n'
    '- 연습 방법: "크로스 세 개 치고 다운더라인", "하나 치고 두 개 치고"\n'
    '- 전술 판단: "짧은 공이면 들어와", "서브 후 포지션 잡아"\n\n'
    'feedback에서 제외하는 것:\n'
    '- 수강생 대답/추임새: "네", "아", "맞아요", "오케이요"\n'
    '- 단순 칭찬/진행 멘트: "좋아", "오케이", "그렇지", "하나 더", "다시", "자"\n'
    '- 카운트만 하는 말, 공 소리, 숨소리, 불명확한 발화\n'
    '- 단순 시작 신호: "시작", "준비", "하나 둘"만 있는 말\n'
    '- 레슨과 무관한 주변 대화: 핸드폰, 아이, 잡담 등\n'
    '- 들리지 않는 내용을 추측한 문장\n\n'
    '{"feedbacks": ['
    '{'
    '"local_start_sec": 0.0, "local_end_sec": 0.0, '
    '"type": "교정|드릴|전술", "category": "포핸드", "label": "요약", '
    '"quote": "실제 들린 코치 발언 원문", "problem": "문제 동작", '
    '"fix": "교정법 또는 드릴 내용", "importance": "high|medium|low", '
    '"confidence": 0.0'
    '}'
    '], "keywords": ["단어1", "단어2"]}\n\n'
    '규칙:\n'
    'type 분류:\n'
    '  - "교정": 수강생의 잘못된 동작을 지적하거나 교정하는 발언 (예: "타점이 뒤야", "라켓 면 닫아")\n'
    '  - "드릴": 특정 연습 방법·순서를 지시하는 발언 (예: "하나 치고 두 개 치고 스트레이트로", "크로스 세 개 다음에 다운더라인")\n'
    '  - "전술": 경기 상황 판단·배치·전략을 설명하는 발언 (예: "짧은 공 오면 네트로 들어와", "서브 후 포지션")\n'
    'category: 포핸드/백핸드/발리/서브/로브/스텝/풋워크/기타 중 하나.\n'
    'local_start_sec: 이 클립 안에서 해당 코치 발언이 시작된 대략 초. 0 이상 클립 길이 이하 숫자.\n'
    'local_end_sec: 이 클립 안에서 해당 코치 발언이 끝난 대략 초. 모르면 local_start_sec와 같게.\n'
    'label: 발언 내용 핵심 20자 이내.\n'
    'quote: 실제 들린 코치 발언 원문 그대로. 요약 금지. 수강생 발화 혼입 금지.\n'
    'problem: 코치가 지적한 문제 동작. 명확하지 않으면 빈 문자열.\n'
    'fix: 교정법 또는 드릴·전술 내용. 오디오에서 언급된 것만.\n'
    'importance: 레슨 복기에 중요한 핵심 피드백이면 high, 일반 지시면 medium, 보조적이면 low.\n'
    'confidence: 0.0~1.0. 발화자/내용/시간이 모두 확실할수록 높게.\n'
    '테니스 용어 참고: 타점·팔로우스루·내전·라켓드롭·토스·발리·스플릿스텝·풋워크·크로스·다운더라인.\n'
    '중요: "시작", "준비", "세 개", "하나 둘"처럼 드릴 진행 신호만 있으면 feedbacks에 넣지 말 것.\n'
    '중요: confidence가 0.65 미만이면 feedbacks에 넣지 말 것.\n'
    '중요: 코치의 명확한 발언이 들리지 않으면 feedbacks를 반드시 빈 배열 []로 반환할 것.\n'
    '추측하거나 공 소리·배경 소음만 있는 구간은 절대 feedbacks에 넣지 말 것.\n'
    'feedbacks는 최대 5개. 교정·드릴·전술 모두 포함. 순수 JSON만, 펜스 금지.'
)

MERGE_PROMPT_TEMPLATE = (
    '당신은 테니스 레슨 분석 전문가입니다.\n'
    '여성 코치가 남성 수강생에게 진행한 1:1 레슨을 짧은 구간별로 분석한 결과입니다.\n'
    '아래 형식의 JSON 하나만 출력하세요. timestamps 필드는 없음. 설명·주석 없이 JSON만.\n\n'
    '{chunk_results}\n\n'
    '{{"card1_problem":"50자이내","card2_cueing":"50자이내","card3_action":"60자이내",'
    '"keywords":["k1","k2","k3"],"lesson_type":["포핸드"],'
    '"steps":[],"scenarios":[]}}\n\n'
    '규칙:\n'
    '1) 모든 문자열 한국어. 자 이내 제한 엄수.\n'
    '2) card1_problem은 high importance 또는 반복 등장한 교정 피드백을 우선 반영.\n'
    '3) steps: 코치가 알려준 기술 동작 순서 3~5개. 없으면 [].\n'
    '4) scenarios: 상황별 대처 1~3개. 없으면 [].\n'
    '5) timestamps는 출력하지 않음 — 별도 처리됨.\n'
    '6) 순수 JSON만. 펜스·설명 금지.'
)

ALLOWED_LESSON_TYPES = {
    "포핸드", "백핸드", "발리", "서브", "로브",
    "스텝", "풋워크", "게임레슨", "드롭샷", "어프로치",
}


# ─── 유틸 ─────────────────────────────────────────────────────────────

def _strip_fence(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z0-9_-]*\s*\n?", "", t)
        if t.endswith("```"):
            t = t[:-3]
        t = t.strip()
    return t


def _parse_json(raw: str) -> dict:
    raw = _strip_fence(raw)

    # 1) 정상 파싱 시도
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # 2) 첫 번째 완전한 JSON 객체 추출 시도
    # { 위치부터 중괄호 depth를 추적해서 완전한 블록만 추출
    start = raw.find("{")
    if start == -1:
        raise RuntimeError(f"JSON 파싱 실패: {raw[:200]}")

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
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                candidate = raw[start:i+1]
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    pass
                break

    raise RuntimeError(f"JSON 파싱 실패: {raw[:200]}")


def _coerce_keywords(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    return [str(i).strip() for i in value if str(i).strip()][:3]


def _coerce_lesson_type(value: Any) -> List[str]:
    """LLM이 뱉은 lesson_type을 화이트리스트로 검증·정제."""
    if not isinstance(value, list):
        return []
    out: List[str] = []
    for item in value:
        s = str(item).strip()
        if s in ALLOWED_LESSON_TYPES and s not in out:
            out.append(s)
    return out[:3]  # 과도한 라벨링 방지


def _coerce_steps(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    return [str(i).strip() for i in value if str(i).strip()][:6]


def _coerce_scenarios(value: Any) -> List[Dict[str, str]]:
    if not isinstance(value, list):
        return []
    out = []
    for item in value:
        if not isinstance(item, dict):
            continue
        condition = str(item.get("condition", "")).strip()
        action = str(item.get("action", "")).strip()
        if condition and action:
            out.append({"condition": condition, "action": action})
    return out[:4]


def _coerce_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp_float(value: float, min_value: float, max_value: float) -> float:
    return max(min_value, min(max_value, value))


def _normalize_importance(value: Any) -> str:
    importance = str(value or "").strip().lower()
    if importance in ("high", "medium", "low"):
        return importance
    return "medium"


def _normalize_text_for_dedupe(value: Any) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]+", "", str(value or "").lower())


def _is_emptyish(value: Any) -> bool:
    normalized = _normalize_text_for_dedupe(value)
    return normalized in ("", "none", "null", "없음")


def _is_progress_only_feedback(item: Dict[str, Any]) -> bool:
    text = " ".join(
        str(item.get(key) or "")
        for key in ("label", "quote", "problem", "fix")
    )
    normalized = _normalize_text_for_dedupe(text)
    progress_words = (
        "시작", "준비", "하나둘", "세개", "다시", "오케이",
        "좋아", "그렇지", "자", "아기핸드폰",
    )
    if any(word in normalized for word in progress_words):
        if item.get("type") == "드릴" or item.get("importance") == "low":
            return True
    return False


def _timestamp_score(item: Dict[str, Any]) -> float:
    score = 0.0
    importance = _normalize_importance(item.get("importance"))
    if importance == "high":
        score += 3.0
    elif importance == "medium":
        score += 1.5

    if item.get("type") == "교정":
        score += 1.0
    elif item.get("type") == "전술":
        score += 0.8

    confidence = _coerce_float(item.get("confidence"), 0.0) or 0.0
    score += confidence

    if not _is_emptyish(item.get("problem")):
        score += 0.8
    if not _is_emptyish(item.get("fix")):
        score += 0.5

    if _is_progress_only_feedback(item):
        score -= 4.0
    if importance == "low":
        score -= 2.0
    return score


def _is_near_duplicate(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    try:
        sec_a = int(a.get("sec", 0))
        sec_b = int(b.get("sec", 0))
    except (TypeError, ValueError):
        return False
    if abs(sec_a - sec_b) > TIMELINE_DEDUP_WINDOW_SEC:
        return False

    comparable_keys = ("quote", "label", "problem", "fix")
    for key in comparable_keys:
        av = _normalize_text_for_dedupe(a.get(key))
        bv = _normalize_text_for_dedupe(b.get(key))
        if av and bv and av == bv:
            return True

    return (
        _normalize_text_for_dedupe(a.get("category")) == _normalize_text_for_dedupe(b.get("category"))
        and _normalize_text_for_dedupe(a.get("label")) == _normalize_text_for_dedupe(b.get("label"))
    )


def _compact_timestamps(timestamps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Dense chunk feedbacks를 복기용 핵심 타임라인으로 압축한다."""
    if not timestamps:
        return []

    ordered = sorted(timestamps, key=lambda item: int(item.get("sec", 0)))
    deduped: List[Dict[str, Any]] = []
    for item in ordered:
        if _is_progress_only_feedback(item) and _normalize_importance(item.get("importance")) != "high":
            continue

        duplicate_index = next(
            (idx for idx, prev in enumerate(deduped) if _is_near_duplicate(item, prev)),
            None,
        )
        if duplicate_index is None:
            deduped.append(item)
            continue

        if _timestamp_score(item) > _timestamp_score(deduped[duplicate_index]):
            deduped[duplicate_index] = item

    if len(deduped) <= MAX_TIMELINE_ITEMS:
        return sorted(deduped, key=lambda item: int(item.get("sec", 0)))

    ranked = sorted(deduped, key=_timestamp_score, reverse=True)
    selected: List[Dict[str, Any]] = []
    for item in ranked:
        sec = int(item.get("sec", 0))
        if any(abs(sec - int(prev.get("sec", 0))) < TIMELINE_MIN_GAP_SEC for prev in selected):
            continue
        selected.append(item)
        if len(selected) >= MAX_TIMELINE_ITEMS:
            break

    if len(selected) < MAX_TIMELINE_ITEMS:
        selected_ids = {id(item) for item in selected}
        for item in ranked:
            if id(item) in selected_ids:
                continue
            selected.append(item)
            selected_ids.add(id(item))
            if len(selected) >= MAX_TIMELINE_ITEMS:
                break

    return sorted(selected, key=lambda item: int(item.get("sec", 0)))


def _coerce_timestamps(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        return []
    out = []
    for item in value:
        if not isinstance(item, dict):
            continue
        try:
            sec = int(float(item.get("sec", 0)))
        except (TypeError, ValueError):
            continue
        if sec < 0:
            continue
        ts_type = str(item.get("type", "")).strip()
        if ts_type not in ("교정", "드릴", "전술"):
            ts_type = "교정"
        confidence = _coerce_float(item.get("confidence"))
        out.append({
            "sec": sec,
            "type": ts_type,
            "category": str(item.get("category", "")).strip() or None,
            "label": str(item.get("label", "")).strip() or "주요 지적",
            "quote": str(item.get("quote", "")).strip() or None,
            "problem": str(item.get("problem", "")).strip() or None,
            "fix": str(item.get("fix", "")).strip() or None,
            "importance": _normalize_importance(item.get("importance")),
            "confidence": round(_clamp_float(confidence, 0.0, 1.0), 2) if confidence is not None else None,
        })
    return out


# ─── 오디오 처리 ──────────────────────────────────────────────────────

def _download_full_audio(youtube_url: str, tmp_dir: str) -> str:
    """전체 오디오를 다운로드 (네트워크 오류 시 최대 3회 재시도)."""
    import yt_dlp
    ydl_opts = build_youtube_ydl_opts({
        "format": "bestaudio[ext=m4a]/bestaudio/best",
        "outtmpl": os.path.join(tmp_dir, "full.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "retries": 3,
        "fragment_retries": 3,
    }, tmp_dir=tmp_dir, logger=logger)

    cookiefile = ydl_opts.get("cookiefile")
    cookiefile = os.path.abspath(cookiefile) if isinstance(cookiefile, str) else None
    last_error = None
    for attempt in range(3):
        try:
            # 이전 실패로 남은 파일 정리
            for f in os.listdir(tmp_dir):
                path = os.path.join(tmp_dir, f)
                if cookiefile and os.path.abspath(path) == cookiefile:
                    continue
                if os.path.isdir(path):
                    shutil.rmtree(path)
                else:
                    os.remove(path)
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([youtube_url])
            for name in os.listdir(tmp_dir):
                path = os.path.join(tmp_dir, name)
                if cookiefile and os.path.abspath(path) == cookiefile:
                    continue
                if os.path.isfile(path) and os.path.getsize(path) > 1024:
                    return path
        except Exception as e:
            last_error = e
            logger.warning("오디오 다운로드 실패 (시도 %d/3): %s", attempt + 1, e, exc_info=True)
    raise RuntimeError(f"오디오 다운로드 실패: {last_error}")


def _get_duration(audio_path: str) -> float:
    """ffprobe로 오디오 길이(초) 조회."""
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", audio_path],
        capture_output=True, text=True
    )
    try:
        return float(result.stdout.strip())
    except Exception:
        return 0.0


def _split_audio(audio_path: str, tmp_dir: str, chunk_sec: int) -> List[Dict]:
    """ffmpeg로 오디오를 chunk_sec초씩 분할. [{path, offset_sec}] 반환."""
    duration = _get_duration(audio_path)
    if duration <= 0:
        return [{"path": audio_path, "offset_sec": 0}]

    chunks = []
    offset = 0
    idx = 0
    while offset < duration and idx < MAX_CHUNKS:
        chunk_path = os.path.join(tmp_dir, f"chunk_{idx:02d}.mp3")
        subprocess.run(
            ["ffmpeg", "-y", "-i", audio_path,
             "-ss", str(offset), "-t", str(chunk_sec),
             "-acodec", "libmp3lame", "-q:a", "6",
             chunk_path],
            capture_output=True
        )
        if os.path.exists(chunk_path) and os.path.getsize(chunk_path) > 1024:
            chunks.append({"path": chunk_path, "offset_sec": int(offset)})
        offset += chunk_sec
        idx += 1

    return chunks if chunks else [{"path": audio_path, "offset_sec": 0}]


# ─── Gemini 호출 ──────────────────────────────────────────────────────

def _has_speech(audio_path: str, silence_threshold: float = -25.0) -> bool:
    """ffmpeg silencedetect로 발화 여부 판단.

    -25dB 기준: 테니스 공 소리보다 사람 목소리가 훨씬 크므로
    배경 소음만 있는 구간은 걸러냄.
    전체가 무음이면 False.
    """
    result = subprocess.run(
        ["ffmpeg", "-i", audio_path, "-af",
         f"silencedetect=noise={silence_threshold}dB:d=0.5",
         "-f", "null", "-"],
        capture_output=True, text=True
    )
    output = result.stderr
    # silence_start가 0초에 시작하고 silence_end가 클립 끝이면 전체 무음
    # silence_end가 있다 = 소음 구간이 끊겼다 = 발화 있음
    has_non_silence = "silence_end" in output or "silence_start" not in output
    return has_non_silence


def _analyze_chunk(client: Any, chunk: Dict, types: Any) -> Optional[Dict]:
    """단일 청크를 Gemini로 분석."""
    path = chunk["path"]
    offset = chunk["offset_sec"]

    # 발화 없는 청크 스킵
    if not _has_speech(path):
        logger.info("청크 스킵 (offset=%ds): 발화 없음", offset)
        return None

    try:
        uploaded = client.files.upload(file=path, config={"mime_type": "audio/mpeg"})
    except Exception as e:
        logger.warning("청크 업로드 실패 (offset=%ds): %s", offset, e)
        return None

    try:
        duration = _get_duration(path)
        end = offset + int(duration)
        chunk_prompt = (
            CHUNK_PROMPT +
            f'\n\n[클립 정보] 영상 전체 {offset}초~{end}초 구간 ({offset//60}분{offset%60}초 ~ {end//60}분{end%60}초). '
            f'이 짧은 클립에서 코치의 명확한 발언이 있으면 추출하고, 없으면 feedbacks를 빈 배열로 반환하세요.'
        )
        response = client.models.generate_content(
            model=get_settings().GEMINI_MODEL,
            contents=[
                types.Part(file_data=types.FileData(file_uri=uploaded.uri, mime_type="audio/mpeg")),
                types.Part(text=chunk_prompt),
            ],
            config=types.GenerateContentConfig(
                temperature=0.3,
                max_output_tokens=65536,
                thinking_config=types.ThinkingConfig(thinking_budget=0),
            ),
        )
        raw = response.text or ""
        logger.info("청크 응답 (offset=%ds, 길이=%d): %s", offset, len(raw), raw[:200])
        parsed = _parse_json(raw)

        normalized_feedbacks = []
        for fb in parsed.get("feedbacks", []):
            if not isinstance(fb, dict):
                continue

            confidence = _coerce_float(fb.get("confidence"), 1.0)
            if confidence is not None and confidence < MIN_FEEDBACK_CONFIDENCE:
                continue

            local_start = _coerce_float(fb.get("local_start_sec"))
            if local_start is None:
                # 모델이 시간을 누락한 경우 청크 중앙값을 사용해 기존 offset 고정보다 오차를 줄인다.
                local_start = duration / 2 if duration > 0 else 0.0
            local_start = _clamp_float(local_start, 0.0, max(duration, 0.0))

            local_end = _coerce_float(fb.get("local_end_sec"), local_start)
            if local_end is None:
                local_end = local_start
            local_end = _clamp_float(local_end, local_start, max(duration, local_start))

            fb["local_start_sec"] = round(local_start, 1)
            fb["local_end_sec"] = round(local_end, 1)
            fb["sec"] = offset + int(round(local_start))
            fb["importance"] = _normalize_importance(fb.get("importance"))
            if confidence is not None:
                fb["confidence"] = round(_clamp_float(confidence, 0.0, 1.0), 2)
            normalized_feedbacks.append(fb)

        parsed["feedbacks"] = normalized_feedbacks

        parsed["offset_sec"] = offset
        logger.info("청크 분석 완료 (offset=%ds, feedbacks=%d)", offset, len(parsed.get("feedbacks", [])))
        return parsed

    except Exception as e:
        logger.warning("청크 분석 실패 (offset=%ds): %s", offset, e)
        return None
    finally:
        try:
            client.files.delete(name=uploaded.name)
        except Exception:
            pass


TRANSCRIPT_PROMPT = (
    '당신은 테니스 레슨 전문 분석가입니다.\n'
    '여성 코치가 남성 수강생에게 1:1 테니스 레슨을 진행하는 오디오입니다.\n\n'
    '코치의 발언만 추출해서 정리해주세요. 수강생 발화는 제외.\n\n'
    '규칙:\n'
    '1) 코치 발언만 포함. 수강생 반응("네", "아" 등) 제외.\n'
    '2) 같은 단어나 문장이 연속으로 반복되면 한 번만 기록. 예: "발리. 발리. 발리." → "발리."\n'
    '3) 짧은 추임새나 의미 없는 반복(그냥, 응, 어 등이 단독으로 반복)은 완전히 생략.\n'
    '4) 핵심 지시/교정/설명은 빠짐없이 포함.\n'
    '5) 테니스 용어를 정확하게 사용 (타점, 팔로우스루, 라켓드롭, 스플릿스텝, 트로피자세, 내전 등).\n'
    '6) 발언이 자연스럽게 이어지도록 정리. 원문 의도 훼손 금지.\n'
    '7) JSON이나 마크다운 없이 텍스트만 출력.'
)

YOUTUBE_URL_REPORT_PROMPT = (
    '당신은 테니스 레슨 전문 분석가입니다.\n'
    '첨부된 YouTube 레슨 영상을 직접 보고/듣고, 여성 코치가 남성 수강생에게 한 '
    '명확한 테니스 피드백만 추출해 오답노트 JSON을 작성하세요.\n\n'
    '중요한 구분:\n'
    '- 코치(여성): 지시·교정·시범·설명을 하는 쪽입니다.\n'
    '- 수강생(남성): 질문하거나 "네", "아" 등으로 반응하는 쪽입니다.\n'
    '- 수강생 반응, 공 소리, 진행 카운트, 단순 칭찬, 잡담은 제외하세요.\n\n'
    '아래 JSON 하나만 출력하세요. 마크다운 펜스나 설명은 금지합니다.\n\n'
    '{{"card1_problem": "코치가 반복적으로 지적한 핵심 문제 50자 이내", '
    '"card2_cueing": "코치가 제시한 핵심 이미지/큐잉 50자 이내", '
    '"card3_action": "다음 연습 때 집중할 구체 행동 60자 이내", '
    '"full_summary": "레슨 전체 흐름 요약 3~5문단", '
    '"keywords": ["키워드1", "키워드2", "키워드3"], '
    '"lesson_type": ["포핸드"], '
    '"steps": ["① 단계1", "② 단계2", "③ 단계3"], '
    '"scenarios": [{{"condition": "상황", "action": "대처"}}], '
    '"timestamps": ['
    '{{"sec": 123, "type": "교정", "category": "포핸드", "label": "20자 이내 요약", '
    '"quote": "실제 들린 코치 발언 원문", "problem": "문제 동작", '
    '"fix": "교정법", "importance": "high", "confidence": 0.85}}'
    ']}}\n\n'
    '규칙:\n'
    '1) 모든 문자열은 한국어.\n'
    '2) keywords는 정확히 3개.\n'
    '3) lesson_type은 ["포핸드","백핸드","발리","서브","로브","스텝","풋워크","게임레슨","드롭샷","어프로치"] 중 1~3개.\n'
    '4) timestamps는 주요 피드백 장면 15~30개. sec는 영상 전체 기준 초 단위 정수.\n'
    '5) timestamps의 quote는 실제 들린 코치 발언 원문에 가깝게 작성하고, 수강생 발화는 넣지 마세요.\n'
    '6) 확실하지 않은 장면은 timestamps에 넣지 마세요. confidence는 0.0~1.0.\n'
    '7) type은 "교정", "드릴", "전술" 중 하나.\n'
    '8) 단순 진행 신호("시작", "준비", "하나 둘", "다시")만 있는 장면은 제외.\n'
    '9) 순수 JSON만 출력. 마크다운 펜스 금지.'
)

YOUTUBE_URL_SEGMENT_PROMPT_TEMPLATE = (
    '당신은 오디오/영상 전사(transcription) 담당자입니다. 테니스 지식으로 내용을 채우거나 '
    '"이런 상황이면 코치가 보통 이렇게 말한다"는 추론을 하는 것은 엄격히 금지됩니다.\n\n'
    '첨부된 YouTube 레슨 영상 중 {start_label}~{end_label} 구간만 실제로 보고/들으세요. '
    '이 구간에 여성 코치가 남성 수강생에게 한 발언 중, 당신이 단어 단위로 정확하게 알아들은 '
    '발언만 JSON으로 추출하세요.\n\n'
    '절대 규칙 — 위반 시 전체 응답이 폐기됩니다:\n'
    '- quote는 실제로 들은 말을 한 글자도 바꾸지 않고 그대로 옮긴 것이어야 합니다. '
    '"~라는 취지", "~에 가까운 말", "대략" 같은 재구성/의역/추론은 절대 금지입니다.\n'
    '- 발화가 흐릿하거나, 숫자 세기("하나 둘 셋"), 이름/호칭 부르기, 짧은 감탄사("어!", "좋아"), '
    '공 치는 소리, 무의미한 잡음뿐이라면 그 장면은 절대 feedbacks에 넣지 마세요. '
    '내용을 지어내서 채우지 마세요.\n'
    '- 이 구간에 명확히 들리는 코치의 교정/드릴/전술 발언이 하나도 없다면, '
    'feedbacks를 반드시 빈 배열 []로 반환하세요. 빈 배열은 정상적이고 바람직한 응답입니다. '
    '개수를 채우려고 애쓰지 마세요.\n'
    '- 영상의 실제 길이가 {start_label}보다 짧아서 이 구간이 아예 존재하지 않을 수 있습니다. '
    '그런 경우 video_ended를 true로 설정하고 feedbacks를 빈 배열로 반환하세요.\n\n'
    '{{"video_ended": false, "feedbacks": ['
    '{{"sec": 123, "type": "교정", "category": "포핸드", "label": "20자 이내 요약", '
    '"quote": "실제 들린 코치 발언 원문 그대로", "problem": "문제 동작", '
    '"fix": "교정법", "importance": "high|medium|low", "confidence": 0.85}}'
    '], "keywords": ["키워드1", "키워드2", "키워드3"]}}\n\n'
    '규칙:\n'
    '1) sec는 영상 전체 기준 초 단위 정수이며 반드시 {start_sec} 이상 {end_sec} 이하.\n'
    '2) type은 "교정", "드릴", "전술" 중 하나.\n'
    '3) category는 포핸드/백핸드/발리/서브/로브/스텝/풋워크/기타 중 하나.\n'
    '4) 수강생 반응, 공 소리, 카운트, 단순 칭찬, 잡담, 진행 신호만 있는 장면은 제외.\n'
    '5) confidence는 "이 발언을 실제로 정확히 들었다고 확신하는 정도"를 뜻합니다. '
    '조금이라도 추측이 섞였다면 0.65 미만으로 낮추세요(이 경우 자동 제외됩니다).\n'
    '6) 이 구간이 영상 실제 길이를 넘어서면(영상이 이미 끝났으면) video_ended를 true로, '
    '그렇지 않으면 false로 반환. 불확실하면 false.\n'
    '7) 순수 JSON만 출력. 마크다운 펜스 금지.'
)


def _merge_chunks(client: Any, chunk_results: List[Dict], types: Any) -> dict:
    """청크 결과들을 Gemini로 최종 합산.

    timestamps는 Gemini에 맡기지 않고 청크 feedbacks에서 코드로 직접 생성.
    Gemini는 card1/card2/card3/keywords/steps/scenarios만 담당.
    """
    summary_lines = []
    # 청크 feedbacks에서 직접 timestamps 수집 (sec는 청크 분석에서 나온 값 그대로 사용)
    raw_timestamps: List[Dict] = []

    for r in chunk_results:
        offset = r.get("offset_sec", 0)
        start_m = offset // 60
        start_s = offset % 60
        feedbacks = r.get("feedbacks", [])
        keywords = r.get("keywords", [])
        lines = [f"\n## {start_m}분{start_s:02d}초 부근 구간"]
        if feedbacks:
            for fb in feedbacks:
                fb_type = fb.get("type", "교정")
                label = fb.get("label") or fb.get("problem", "")
                importance = _normalize_importance(fb.get("importance"))
                confidence = _coerce_float(fb.get("confidence"))
                confidence_text = f", 신뢰도 {confidence:.2f}" if confidence is not None else ""
                lines.append(
                    f"- [{fb['sec']}초][{fb_type}][{importance}{confidence_text}] "
                    f"{label} / 발언: {fb.get('quote','')}"
                )
                # timestamps 직접 수집
                raw_timestamps.append({
                    "sec": fb.get("sec", offset),  # _analyze_chunk에서 local_start_sec를 더해 계산됨
                    "type": fb_type,
                    "category": str(fb.get("category", "")).strip() or None,
                    "label": str(label).strip()[:20] or "피드백",
                    "quote": str(fb.get("quote", "")).strip()[:30] or None,
                    "problem": str(fb.get("problem", "")).strip()[:30] or None,
                    "fix": str(fb.get("fix", "")).strip()[:30] or None,
                    "importance": importance,
                    "confidence": round(_clamp_float(confidence, 0.0, 1.0), 2) if confidence is not None else None,
                })
        else:
            lines.append("- 피드백 없음")
        if keywords:
            lines.append(f"- 반복 키워드: {', '.join(keywords)}")
        summary_lines.append("\n".join(lines))

    # sec 오름차순 정렬
    raw_timestamps.sort(key=lambda x: x["sec"])

    # 중복 제거: sec가 10초 이내이고 quote가 동일하면 첫 번째만 유지
    deduped: List[Dict] = []
    for ts in raw_timestamps:
        is_dup = any(
            abs(ts["sec"] - prev["sec"]) <= 10 and ts.get("quote") == prev.get("quote")
            for prev in deduped
        )
        if not is_dup:
            deduped.append(ts)
    raw_timestamps = deduped
    raw_timestamps = _compact_timestamps(raw_timestamps)

    chunk_text = "\n".join(summary_lines)
    prompt = MERGE_PROMPT_TEMPLATE.format(chunk_results=chunk_text)

    response = client.models.generate_content(
        model=get_settings().GEMINI_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.4,
            max_output_tokens=16384,
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        ),
    )
    result = _parse_json(response.text or "")
    # Gemini가 만든 카드에 코드로 생성한 timestamps 주입
    result["timestamps"] = raw_timestamps
    return result


# ─── 메인 진입점 ──────────────────────────────────────────────────────

ProgressCallback = Callable[[int, str], None]


def generate_lesson_report(
    youtube_url: str,
    on_progress: Optional[ProgressCallback] = None,
) -> dict:
    """전체 분석 파이프라인 진입점.

    Args:
        youtube_url: 분석할 YouTube URL.
        on_progress: (step, message) 시그니처의 진행 콜백. 호출 측이 DB 등에
            진행 상태를 기록할 수 있도록 한다. 콜백이 던지는 예외는 흘려
            보내고 파이프라인을 멈추지 않는다.
    """
    settings = get_settings()
    if not settings.GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not configured")

    youtube_url = (youtube_url or "").strip()
    if not youtube_url:
        raise RuntimeError("youtube_url is empty")

    def _notify(step: int, message: str) -> None:
        if on_progress is None:
            return
        try:
            on_progress(step, message)
        except Exception as e:
            logger.debug("on_progress error ignored: %s", e)

    from google import genai
    from google.genai import types

    client = genai.Client(api_key=settings.GEMINI_API_KEY)

    with tempfile.TemporaryDirectory(prefix="tennis-gemini-") as tmp_dir:
        # 1) 전체 오디오 다운로드
        _notify(1, "🎵 오디오 다운로드 중... (1/3)")
        logger.info("전체 오디오 다운로드 중...")
        audio_path = _download_full_audio(youtube_url, tmp_dir)

        duration = _get_duration(audio_path)
        logger.info("오디오 길이: %.0f초 (%.1f분)", duration, duration / 60)

        # 2) 청크 분할
        chunks = _split_audio(audio_path, tmp_dir, CHUNK_SECONDS)
        logger.info("청크 수: %d", len(chunks))

        # 오디오 다운로드/청크 분할 완료 → 본격 분석 단계 진입 알림
        total_chunks = len(chunks)
        _notify(
            2,
            f"🔍 영상 분석 중... (2/3) — {total_chunks}개 구간 병렬 처리 중",
        )

        # 3) 병렬 청크 분석
        chunk_results = []
        completed = 0
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {
                executor.submit(_analyze_chunk, client, chunk, types): chunk
                for chunk in chunks
            }
            for future in as_completed(futures):
                result = future.result()
                if result:
                    chunk_results.append(result)
                completed += 1
                _notify(
                    2,
                    f"🔍 영상 분석 중... (2/3) — {completed}/{total_chunks} 구간 완료",
                )

        chunk_results.sort(key=lambda x: x.get("offset_sec", 0))
        logger.info("성공한 청크: %d/%d", len(chunk_results), len(chunks))

        if not chunk_results:
            raise RuntimeError("모든 청크 분석 실패")

        # 4) 최종 합산
        if len(chunk_results) == 1:
            # 청크가 1개면 바로 최종 형식으로 변환
            r = chunk_results[0]
            feedbacks = r.get("feedbacks", [])
            parsed = {
                "card1_problem": feedbacks[0].get("problem") if feedbacks else None,
                "card2_cueing": feedbacks[0].get("fix") if feedbacks else None,
                "card3_action": None,
                "full_summary": None,
                "keywords": r.get("keywords", []),
                "lesson_type": r.get("lesson_type", []),
                "steps": r.get("steps", []),
                "scenarios": r.get("scenarios", []),
                "timestamps": [
                    {
                        "sec": fb["sec"],
                        "type": fb.get("type", "교정"),
                        "category": fb.get("category", ""),
                        "label": fb.get("label") or fb.get("problem", ""),
                        "quote": fb.get("quote", ""),
                        "problem": fb.get("problem", ""),
                        "fix": fb.get("fix", ""),
                        "importance": _normalize_importance(fb.get("importance")),
                        "confidence": fb.get("confidence"),
                    }
                    for fb in feedbacks
                ],
            }
        else:
            # 합산 단계 진입 알림 (3/3)
            _notify(3, "📝 오답노트 정리 중... (3/3)")
            logger.info("청크 결과 합산 중...")
            parsed = _merge_chunks(client, chunk_results, types)

    return {
        "card1_problem":   str(parsed.get("card1_problem") or "").strip() or None,
        "card2_cueing":    str(parsed.get("card2_cueing")  or "").strip() or None,
        "card3_action":    str(parsed.get("card3_action")  or "").strip() or None,
        "full_summary":    str(parsed.get("full_summary")  or "").strip() or None,
        "keywords":        _coerce_keywords(parsed.get("keywords")),
        "lesson_type":     _coerce_lesson_type(parsed.get("lesson_type")),
        "steps":           _coerce_steps(parsed.get("steps")),
        "scenarios":       _coerce_scenarios(parsed.get("scenarios")),
        "timestamps":      _compact_timestamps(_coerce_timestamps(parsed.get("timestamps"))),
        "gemini_model":    settings.GEMINI_MODEL,
    }


def generate_lesson_report_youtube_url(
    youtube_url: str,
    on_progress: Optional[ProgressCallback] = None,
) -> dict:
    """Gemini가 public YouTube URL을 직접 읽는 실험 경로.

    yt-dlp 다운로드 없이 YouTube URL을 Gemini의 video URI input으로 전달한다.
    public YouTube 영상에서만 동작하며, preview 성격의 Gemini 기능에 의존한다.
    """
    settings = get_settings()
    if not settings.GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not configured")

    youtube_url = (youtube_url or "").strip()
    if not youtube_url:
        raise RuntimeError("youtube_url is empty")

    def _notify(step: int, message: str) -> None:
        if on_progress is None:
            return
        try:
            on_progress(step, message)
        except Exception as e:
            logger.debug("on_progress error ignored: %s", e)

    from google import genai
    from google.genai import types

    _notify(1, "🎬 YouTube 영상을 Gemini로 불러오는 중... (1/3)")
    client = genai.Client(api_key=settings.GEMINI_API_KEY)

    duration_sec = _estimate_youtube_duration_sec(youtube_url)
    if duration_sec <= 0:
        duration_sec = YOUTUBE_URL_FALLBACK_DURATION_SEC
    duration_sec = min(duration_sec, YOUTUBE_URL_MAX_DURATION_SEC)
    total_segments = max(1, (duration_sec + YOUTUBE_URL_SEGMENT_SECONDS - 1) // YOUTUBE_URL_SEGMENT_SECONDS)

    _notify(2, f"🔍 Gemini가 영상을 구간별 분석 중... (2/3) — 0/{total_segments} 구간 완료")
    logger.info(
        "[gemini-youtube] YouTube URL 구간 분석 중: %s duration=%ds segments=%d",
        youtube_url,
        duration_sec,
        total_segments,
    )

    segment_results: List[Dict[str, Any]] = []
    for idx, start_sec in enumerate(range(0, duration_sec, YOUTUBE_URL_SEGMENT_SECONDS), start=1):
        end_sec = min(start_sec + YOUTUBE_URL_SEGMENT_SECONDS, duration_sec)
        result = _analyze_youtube_url_segment(client, types, youtube_url, start_sec, end_sec)
        if result:
            segment_results.append(result)
        _notify(2, f"🔍 Gemini가 영상을 구간별 분석 중... (2/3) — {idx}/{total_segments} 구간 완료")
        # duration 추정이 부정확해 영상 실제 길이를 넘겼다고 모델이 보고하면
        # 이후 구간은 존재하지 않는 내용을 지어낼 위험이 있으므로 즉시 중단.
        if result and result.get("video_ended"):
            logger.info(
                "[gemini-youtube] 영상 종료 감지 (offset=%ds) — 이후 구간 분석 중단",
                start_sec,
            )
            break

    if not segment_results:
        raise RuntimeError("Gemini YouTube URL 구간 분석 결과가 비어 있습니다")

    _notify(3, "📝 오답노트 정리 중... (3/3)")
    logger.info("[gemini-youtube] 구간 분석 완료: %d/%d", len(segment_results), total_segments)
    parsed = _merge_chunks(client, segment_results, types)

    return {
        "card1_problem": str(parsed.get("card1_problem") or "").strip() or None,
        "card2_cueing":  str(parsed.get("card2_cueing")  or "").strip() or None,
        "card3_action":  str(parsed.get("card3_action")  or "").strip() or None,
        "full_summary":  str(parsed.get("full_summary")  or "").strip() or None,
        "keywords":      _coerce_keywords(parsed.get("keywords")),
        "lesson_type":   _coerce_lesson_type(parsed.get("lesson_type")),
        "steps":         _coerce_steps(parsed.get("steps")),
        "scenarios":     _coerce_scenarios(parsed.get("scenarios")),
        "timestamps":    _compact_timestamps(_coerce_timestamps(parsed.get("timestamps"))),
        "gemini_model":  settings.GEMINI_MODEL,
    }


def _format_mmss(sec: int) -> str:
    return f"{sec // 60:02d}:{sec % 60:02d}"


def _estimate_youtube_duration_sec(youtube_url: str) -> int:
    """Best-effort duration lookup for segment planning.

    Metadata lookup is only used to size Gemini URL segments. If it fails, the
    caller falls back to a conservative default duration.
    """
    try:
        from app.services import youtube_service

        video_id = youtube_service.extract_video_id(youtube_url)
        meta = youtube_service.get_video_metadata(video_id)
        duration = meta.get("duration_sec")
        if duration:
            return int(duration)
    except Exception as e:
        logger.info("[gemini-youtube] duration lookup skipped: %s", e)
    return 0


def _analyze_youtube_url_segment(
    client: Any,
    types: Any,
    youtube_url: str,
    start_sec: int,
    end_sec: int,
) -> Optional[Dict[str, Any]]:
    prompt = YOUTUBE_URL_SEGMENT_PROMPT_TEMPLATE.format(
        start_label=_format_mmss(start_sec),
        end_label=_format_mmss(end_sec),
        start_sec=start_sec,
        end_sec=end_sec,
    )
    try:
        response = client.models.generate_content(
            model=get_settings().GEMINI_MODEL,
            contents=[
                types.Part.from_uri(
                    file_uri=youtube_url,
                    mime_type="video/*",
                    media_resolution=types.PartMediaResolutionLevel.MEDIA_RESOLUTION_MEDIUM,
                ),
                types.Part.from_text(text=prompt),
            ],
            config=types.GenerateContentConfig(
                temperature=0.1,
                max_output_tokens=8192,
                thinking_config=types.ThinkingConfig(thinking_budget=1024),
            ),
        )
        raw = response.text or ""
        logger.info(
            "[gemini-youtube] 구간 응답 (%s~%s, 길이=%d): %s",
            _format_mmss(start_sec),
            _format_mmss(end_sec),
            len(raw),
            raw[:240],
        )
        parsed = _parse_json(raw)
    except Exception as e:
        logger.warning(
            "[gemini-youtube] 구간 분석 실패 (%s~%s): %s",
            _format_mmss(start_sec),
            _format_mmss(end_sec),
            e,
        )
        return None

    video_ended = bool(parsed.get("video_ended"))

    feedbacks = []
    for fb in ([] if video_ended else parsed.get("feedbacks", [])):
        if not isinstance(fb, dict):
            continue
        sec = _coerce_float(fb.get("sec"))
        if sec is None:
            continue
        sec = int(round(_clamp_float(sec, float(start_sec), float(end_sec))))

        confidence = _coerce_float(fb.get("confidence"), 1.0)
        if confidence is not None and confidence < MIN_FEEDBACK_CONFIDENCE:
            continue

        fb["sec"] = sec
        fb["type"] = str(fb.get("type") or "교정").strip()
        if fb["type"] not in ("교정", "드릴", "전술"):
            fb["type"] = "교정"
        fb["importance"] = _normalize_importance(fb.get("importance"))
        if confidence is not None:
            fb["confidence"] = round(_clamp_float(confidence, 0.0, 1.0), 2)
        feedbacks.append(fb)

    return {
        "offset_sec": start_sec,
        "feedbacks": feedbacks,
        "keywords": _coerce_keywords(parsed.get("keywords")),
        "video_ended": video_ended,
    }


# ─── Whisper 경로 (TRANSCRIPT_ENGINE=whisper) ──────────────────────────

WHISPER_TRANSCRIPT_PROMPT = (
    '당신은 테니스 레슨 분석 전문가입니다.\n\n'
    '아래는 테니스 레슨 영상을 Whisper STT로 전사한 스크립트입니다.\n'
    '각 줄은 "[시작초~종료초] 발화 내용" 형식입니다.\n\n'
    '{transcript}\n\n'
    '{{"card1_problem": "코치가 반복적으로 지적한 핵심 문제(고질병) 1~2문장", '
    '"card2_cueing": "코치가 제시한 핵심 이미지/큐잉 1~2문장", '
    '"card3_action": "다음 연습 때 집중할 구체 행동 1~2문장", '
    '"full_summary": "레슨 전체 흐름 요약 3~5문단", '
    '"keywords": ["키워드1", "키워드2", "키워드3"], '
    '"lesson_type": ["포핸드"], '
    '"steps": ["① 단계1", "② 단계2"], '
    '"scenarios": [{{"condition": "상황", "action": "대처"}}], '
    '"timestamps": [{{"sec": 정수, "category": "포핸드", "label": "문제 요약", "quote": "코치 발언 원문", "fix": "교정 방법"}}]}}\n\n'
    '규칙:\n'
    '1) 모든 문자열은 한국어.\n'
    '2) keywords는 정확히 3개.\n'
    '3) timestamps: 주요 피드백 장면 15~20개. sec은 스크립트의 시작초 그대로 사용 (추정 금지).\n'
    '4) lesson_type: ["포핸드","백핸드","발리","서브","로브","스텝","풋워크","게임레슨","드롭샷","어프로치"] 중 1~3개.\n'
    '5) steps: 코치가 알려준 기술 동작 ①②③ 순서로 3~6개. 없으면 [].\n'
    '6) scenarios: 상황별 대처법. 없으면 [].\n'
    '7) 순수 JSON만 출력. 마크다운 펜스 금지.'
)


def generate_lesson_report_whisper(
    youtube_url: str,
    on_progress: Optional[ProgressCallback] = None,
) -> dict:
    """Whisper STT 경로: 로컬 전사 후 텍스트로 Gemini 분석.

    타임스탬프 정확도가 높지만 전사 시간이 더 걸린다.
    """
    settings = get_settings()
    if not settings.GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not configured")

    youtube_url = (youtube_url or "").strip()
    if not youtube_url:
        raise RuntimeError("youtube_url is empty")

    def _notify(step: int, message: str) -> None:
        if on_progress is None:
            return
        try:
            on_progress(step, message)
        except Exception as e:
            logger.debug("on_progress error ignored: %s", e)

    with tempfile.TemporaryDirectory(prefix="tennis-whisper-") as tmp_dir:
        # 1) 오디오 다운로드
        _notify(1, "🎵 오디오 다운로드 중... (1/3)")
        logger.info("[whisper] 오디오 다운로드 중...")
        audio_path = _download_full_audio(youtube_url, tmp_dir)
        duration = _get_duration(audio_path)
        logger.info("[whisper] 오디오 길이: %.0f초", duration)

        # 2) Whisper 전사
        _notify(2, "🎙️ 음성 인식 중... (2/3) — 시간이 걸릴 수 있습니다")
        logger.info("[whisper] faster-whisper 전사 시작...")
        from faster_whisper import WhisperModel
        model = WhisperModel(
            settings.WHISPER_MODEL_SIZE,
            device=settings.WHISPER_DEVICE,
            compute_type="int8",
        )
        segments, _ = model.transcribe(audio_path, language="ko", beam_size=5)

        lines = []
        for seg in segments:
            lines.append(f"[{seg.start:.1f}~{seg.end:.1f}초] {seg.text.strip()}")
        transcript_text = "\n".join(lines)
        logger.info("[whisper] 전사 완료: %d 세그먼트", len(lines))

        # 3) Gemini로 분석
        _notify(3, "📝 오답노트 정리 중... (3/3)")
        logger.info("[whisper] Gemini 분석 중...")
        from google import genai
        from google.genai import types
        client = genai.Client(api_key=settings.GEMINI_API_KEY)

        prompt = WHISPER_TRANSCRIPT_PROMPT.format(transcript=transcript_text)
        response = client.models.generate_content(
            model=settings.GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.3,
                max_output_tokens=8192,
                thinking_config=types.ThinkingConfig(thinking_budget=0),
            ),
        )
        parsed = _parse_json(response.text or "")

    return {
        "card1_problem": str(parsed.get("card1_problem") or "").strip() or None,
        "card2_cueing":  str(parsed.get("card2_cueing")  or "").strip() or None,
        "card3_action":  str(parsed.get("card3_action")  or "").strip() or None,
        "full_summary":  str(parsed.get("full_summary")  or "").strip() or None,
        "keywords":      _coerce_keywords(parsed.get("keywords")),
        "lesson_type":   _coerce_lesson_type(parsed.get("lesson_type")),
        "steps":         _coerce_steps(parsed.get("steps")),
        "scenarios":     _coerce_scenarios(parsed.get("scenarios")),
        "timestamps":    _compact_timestamps(_coerce_timestamps(parsed.get("timestamps"))),
        "gemini_model":  settings.GEMINI_MODEL,
        "transcript_text": transcript_text,
    }
