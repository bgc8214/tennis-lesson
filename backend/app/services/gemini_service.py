"""google-genai SDK 기반 오답노트 리포트 생성 서비스.

전략: 전체 오디오 다운로드 → 10분 청크로 분할 → 청크별 병렬 분석 → 최종 합산
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Dict, List, Optional

from app.config import get_settings

logger = logging.getLogger(__name__)

CHUNK_SECONDS = 600      # 청크당 10분
MAX_CHUNKS = 8           # 최대 80분
MAX_WORKERS = 4          # 병렬 Gemini 호출 수

# ─── 프롬프트 ─────────────────────────────────────────────────────────

CHUNK_PROMPT = (
    '테니스 레슨 오디오 클립입니다. 코치 피드백을 분석해서 JSON만 출력하세요.\n\n'
    '{"feedbacks": ['
    '{"sec": 정수, "category": "포핸드", "problem": "문제 설명", "quote": "코치 발언 원문", "fix": "교정 방법"}'
    '], "keywords": ["단어1", "단어2"]}\n\n'
    '규칙: 한국어. sec은 클립 시작 기준 초.\n'
    'category는 포핸드/백핸드/발리/서브/로브/스텝/풋워크/기타 중 하나.\n'
    'problem: 어떤 문제인지 구체적으로 (예: 스윙을 끝까지 크게 안 함).\n'
    'quote: 코치가 실제로 한 말 그대로 (예: 풀 스윙이 없다, 끝까지 쭉 뻗어야지).\n'
    'fix: 어떻게 고쳐야 하는지 구체적 교정법 (예: 임팩트 후 어깨까지 라켓 끝까지 올리기).\n'
    'feedbacks는 주요 피드백 장면 최대 15개. 순수 JSON만, 펜스 금지.'
)

MERGE_PROMPT_TEMPLATE = (
    '당신은 테니스 레슨 분석 전문가입니다.\n\n'
    '아래는 테니스 레슨 영상을 10분씩 나눠 분석한 청크별 결과입니다.\n'
    '이를 종합하여 최종 오답노트를 만들어주세요. JSON만 출력하세요.\n\n'
    '{chunk_results}\n\n'
    '{{"card1_problem": "코치가 레슨 전체에서 반복적으로 지적한 핵심 문제(고질병) 1~2문장", '
    '"card2_cueing": "코치가 제시한 핵심 이미지/큐잉/표현 1~2문장", '
    '"card3_action": "다음 연습 때 집중할 구체 행동 1~2문장", '
    '"full_summary": "레슨 전체 흐름 요약 3~5문단", '
    '"keywords": ["키워드1", "키워드2", "키워드3"], '
    '"lesson_type": ["포핸드"], '
    '"steps": ["① 첫 번째 실행 단계", "② 두 번째 실행 단계", "③ 세 번째 실행 단계"], '
    '"scenarios": [{{"condition": "볼이 높게 왔을 때", "action": "앞에서 파워로 마무리"}}, {{"condition": "볼이 낮게 왔을 때", "action": "드롭 후 드라이브로 넘겨준다"}}], '
    '"timestamps": [{{"sec": 0, "category": "포핸드", "label": "문제 요약", "quote": "코치 발언 원문", "fix": "교정 방법"}}]}}\n\n'
    '규칙:\n'
    '1) 모든 문자열은 한국어.\n'
    '2) keywords는 정확히 3개.\n'
    '3) timestamps는 주요 피드백 장면 15~20개. sec은 영상 전체 기준 정수(초).\n'
    '   - category: 포핸드/백핸드/발리/서브/로브/스텝/풋워크/기타 중 하나\n'
    '   - label: 어떤 문제인지 구체적으로 (예: 스윙을 끝까지 크게 안 함)\n'
    '   - quote: 코치가 실제로 한 말 그대로\n'
    '   - fix: 어떻게 고쳐야 하는지 구체적 교정법\n'
    '4) lesson_type은 다음 값들 중 해당하는 것을 모두 포함한 배열: '
    '["포핸드", "백핸드", "발리", "서브", "로브", "스텝", "풋워크", "게임레슨", "드롭샷", "어프로치"]. '
    '레슨 내용/피드백 키워드를 근거로 1~3개를 선택. 분류 불가하면 빈 배열 [].\n'
    '5) steps: 코치가 알려준 기술 동작을 ①②③... 순서로 3~6개 배열. 없으면 빈 배열 [].\n'
    '6) scenarios: 코치가 언급한 상황별 대처법. condition(상황 조건)과 action(대응 행동) 쌍으로 1~4개. 없으면 빈 배열 [].\n'
    '7) 순수 JSON만 출력. 마크다운 펜스 금지.'
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
        out.append({
            "sec": sec,
            "category": str(item.get("category", "")).strip() or None,
            "label": str(item.get("label", "")).strip() or "주요 지적",
            "quote": str(item.get("quote", "")).strip() or None,
            "fix": str(item.get("fix", "")).strip() or None,
        })
    return out


# ─── 오디오 처리 ──────────────────────────────────────────────────────

def _download_full_audio(youtube_url: str, tmp_dir: str) -> str:
    """전체 오디오를 mp3로 다운로드."""
    import yt_dlp
    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": os.path.join(tmp_dir, "full.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "64"}],
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([youtube_url])

    for name in os.listdir(tmp_dir):
        if name.lower().endswith(".mp3"):
            return os.path.join(tmp_dir, name)
    raise RuntimeError("오디오 다운로드 실패")


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

def _analyze_chunk(client: Any, chunk: Dict, types: Any) -> Optional[Dict]:
    """단일 청크를 Gemini로 분석."""
    path = chunk["path"]
    offset = chunk["offset_sec"]

    try:
        uploaded = client.files.upload(file=path, config={"mime_type": "audio/mpeg"})
    except Exception as e:
        logger.warning("청크 업로드 실패 (offset=%ds): %s", offset, e)
        return None

    try:
        response = client.models.generate_content(
            model=get_settings().GEMINI_MODEL,
            contents=[
                types.Part(file_data=types.FileData(file_uri=uploaded.uri, mime_type="audio/mpeg")),
                types.Part(text=CHUNK_PROMPT),
            ],
            config=types.GenerateContentConfig(
                temperature=0.3,
                max_output_tokens=16000,
                thinking_config=types.ThinkingConfig(thinking_budget=0),
            ),
        )
        raw = response.text or ""
        logger.info("청크 응답 (offset=%ds, 길이=%d): %s", offset, len(raw), raw[:200])
        parsed = _parse_json(raw)

        # 타임스탬프에 오프셋 더하기
        for fb in parsed.get("feedbacks", []):
            fb["sec"] = fb.get("sec", 0) + offset

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


def _merge_chunks(client: Any, chunk_results: List[Dict], types: Any) -> dict:
    """청크 결과들을 Gemini로 최종 합산."""
    summary_lines = []
    for r in chunk_results:
        offset = r.get("offset_sec", 0)
        mins = offset // 60
        feedbacks = r.get("feedbacks", [])
        keywords = r.get("keywords", [])
        lines = [f"\n## {mins}분~{mins+10}분 구간"]
        if feedbacks:
            for fb in feedbacks:
                lines.append(f"- [{fb['sec']}초] {fb.get('problem','')} / 큐잉: {fb.get('cueing','')} / 발언: {fb.get('quote','')}")
        else:
            lines.append("- 피드백 없음")
        if keywords:
            lines.append(f"- 반복 키워드: {', '.join(keywords)}")
        summary_lines.append("\n".join(lines))

    chunk_text = "\n".join(summary_lines)
    prompt = MERGE_PROMPT_TEMPLATE.format(chunk_results=chunk_text)

    response = client.models.generate_content(
        model=get_settings().GEMINI_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.4,
            max_output_tokens=8192,
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        ),
    )
    return _parse_json(response.text or "")


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
                "card2_cueing": feedbacks[0].get("cueing") if feedbacks else None,
                "card3_action": None,
                "full_summary": None,
                "keywords": r.get("keywords", []),
                "lesson_type": r.get("lesson_type", []),
                "steps": r.get("steps", []),
                "scenarios": r.get("scenarios", []),
                "timestamps": [{"sec": fb["sec"], "category": fb.get("category",""), "label": fb.get("problem",""), "quote": fb.get("quote",""), "fix": fb.get("fix","")} for fb in feedbacks],
            }
        else:
            # 합산 단계 진입 알림 (3/3)
            _notify(3, "📝 오답노트 정리 중... (3/3)")
            logger.info("청크 결과 합산 중...")
            parsed = _merge_chunks(client, chunk_results, types)

    return {
        "card1_problem": str(parsed.get("card1_problem") or "").strip() or None,
        "card2_cueing":  str(parsed.get("card2_cueing")  or "").strip() or None,
        "card3_action":  str(parsed.get("card3_action")  or "").strip() or None,
        "full_summary":  str(parsed.get("full_summary")  or "").strip() or None,
        "keywords":      _coerce_keywords(parsed.get("keywords")),
        "lesson_type":   _coerce_lesson_type(parsed.get("lesson_type")),
        "steps":         _coerce_steps(parsed.get("steps")),
        "scenarios":     _coerce_scenarios(parsed.get("scenarios")),
        "timestamps":    _coerce_timestamps(parsed.get("timestamps")),
        "gemini_model":  settings.GEMINI_MODEL,
    }
