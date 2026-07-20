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
    '당신은 오디오 전사(transcription) 담당자입니다. 테니스 지식으로 내용을 채우거나 '
    '"이런 상황이면 코치가 보통 이렇게 말한다"는 추론을 하는 것은 엄격히 금지됩니다.\n\n'
    '아래는 코치가 수강생에게 1:1 테니스 레슨을 진행하는 오디오 클립입니다.\n'
    '이 클립에서 코치가 한 발언 중, 당신이 단어 단위로 정확하게 알아들은 발언만 '
    'JSON으로 추출하세요.\n\n'
    '절대 규칙 — 위반 시 전체 응답이 폐기됩니다:\n'
    '- quote는 실제로 들은 말을 한 글자도 바꾸지 않고 그대로 옮긴 것이어야 합니다. '
    '"~라는 취지", "~에 가까운 말", "대략" 같은 재구성/의역/추론은 절대 금지입니다.\n'
    '- 발화가 흐릿하거나, 숫자 세기, 이름/호칭 부르기, 짧은 감탄사, 공 치는 소리, '
    '무의미한 잡음뿐이라면 그 장면은 절대 feedbacks에 넣지 마세요. 내용을 지어내서 '
    '채우지 마세요.\n'
    '- 이 클립에 명확히 들리는 코치의 교정/드릴/전술 발언이 하나도 없다면, feedbacks를 '
    '반드시 빈 배열 []로 반환하세요. 빈 배열은 정상적이고 바람직한 응답입니다. 개수를 '
    '채우려고 애쓰지 마세요.\n\n'
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
    'type: "교정"(잘못된 동작 지적/교정), "드릴"(연습 방법·순서), "전술"(경기 상황 판단) 중 하나.\n'
    'category: 포핸드/백핸드/발리/서브/로브/스텝/풋워크/기타 중 하나.\n'
    'local_start_sec: 이 클립 안에서 해당 코치 발언이 시작된 대략 초. 0 이상 클립 길이 이하 숫자.\n'
    'local_end_sec: 이 클립 안에서 해당 코치 발언이 끝난 대략 초. 모르면 local_start_sec와 같게.\n'
    'label: 발언 내용 핵심 20자 이내.\n'
    'quote: 실제 들린 코치 발언 원문 그대로. 요약/의역 금지. 수강생 발화 혼입 금지.\n'
    'problem: 코치가 지적한 문제 동작. 명확하지 않으면 빈 문자열.\n'
    'fix: 교정법 또는 드릴·전술 내용. 오디오에서 언급된 것만.\n'
    'importance: 레슨 복기에 중요한 핵심 피드백이면 high, 일반 지시면 medium, 보조적이면 low.\n'
    'confidence: "이 발언을 실제로 정확히 들었다고 확신하는 정도". 조금이라도 추측이 '
    '섞였다면 0.65 미만으로 낮추세요(이 경우 자동 제외됩니다).\n'
    '테니스 용어 참고: 타점·팔로우스루·내전·라켓드롭·토스·발리·스플릿스텝·풋워크·크로스·다운더라인.\n'
    '수강생 대답/추임새("네","아","맞아요"), 단순 칭찬/진행 멘트("좋아","오케이","그렇지","자"), '
    '카운트만 하는 말, 단순 시작 신호("시작","준비","하나 둘")는 제외.\n'
    'feedbacks는 최대 5개. 교정·드릴·전술 모두 포함. 순수 JSON만, 펜스 금지.'
)

MERGE_PROMPT_TEMPLATE = (
    '당신은 테니스 레슨 분석 전문가입니다.\n'
    '코치가 수강생에게 진행한 1:1 레슨을 짧은 구간별로 분석한 결과입니다.\n'
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


def _coerce_ai_context(value: Any) -> List[Dict[str, str]]:
    """09문서 1-6: AI 보조 설명 항목. quote 필드가 없어 verify_report 검증
    대상에서 애초에 제외된다 — 프론트에서 "AI 보조 설명" 라벨과 함께
    코치 인용 영역과 분리 노출해야 함(코드 레벨로는 강제 불가)."""
    if not isinstance(value, list):
        return []
    out = []
    for item in value:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title", "")).strip()
        note = str(item.get("note", "")).strip()
        if title and note:
            out.append({"title": title[:20], "note": note[:200]})
    return out[:3]


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
        coerced = {
            "sec": sec,
            "type": ts_type,
            "category": str(item.get("category", "")).strip() or None,
            "label": str(item.get("label", "")).strip() or "주요 지적",
            "quote": str(item.get("quote", "")).strip() or None,
            "problem": str(item.get("problem", "")).strip() or None,
            "fix": str(item.get("fix", "")).strip() or None,
            "importance": _normalize_importance(item.get("importance")),
            "confidence": round(_clamp_float(confidence, 0.0, 1.0), 2) if confidence is not None else None,
        }
        # 검증기 통과 메타 (whisper 검증 경로에서만 존재)
        match_score = _coerce_float(item.get("match_score"))
        if match_score is not None:
            coerced["match_score"] = round(_clamp_float(match_score, 0.0, 1.0), 3)
        out.append(coerced)
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
                temperature=0.1,
                max_output_tokens=65536,
                thinking_config=types.ThinkingConfig(thinking_budget=1024),
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
    '코치가 수강생에게 1:1 테니스 레슨을 진행하는 오디오입니다.\n\n'
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
    '첨부된 YouTube 레슨 영상을 직접 보고/듣고, 코치가 수강생에게 한 '
    '명확한 테니스 피드백만 추출해 오답노트 JSON을 작성하세요.\n\n'
    '중요한 구분:\n'
    '- 코치: 지시·교정·시범·설명을 하는 쪽입니다.\n'
    '- 수강생: 질문하거나 "네", "아" 등으로 반응하는 쪽입니다.\n'
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

# 영상 실제 길이를 알 때 쓰는 프롬프트. video_ended 필드를 아예 요구하지 않는다 —
# 이 필드를 판단하게 하면 모델이 발화가 뜸하거나 잡음이 많은 구간을 "영상이
# 끝났다"로 오판하고, 그 구간에 실제 존재하는 피드백까지 통째로 비우는 사고가
# 반복 확인됨(실제 오디오 STT 대조로 검증). duration을 알면 어차피 range()가
# 존재하는 구간까지만 순회하므로 이 필드가 필요 없다.
YOUTUBE_URL_SEGMENT_PROMPT_TEMPLATE = (
    '당신은 오디오/영상 전사(transcription) 담당자입니다. 테니스 지식으로 내용을 채우거나 '
    '"이런 상황이면 코치가 보통 이렇게 말한다"는 추론을 하는 것은 엄격히 금지됩니다.\n\n'
    '첨부된 YouTube 레슨 영상 중 {start_label}~{end_label} 구간만 실제로 보고/들으세요. '
    '이 구간에 코치가 수강생에게 한 발언 중, 당신이 단어 단위로 정확하게 알아들은 '
    '발언만 JSON으로 추출하세요.\n\n'
    '절대 규칙 — 위반 시 전체 응답이 폐기됩니다:\n'
    '- quote는 실제로 들은 말을 한 글자도 바꾸지 않고 그대로 옮긴 것이어야 합니다. '
    '"~라는 취지", "~에 가까운 말", "대략" 같은 재구성/의역/추론은 절대 금지입니다.\n'
    '- 발화가 흐릿하거나, 숫자 세기("하나 둘 셋"), 이름/호칭 부르기, 짧은 감탄사("어!", "좋아"), '
    '공 치는 소리, 무의미한 잡음뿐이라면 그 장면은 절대 feedbacks에 넣지 마세요. '
    '내용을 지어내서 채우지 마세요.\n'
    '- 이 구간에 명확히 들리는 코치의 교정/드릴/전술 발언이 하나도 없다면, '
    'feedbacks를 반드시 빈 배열 []로 반환하세요. 빈 배열은 정상적이고 바람직한 응답입니다. '
    '개수를 채우려고 애쓰지 마세요. 잡음이 많거나 알아듣기 어렵다는 것이 "코치 발언이 없다"는 '
    '뜻은 아닙니다 — 잡음 속에서도 명확히 들리는 발언이 있으면 반드시 포함하세요. '
    '이 구간은 영상 실제 재생 구간이 확정되어 있으니, "영상이 끝났는지"는 판단하지 마세요.\n\n'
    '{{"feedbacks": ['
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
    '6) 순수 JSON만 출력. 마크다운 펜스 금지.'
)

# 영상 길이를 모를 때(fallback 추정 75분 사용 중)만 video_ended로 조기 중단
# 신호를 받는다 — 이때는 fallback이 실제보다 길 위험이 있어 존재하지 않는
# 구간을 지어낼 위험이 이 필드를 두는 것보다 더 크기 때문.
YOUTUBE_URL_SEGMENT_PROMPT_TEMPLATE_UNKNOWN_DURATION = (
    '당신은 오디오/영상 전사(transcription) 담당자입니다. 테니스 지식으로 내용을 채우거나 '
    '"이런 상황이면 코치가 보통 이렇게 말한다"는 추론을 하는 것은 엄격히 금지됩니다.\n\n'
    '첨부된 YouTube 레슨 영상 중 {start_label}~{end_label} 구간만 실제로 보고/들으세요. '
    '이 구간에 코치가 수강생에게 한 발언 중, 당신이 단어 단위로 정확하게 알아들은 '
    '발언만 JSON으로 추출하세요.\n\n'
    '절대 규칙 — 위반 시 전체 응답이 폐기됩니다:\n'
    '- quote는 실제로 들은 말을 한 글자도 바꾸지 않고 그대로 옮긴 것이어야 합니다. '
    '"~라는 취지", "~에 가까운 말", "대략" 같은 재구성/의역/추론은 절대 금지입니다.\n'
    '- 발화가 흐릿하거나, 숫자 세기("하나 둘 셋"), 이름/호칭 부르기, 짧은 감탄사("어!", "좋아"), '
    '공 치는 소리, 무의미한 잡음뿐이라면 그 장면은 절대 feedbacks에 넣지 마세요. '
    '내용을 지어내서 채우지 마세요.\n'
    '- 이 구간에 명확히 들리는 코치의 교정/드릴/전술 발언이 하나도 없다면, '
    'feedbacks를 반드시 빈 배열 []로 반환하세요. 빈 배열은 정상적이고 바람직한 응답입니다. '
    '개수를 채우려고 애쓰지 마세요. 잡음이 많거나 알아듣기 어렵다는 것이 "코치 발언이 없다"는 '
    '뜻은 아닙니다 — 잡음 속에서도 명확히 들리는 발언이 있으면 반드시 포함하세요.\n'
    '- 영상의 실제 길이가 {start_label}보다 짧아서 이 구간이 아예 존재하지 않을 수 있습니다. '
    '그런 경우에만 video_ended를 true로 설정하고 feedbacks를 빈 배열로 반환하세요. '
    '단순히 발화가 적거나 잡음이 많다는 이유로 video_ended를 true로 하면 안 됩니다.\n\n'
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
    '6) video_ended는 "이 구간이 영상 실제 길이를 벗어나 존재하지 않음"을 뜻합니다. '
    '발화가 적다는 이유로 true로 하지 마세요. 불확실하면 false.\n'
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
        # 15문서 2-A: 이 경로는 whisper 검증 게이트조차 없어 인용 신뢰도가
        # whisper 경로보다도 낮다고 봐야 함 — 항상 low.
        "transcript_quality": "low",
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

    video_title = _get_youtube_title_via_gemini(client, types, youtube_url)

    estimated_duration_sec = _estimate_youtube_duration_sec(youtube_url)
    duration_is_known = estimated_duration_sec > 0
    duration_sec = estimated_duration_sec if duration_is_known else YOUTUBE_URL_FALLBACK_DURATION_SEC
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
        result = _analyze_youtube_url_segment(
            client, types, youtube_url, start_sec, end_sec,
            duration_is_known=duration_is_known,
        )
        if result:
            segment_results.append(result)
        _notify(2, f"🔍 Gemini가 영상을 구간별 분석 중... (2/3) — {idx}/{total_segments} 구간 완료")
        # duration_sec를 실제로 알고 있으면(메타데이터 조회 성공) 그 값이 근거가
        # 확실하므로 range()가 이미 정확한 구간까지만 순회한다 — 모델의 video_ended
        # 자기보고는 무시한다. 한 구간에 발화가 뜸했을 뿐인데 모델이 "영상이
        # 끝났다"고 착각해 그 이후 구간을 통째로 스킵하는 사고가 실제로 발생했음
        # (59분 영상, 10분 지점에서 video_ended=true 오판 → 이후 49분 누락).
        # duration을 모를 때(fallback 75분 추정)만 모델의 판단을 신뢰해 중단한다 —
        # 이 경우엔 fallback이 실제보다 길 위험이 있어 존재하지 않는 구간을
        # 지어낼 위험이 더 크기 때문.
        if not duration_is_known and result and result.get("video_ended"):
            logger.info(
                "[gemini-youtube] 영상 종료 감지 (offset=%ds, fallback 추정 사용 중) — 이후 구간 분석 중단",
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
        "video_title":   video_title,
        # 15문서 2-A: 검증 게이트 없음 — 항상 low.
        "transcript_quality": "low",
    }


def _get_youtube_title_via_gemini(client: Any, types: Any, youtube_url: str) -> Optional[str]:
    """Gemini가 이미 로드한 YouTube 영상에서 실제 제목을 직접 읽어 반환한다.

    yt-dlp 메타 조회가 막혀도(예: 봇 차단) Gemini 경로에서는 제목을 얻을 수 있게
    별도의 경량 호출로 분리했다. 실패 시 None을 반환해 호출부가 yt-dlp로 폴백한다.
    """
    prompt = (
        '첨부된 YouTube 영상의 실제 제목을 그대로 알려주세요. '
        '{"title": "영상 제목"} 형식의 순수 JSON만 출력하세요. 마크다운 펜스 금지.'
    )
    try:
        response = client.models.generate_content(
            model=get_settings().GEMINI_MODEL,
            contents=[
                types.Part.from_uri(file_uri=youtube_url, mime_type="video/*"),
                types.Part.from_text(text=prompt),
            ],
            config=types.GenerateContentConfig(temperature=0.0, max_output_tokens=256),
        )
        parsed = _parse_json(response.text or "")
        title = str(parsed.get("title") or "").strip()
        return title or None
    except Exception as e:
        logger.info("[gemini-youtube] title lookup skipped: %s", e)
        return None


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
    duration_is_known: bool = False,
) -> Optional[Dict[str, Any]]:
    template = (
        YOUTUBE_URL_SEGMENT_PROMPT_TEMPLATE
        if duration_is_known
        else YOUTUBE_URL_SEGMENT_PROMPT_TEMPLATE_UNKNOWN_DURATION
    )
    prompt = template.format(
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

    # duration을 실제로 알 때는 이 구간이 range() 상 존재가 확정된 구간이므로
    # 모델의 video_ended 자기보고로 정상 피드백을 폐기하지 않는다.
    video_ended = bool(parsed.get("video_ended")) and not duration_is_known

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


# ─── Whisper 검증 경로 (TRANSCRIPT_ENGINE=whisper | whisper-verified) ──
#
# 설계 원칙: "LLM이 오디오를 듣고 판단"하는 구조를 버리고,
#   신뢰 가능한 STT 전사 → LLM은 전사 텍스트의 구조화만 → 코드 레벨 인용 검증
# 3단으로 분리한다. LLM이 전사에 없는 내용을 지어내면 verification 게이트에서
# timestamps/card가 자동 폐기되므로 할루시네이션이 최종 리포트에 도달할 수 없다.
#
# 09문서 1-5: Pass A(추출)와 Pass B(전체 종합)로 분리.
#
# 원래 가설은 "전사를 10~15분 창으로 나눠 각각 Pass A를 호출하면 창마다
# 완전한 주의를 받아 리콜이 오른다"였다. 실측(2026-07-17, Wh2B6VyR_ys
# 56.9분, 캐시된 동일 STT 결과로 창 크기만 바꿔 A/B)으로 정반대 결과가
# 나와 이 가설은 반증됨:
#   10분 창(5개) → 검증통과 8개 / 15분 창(4개) → 12개 / 20분 창(3개) → 11개
#   30분 창(2개) → 15개 / 단일 창(1개, 전체) → 13개
# 창을 작게 나눌수록 오히려 리콜이 떨어졌다 — 개수 가이드가 작은 창에서
# LLM을 더 소극적으로 만들거나, 창 경계가 문맥을 끊어 판단을 방해하는
# 것으로 추정. 반면 "추출 전용 프롬프트로 Pass A/B를 분리"한 것 자체는
# 유효했다(기존 단일 호출 통합 프롬프트 10개 → Pass A 단일 호출 13개).
#
# 결론: 창 분할은 쓰지 않고 Pass A를 전체 전사에 대해 한 번만 호출한다.
# WHISPER_PASS_A_WINDOW_SEC를 영상 최대 허용 길이보다 크게 잡아 항상
# 단일 창이 되도록 한다(YTDLP_MAX_DURATION_SEC 기본 5400s=90분보다 크게).
# split_segments_into_windows 자체는 향후 다른 실험을 위해 남겨둔다.
WHISPER_PASS_A_WINDOW_SEC = 24 * 3600
# 개수 가이드는 영상 길이에 비례한다(고정값 "15~30개"는 60분 영상에서도
# 동일해 리콜을 강제로 낮추는 효과가 있었음 — 09문서 1-5 원 문제 진단은
# 유효, 해법만 "창 분할"이 아니라 "단일 호출 + 길이비례 가이드"로 수정).
WHISPER_PASS_A_MIN_PER_10MIN = 3
WHISPER_PASS_A_MAX_PER_10MIN = 8

WHISPER_PASS_A_PROMPT = (
    '당신은 테니스 레슨 전사 스크립트에서 코치 피드백만 추출하는 담당자입니다.\n'
    '테니스 지식으로 내용을 보충하거나 "코치가 보통 이렇게 말한다"는 추론은 엄격히 금지됩니다.\n\n'
    '아래는 코치가 수강생에게 진행한 테니스 레슨 전체 중 '
    '{window_label} 구간의 STT 전사 스크립트입니다. 수강생은 한 명일 수도 '
    '있고(1:1 레슨) 여러 명일 수도 있습니다(게임 레슨·그룹 레슨) — 스크립트만 '
    '보고 판단하세요.\n'
    '각 줄은 "[시작초~종료초] 발화 내용" 형식입니다(초는 영상 전체 기준).\n\n'
    '===== 전사 스크립트 시작 =====\n'
    '{transcript}\n'
    '===== 전사 스크립트 끝 =====\n\n'
    '절대 규칙 — 위반 항목은 자동 검증기에서 폐기됩니다:\n'
    '- 스크립트에 없는 내용은 한 글자도 쓰지 마세요.\n'
    '- quote는 위 스크립트의 발화 내용에서 연속된 구간을 한 글자도 바꾸지 않고 '
    '그대로 복사한 것이어야 합니다. 요약/의역/재구성 금지.\n'
    '- sec는 그 quote가 포함된 줄의 시작초를 그대로 사용하세요. 추정 금지.\n'
    '- 이 구간에 명확한 코치 피드백이 없으면 feedbacks를 빈 배열로 반환하세요. '
    '개수를 채우려고 애쓰지 마세요.\n\n'
    '아래 JSON 하나만 출력하세요:\n'
    '{{"feedbacks": [{{"sec": 정수, "type": "교정", "category": "포핸드", '
    '"label": "20자 이내 요약", "quote": "스크립트 원문 그대로 인용", '
    '"problem": "코치가 지적한 문제", "fix": "교정법", "importance": "high"}}], '
    '"keywords": ["키워드1", "키워드2"]}}\n\n'
    '규칙:\n'
    '1) 모든 문자열은 한국어. keywords는 이 구간에 실제로 등장한 단어만, 최대 3개.\n'
    '2) feedbacks: 이 구간 길이({window_minutes}분) 기준 {min_count}~{max_count}개 '
    '가이드 — 이보다 적어도 되고(진짜 피드백이 적으면), 실제로 그만큼 있다면 '
    '가이드를 넘어도 됩니다. 개수 맞추기보다 스크립트에 있는 코치의 명확한 '
    '교정/드릴/전술 발언을 빠짐없이 담는 것이 우선입니다.\n'
    '3) 수강생이 여러 명인 게임·그룹 레슨에서는 특정 수강생 이름을 지적하는 '
    '개별 교정("재호씨는~")과, 전체를 대상으로 한 경기 운영·포지션·순서에 '
    '관한 전술 지시("공이 짧으면 들어와", "로테이션")를 구분해 type을 '
    '정하세요 — 전자는 "교정", 후자는 "전술"에 가깝습니다.\n'
    '4) 수강생 반응, 카운트, 단순 칭찬/진행 멘트("좋아","오케이","자")는 제외.\n'
    '5) type은 "교정", "드릴", "전술" 중 하나. importance는 high|medium|low.\n'
    '6) category는 포핸드/백핸드/발리/서브/로브/스텝/풋워크/기타 중 하나.\n'
    '7) problem/fix도 스크립트에서 언급된 것만. 명확하지 않으면 빈 문자열.\n'
    '8) 순수 JSON만 출력. 마크다운 펜스 금지.'
)

# 09문서 1-6: "검증된 사실" vs "AI 보조 설명" 2계층 리포트.
# card1~3/timestamps는 verify_report()가 quote를 전사 원문과 대조하는 검증
# 대상이지만, ai_context는 quote 필드 자체가 없어 검증 대상에서 애초에
# 제외된다 — 즉 AI의 일반 테니스 지식(용어 설명, 왜 이 교정이 중요한지,
# 추천 셀프 드릴)을 안전하게 노출하는 별도 채널이다. 프론트에서 반드시
# "AI 보조 설명" 라벨과 함께 코치 인용 영역과 시각적으로 분리해 노출해야
# 사용자가 "코치가 실제로 한 말"과 혼동하지 않는다.
WHISPER_PASS_B_PROMPT = (
    '당신은 테니스 레슨 코칭 리포트를 종합하는 담당자입니다.\n'
    '아래는 한 레슨 전체를 구간별로 나눠 이미 추출·검증된 코치 피드백 목록입니다 '
    '(이미 전사 원문과 대조를 마친 사실만 포함되어 있으니 내용을 그대로 신뢰하세요).\n\n'
    '===== 검증된 피드백 목록 시작 =====\n'
    '{verified_feedbacks}\n'
    '===== 검증된 피드백 목록 끝 =====\n\n'
    '규칙:\n'
    '- 위 목록에 있는 내용만 근거로 사용하세요. 목록에 없는 내용을 지어내지 마세요.\n'
    '- card1_evidence/card2_evidence/card3_evidence는 각 항목의 quote 줄에 있는 '
    '큰따옴표(") 안쪽 텍스트만을 한 글자도 바꾸지 않고 그대로 복사하세요. '
    '"문제:"나 "교정:" 뒤의 설명, 대괄호 태그, label은 evidence에 절대 '
    '포함하지 마세요 — quote 큰따옴표 안쪽 문장만입니다.\n'
    '- category별 등장 횟수가 표시되어 있다면, card1(고질병)에는 가장 반복된 '
    '지적을 "N회 반복 지적"처럼 정량 근거와 함께 명시하세요.\n'
    '- 목록에 [전술] 태그가 [교정]/[드릴]보다 많거나 특정 수강생 이름이 여러 '
    '명 등장한다면, 이는 다수 수강생 대상 게임·그룹 레슨입니다. 이 경우 '
    'card1~3과 full_summary는 특정 한 명의 개인 교정이 아니라 경기 운영· '
    '포지션·로테이션 등 전술 피드백을 중심으로 작성하고, lesson_type에 '
    '"게임레슨"을 포함하세요.\n'
    '- ai_context는 예외입니다: 코치가 실제로 한 말이 아니라, 당신의 테니스 '
    '일반 지식으로 위 피드백을 보충 설명하는 영역입니다. "코치가 이렇게 '
    '말했다"는 인용문처럼 쓰지 말고, 왜 이 교정이 중요한지·이 용어가 무엇인지· '
    '집에서 해볼 수 있는 셀프 드릴 등을 항목당 1~2문장으로 작성하세요. '
    '위 목록에 없는 일반 지식이어도 괜찮습니다(단, 사실처럼 위장하지 말고 '
    '보충 설명임이 문장 자체로 드러나야 함 — 예: "~때 흔히 쓰는 방법은" '
    '"~에 도움이 되는 연습은").\n\n'
    '아래 JSON 하나만 출력하세요:\n'
    '{{"card1_problem": "코치가 반복 지적한 핵심 문제 1~2문장 (반복 횟수 근거 포함)", '
    '"card1_evidence": "card1의 근거가 된 목록 원문 인용", '
    '"card2_cueing": "코치가 제시한 핵심 이미지/큐잉 1~2문장", '
    '"card2_evidence": "card2의 근거가 된 목록 원문 인용", '
    '"card3_action": "다음 연습 때 집중할 구체 행동 1~2문장", '
    '"card3_evidence": "card3의 근거가 된 목록 원문 인용", '
    '"full_summary": "레슨 전체 흐름 요약 3~5문단 (목록 내용만 사용)", '
    '"lesson_type": ["포핸드"], '
    '"steps": ["① 단계1", "② 단계2"], '
    '"scenarios": [{{"condition": "상황", "action": "대처"}}], '
    '"ai_context": [{{"title": "10자 이내 제목", "note": "보충 설명 1~2문장"}}]}}\n\n'
    '규칙:\n'
    '1) 모든 문자열은 한국어.\n'
    '2) lesson_type: ["포핸드","백핸드","발리","서브","로브","스텝","풋워크",'
    '"게임레슨","드롭샷","어프로치"] 중 1~3개.\n'
    '3) steps: 코치가 알려준 기술 동작 ①②③ 순서로 3~6개. 목록에 없으면 [].\n'
    '4) scenarios: 코치가 언급한 상황별 대처법. 목록에 없으면 [].\n'
    '5) ai_context: 0~3개. 보충할 내용이 없으면 빈 배열 [].\n'
    '6) 순수 JSON만 출력. 마크다운 펜스 금지.'
)


WHISPER_VERIFIED_PROMPT = (
    '당신은 테니스 레슨 전사 스크립트를 구조화하는 담당자입니다.\n'
    '테니스 지식으로 내용을 보충하거나 "코치가 보통 이렇게 말한다"는 추론은 엄격히 금지됩니다.\n\n'
    '아래는 코치가 수강생에게 진행한 1:1 테니스 레슨의 STT 전사 스크립트입니다.\n'
    '각 줄은 "[시작초~종료초] 발화 내용" 형식입니다.\n\n'
    '===== 전사 스크립트 시작 =====\n'
    '{transcript}\n'
    '===== 전사 스크립트 끝 =====\n\n'
    '절대 규칙 — 위반 항목은 자동 검증기에서 폐기됩니다:\n'
    '- 전사 스크립트에 없는 내용은 한 글자도 쓰지 마세요.\n'
    '- 모든 quote와 evidence는 위 스크립트의 발화 내용에서 연속된 구간을 '
    '한 글자도 바꾸지 않고 그대로 복사한 것이어야 합니다. 요약/의역/재구성 금지.\n'
    '- 각 timestamps 항목의 sec는 그 quote가 포함된 줄의 시작초를 그대로 사용하세요. 추정 금지.\n'
    '- 근거가 되는 발화를 스크립트에서 찾을 수 없는 카드는 값을 null로 두세요.\n\n'
    '아래 형식의 JSON 하나만 출력하세요:\n'
    '{{"card1_problem": "코치가 반복 지적한 핵심 문제 1~2문장", '
    '"card1_evidence": "card1의 근거가 된 스크립트 원문 인용", '
    '"card2_cueing": "코치가 제시한 핵심 이미지/큐잉 1~2문장", '
    '"card2_evidence": "card2의 근거가 된 스크립트 원문 인용", '
    '"card3_action": "다음 연습 때 집중할 구체 행동 1~2문장", '
    '"card3_evidence": "card3의 근거가 된 스크립트 원문 인용", '
    '"full_summary": "레슨 전체 흐름 요약 3~5문단 (스크립트 내용만 사용)", '
    '"keywords": ["키워드1", "키워드2", "키워드3"], '
    '"lesson_type": ["포핸드"], '
    '"steps": ["① 단계1", "② 단계2"], '
    '"scenarios": [{{"condition": "상황", "action": "대처"}}], '
    '"timestamps": [{{"sec": 정수, "type": "교정", "category": "포핸드", '
    '"label": "20자 이내 요약", "quote": "스크립트 원문 그대로 인용", '
    '"problem": "코치가 지적한 문제", "fix": "교정법", "importance": "high"}}]}}\n\n'
    '규칙:\n'
    '1) 모든 문자열은 한국어.\n'
    '2) keywords는 정확히 3개. 스크립트에 실제로 등장한 단어만.\n'
    '3) timestamps: 코치의 핵심 교정/드릴/전술 피드백 장면 15~30개. '
    '수강생 반응, 카운트, 단순 칭찬/진행 멘트("좋아","오케이","자")는 제외.\n'
    '4) type은 "교정", "드릴", "전술" 중 하나. importance는 high|medium|low.\n'
    '5) lesson_type: ["포핸드","백핸드","발리","서브","로브","스텝","풋워크",'
    '"게임레슨","드롭샷","어프로치"] 중 1~3개.\n'
    '6) steps: 코치가 알려준 기술 동작 ①②③ 순서로 3~6개. 스크립트에 없으면 [].\n'
    '7) scenarios: 코치가 언급한 상황별 대처법. 스크립트에 없으면 [].\n'
    '8) problem/fix도 스크립트에서 언급된 것만. 명확하지 않으면 빈 문자열.\n'
    '9) 순수 JSON만 출력. 마크다운 펜스 금지.'
)


def _run_pass_a_for_window(
    client: Any,
    types: Any,
    model: str,
    window: "TranscriptWindow",
) -> Dict[str, Any]:
    """단일 창을 Pass A 프롬프트로 추출.

    개수 가이드는 창의 목표 길이(window.window_end - window.window_start)에
    비례한다 — 실제 발화 세그먼트의 시간 범위로 계산하면 발화가 뜸한 창에서
    가이드가 부당하게 깎이는 버그가 있었음(stt_filters.split_segments_into_windows
    docstring 참고).

    Returns:
        {"feedbacks": [...], "keywords": [...]}. 실패 시 양쪽 다 빈 리스트
        (한 창의 실패가 다른 창까지 막지 않도록).
    """
    from app.services.stt_filters import segments_to_transcript_text

    window_label = f"{_format_mmss(int(window.window_start))}~{_format_mmss(int(window.window_end))}"
    window_minutes = max(1, round((window.window_end - window.window_start) / 60))
    min_count = max(1, round(WHISPER_PASS_A_MIN_PER_10MIN * window_minutes / 10))
    max_count = max(min_count, round(WHISPER_PASS_A_MAX_PER_10MIN * window_minutes / 10))

    prompt = WHISPER_PASS_A_PROMPT.format(
        window_label=window_label,
        transcript=segments_to_transcript_text(window.segments),
        window_minutes=window_minutes,
        min_count=min_count,
        max_count=max_count,
    )
    try:
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.0,
                max_output_tokens=8192,
                thinking_config=types.ThinkingConfig(thinking_budget=0),
            ),
        )
        parsed = _parse_json(response.text or "")
        feedbacks = parsed.get("feedbacks")
        keywords = parsed.get("keywords")
        return {
            "feedbacks": feedbacks if isinstance(feedbacks, list) else [],
            "keywords": keywords if isinstance(keywords, list) else [],
        }
    except Exception as e:
        logger.warning("[whisper] Pass A 창 실패 (%s): %s", window_label, e)
        return {"feedbacks": [], "keywords": []}


def generate_lesson_report_whisper(
    youtube_url: str,
    on_progress: Optional[ProgressCallback] = None,
) -> dict:
    """Grounded 파이프라인: STT 전사 → Gemini 2단 구조화(Pass A/B) → 코드 레벨 인용 검증.

    1) yt-dlp 오디오 다운로드
    2) STT_PROVIDER(local faster-whisper | groq)로 전사 + 환청 필터
    3) Pass A: 전사를 WHISPER_PASS_A_WINDOW_SEC 단위 창으로 나눠 각 창에서
       독립적으로 피드백(timestamps) 추출 (09문서 1-5 — 단일 호출 대비 리콜 개선 가설)
    4) verification: Pass A 결과의 모든 quote를 전사 원문과 fuzzy match,
       미매칭 timestamp 폐기 / sec 재계산 — 검증된 사실만 Pass B로 전달
    5) Pass B: 검증된 피드백 목록만 보고 card1/2/3 + steps/scenarios 종합
       (Pass B는 이미 검증된 입력만 다루므로 별도 검증 불필요)

    2)~5)는 _generate_report_from_audio_path로 분리되어 유튜브 경로와
    17문서 U-1 직접 업로드 경로(generate_lesson_report_whisper_from_upload)가
    완전히 공유한다. 이 함수의 유일한 책임은 1) yt-dlp 다운로드.
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
        # audio_path는 tmp_dir 안에 있으므로 파일을 읽는 STT까지 이 블록 안에서 수행.
        return _generate_report_from_audio_path(audio_path, on_progress)


def generate_lesson_report_whisper_from_upload(
    audio_path: str,
    on_progress: Optional[ProgressCallback] = None,
) -> dict:
    """17문서 U-1: 클라이언트가 브라우저(FFmpeg.wasm)에서 추출해 업로드한 오디오
    파일을 입력으로, yt-dlp 다운로드 단계 없이 whisper 검증 파이프라인을 실행.

    유튜브 경로(generate_lesson_report_whisper)와 2)~5) 단계를 완전히 공유하며
    (_generate_report_from_audio_path), 유일한 차이는 1) 오디오 확보 방식이다.
    임시 오디오 파일의 수명은 호출 측(라우터 백그라운드 태스크)이 관리한다.
    """
    settings = get_settings()
    if not settings.GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not configured")

    audio_path = (audio_path or "").strip()
    if not audio_path or not os.path.exists(audio_path):
        raise RuntimeError(f"업로드된 오디오 파일을 찾을 수 없습니다: {audio_path}")

    return _generate_report_from_audio_path(audio_path, on_progress)


def _generate_report_from_audio_path(
    audio_path: str,
    on_progress: Optional[ProgressCallback] = None,
) -> dict:
    """로컬 오디오 파일 경로부터 시작하는 whisper 검증 파이프라인 (2~5단계).

    오디오를 어떻게 확보했는지(yt-dlp 다운로드 / 직접 업로드)와 무관하게
    STT 전사 → Pass A → 인용 검증 → Pass B를 수행하는 공통 본체.
    """
    from app.services import stt_providers, verification
    from app.services.stt_filters import segments_to_transcript_text, split_segments_into_windows

    settings = get_settings()

    def _notify(step: int, message: str) -> None:
        if on_progress is None:
            return
        try:
            on_progress(step, message)
        except Exception as e:
            logger.debug("on_progress error ignored: %s", e)

    duration = _get_duration(audio_path)
    logger.info("[whisper] 오디오 길이: %.0f초", duration)

    # 2) STT 전사 (환청 필터 포함)
    _notify(2, "🎙️ 음성 인식 중... (2/3) — 시간이 걸릴 수 있습니다")
    segments, stt_stats = stt_providers.transcribe_audio(
        audio_path,
        on_progress=lambda msg: _notify(2, f"🎙️ {msg} (2/3)"),
    )
    if not segments:
        raise RuntimeError("전사 결과가 비어 있습니다 (발화 없음 또는 전부 환청 필터링됨)")

    transcript_text = segments_to_transcript_text(segments)
    logger.info(
        "[whisper] 전사 완료: %d 세그먼트 (provider=%s)",
        len(segments), stt_stats.get("provider"),
    )

    # 3) Pass A — 창 단위 추출
    _notify(3, "📝 오답노트 정리 중... (3/3)")
    logger.info("[whisper] Gemini Pass A 구조화 중...")
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=settings.GEMINI_API_KEY)

    windows = split_segments_into_windows(segments, WHISPER_PASS_A_WINDOW_SEC)
    logger.info("[whisper] Pass A 창 수: %d (창당 %ds)", len(windows), WHISPER_PASS_A_WINDOW_SEC)

    raw_feedbacks: List[Dict[str, Any]] = []
    all_keywords: List[str] = []
    for idx, window in enumerate(windows, start=1):
        window_result = _run_pass_a_for_window(client, types, settings.GEMINI_MODEL, window)
        raw_feedbacks.extend(fb for fb in window_result["feedbacks"] if isinstance(fb, dict))
        all_keywords.extend(str(k) for k in window_result["keywords"] if str(k).strip())
        _notify(3, f"📝 오답노트 정리 중... (3/3) — {idx}/{len(windows)} 구간")

    logger.info("[whisper] Pass A 추출 완료: %d개 피드백 후보 (창 %d개)", len(raw_feedbacks), len(windows))

    # 4) 코드 레벨 인용 검증 — 전사에 없는 quote 자동 폐기, sec 재계산
    pseudo_report = {"timestamps": raw_feedbacks}
    verified_a, verify_stats = verification.verify_report(
        pseudo_report, segments, threshold=settings.VERIFY_MATCH_THRESHOLD
    )
    verified_feedbacks = verified_a.get("timestamps") or []
    logger.info("[whisper] Pass A 검증 통계: %s", verify_stats)

    if not verified_feedbacks:
        raise RuntimeError("검증을 통과한 피드백이 없습니다 (전사에 실제 코치 발언이 없거나 추출 실패)")

    # 5) Pass B — 검증된 피드백만 보고 카드 종합 (별도 검증 불필요)
    category_counts: Dict[str, int] = {}
    for fb in verified_feedbacks:
        cat = str(fb.get("category") or "").strip()
        if cat:
            category_counts[cat] = category_counts.get(cat, 0) + 1

    # quote를 별도 줄로 명시적으로 분리 — 한 줄에 label/quote/problem/fix를
    # 섞어 쓰면 Pass B가 "quote만 그대로 복사"해야 할 때 그 줄 전체(부가
    # 설명까지)를 통째로 evidence에 복사해 검증 실패하는 사고가 실측됨
    # (2026-07-17, aYA3iILW2B0: card1~3 evidence에 "(문제: ... / 교정: ...)"
    # 까지 포함되어 전사 미매칭으로 3개 카드 전부 폐기).
    feedback_lines = []
    for fb in verified_feedbacks:
        cat = fb.get("category") or ""
        count_note = f" ({category_counts.get(cat)}회 중 하나)" if category_counts.get(cat, 0) > 1 else ""
        feedback_lines.append(
            f"- [{fb.get('sec')}초][{fb.get('type')}][{cat}{count_note}] {fb.get('label', '')}\n"
            f'  quote(이 줄 전체를 그대로 복사할 것): "{fb.get("quote", "")}"\n'
            f"  문제: {fb.get('problem', '') or '(없음)'} / 교정: {fb.get('fix', '') or '(없음)'}"
        )
    verified_feedbacks_text = "\n".join(feedback_lines)

    logger.info("[whisper] Gemini Pass B 종합 중...")
    pass_b_prompt = WHISPER_PASS_B_PROMPT.format(verified_feedbacks=verified_feedbacks_text)
    response = client.models.generate_content(
        model=settings.GEMINI_MODEL,
        contents=pass_b_prompt,
        config=types.GenerateContentConfig(
            temperature=0.0,
            max_output_tokens=8192,
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        ),
    )
    parsed_b = _parse_json(response.text or "")

    # Pass B의 card evidence는 검증된 피드백 목록에서만 뽑도록 프롬프트로
    # 강제했지만, 그래도 verify_report로 한 번 더 대조해 이중 안전장치를 둔다.
    pseudo_cards = {
        "card1_problem": parsed_b.get("card1_problem"),
        "card1_evidence": parsed_b.get("card1_evidence"),
        "card2_cueing": parsed_b.get("card2_cueing"),
        "card2_evidence": parsed_b.get("card2_evidence"),
        "card3_action": parsed_b.get("card3_action"),
        "card3_evidence": parsed_b.get("card3_evidence"),
    }
    verified_b, card_verify_stats = verification.verify_report(
        pseudo_cards, segments, threshold=settings.VERIFY_MATCH_THRESHOLD
    )
    logger.info("[whisper] Pass B 카드 검증 통계: %s", card_verify_stats)

    combined_verify_stats = {
        "match_threshold": settings.VERIFY_MATCH_THRESHOLD,
        "timestamps_total": verify_stats.get("timestamps_total", 0),
        "timestamps_verified": verify_stats.get("timestamps_verified", 0),
        "timestamps_dropped": verify_stats.get("timestamps_dropped", 0),
        "cards_dropped": card_verify_stats.get("cards_dropped", []),
        "pass_a_windows": len(windows),
    }

    # 창별 keywords를 등장 빈도순으로 중복 제거 — 여러 창에서 같은 단어가
    # 반복될수록(=레슨 전체에서 더 자주 언급될수록) 앞으로 오게 한다.
    keyword_counts: Dict[str, int] = {}
    for kw in all_keywords:
        keyword_counts[kw] = keyword_counts.get(kw, 0) + 1
    deduped_keywords = sorted(keyword_counts, key=lambda k: -keyword_counts[k])

    return {
        "card1_problem": str(verified_b.get("card1_problem") or "").strip() or None,
        "card2_cueing":  str(verified_b.get("card2_cueing")  or "").strip() or None,
        "card3_action":  str(verified_b.get("card3_action")  or "").strip() or None,
        "full_summary":  str(parsed_b.get("full_summary")  or "").strip() or None,
        "keywords":      _coerce_keywords(deduped_keywords),
        "lesson_type":   _coerce_lesson_type(parsed_b.get("lesson_type")),
        "steps":         _coerce_steps(parsed_b.get("steps")),
        "scenarios":     _coerce_scenarios(parsed_b.get("scenarios")),
        "timestamps":    _compact_timestamps(_coerce_timestamps(verified_feedbacks)),
        "gemini_model":  settings.GEMINI_MODEL,
        "transcript_text": transcript_text,
        # 09문서 1-6: quote 없는 AI 보조 설명 — verify_report 대상이 아님(의도적).
        "ai_context":    _coerce_ai_context(parsed_b.get("ai_context")),
        # 15문서 2-A: 인용 노출 여부 판단용 등급. match_score 평균/STT 필터
        # 통과율 둘 다 실제 품질과 상관관계가 없음을 골든셋 3건 사람 검토로
        # 실증(가장 필터 통과율이 높았던 영상이 오히려 정밀도가 가장 낮았음) —
        # 그래서 자동 판정 로직을 만들지 않고, whisper 경로는 항상 "low"로
        # 고정한다(인용 정밀도 실측 13~20%, 신뢰 노출 불가). stt_stats/
        # verification을 DB에 쌓아두는 이유는 향후 진짜 판정 신호를 찾기
        # 위한 원시 데이터 축적.
        "transcript_quality": "low",
        # 신규 메타 (기존 응답 shape에 additive — DB 저장은 라우터에서 선택)
        "stt_stats": stt_stats,
        "verification": combined_verify_stats,
    }
