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

CHUNK_SECONDS = 20       # 청크당 20초 — offset 자체가 타임스탬프
MAX_CHUNKS = 200         # 최대 ~67분
MAX_WORKERS = 10         # 병렬 Gemini 호출 수

# ─── 프롬프트 ─────────────────────────────────────────────────────────

CHUNK_PROMPT = (
    '당신은 테니스 레슨 전문 분석가입니다.\n'
    '아래는 여성 코치가 남성 수강생에게 1:1 테니스 레슨을 진행하는 오디오 클립입니다.\n\n'
    '등장인물:\n'
    '- 코치(여성): 지시·교정·시범·설명을 하는 쪽. 주로 짧고 단호한 말투.\n'
    '- 수강생(남성): 질문하거나 "네", "아" 등으로 반응하는 쪽.\n\n'
    '코치의 모든 발언을 유형별로 분류하여 JSON으로 출력하세요.\n\n'
    '{"feedbacks": ['
    '{"type": "교정|드릴|전술", "category": "포핸드", "label": "요약", "quote": "코치 발언 원문", "fix": "교정법 또는 드릴 내용"}'
    '], "keywords": ["단어1", "단어2"]}\n\n'
    '규칙:\n'
    'type 분류:\n'
    '  - "교정": 수강생의 잘못된 동작을 지적하거나 교정하는 발언 (예: "타점이 뒤야", "라켓 면 닫아")\n'
    '  - "드릴": 특정 연습 방법·순서를 지시하는 발언 (예: "하나 치고 두 개 치고 스트레이트로", "크로스 세 개 다음에 다운더라인")\n'
    '  - "전술": 경기 상황 판단·배치·전략을 설명하는 발언 (예: "짧은 공 오면 네트로 들어와", "서브 후 포지션")\n'
    'category: 포핸드/백핸드/발리/서브/로브/스텝/풋워크/기타 중 하나.\n'
    'label: 발언 내용 핵심 20자 이내.\n'
    'quote: 코치 발언 원문 그대로. 수강생 발화 혼입 금지.\n'
    'fix: 교정법 또는 드릴·전술 내용. 오디오에서 언급된 것만.\n'
    '테니스 용어 참고: 타점·팔로우스루·내전·라켓드롭·토스·발리·스플릿스텝·풋워크·크로스·다운더라인.\n'
    '중요: 코치의 명확한 발언이 들리지 않으면 feedbacks를 반드시 빈 배열 []로 반환할 것.\n'
    '추측하거나 공 소리·배경 소음만 있는 구간은 절대 feedbacks에 넣지 말 것.\n'
    'feedbacks는 최대 20개. 교정·드릴·전술 모두 포함. 순수 JSON만, 펜스 금지.'
)

MERGE_PROMPT_TEMPLATE = (
    '당신은 테니스 레슨 분석 전문가입니다.\n'
    '여성 코치가 남성 수강생에게 진행한 1:1 레슨을 10분씩 나눠 분석한 청크별 결과입니다.\n'
    '아래 형식의 JSON 하나만 출력하세요. timestamps 필드는 없음. 설명·주석 없이 JSON만.\n\n'
    '{chunk_results}\n\n'
    '{{"card1_problem":"50자이내","card2_cueing":"50자이내","card3_action":"60자이내",'
    '"keywords":["k1","k2","k3"],"lesson_type":["포핸드"],'
    '"steps":[],"scenarios":[]}}\n\n'
    '규칙:\n'
    '1) 모든 문자열 한국어. 자 이내 제한 엄수.\n'
    '2) steps: 코치가 알려준 기술 동작 순서 3~5개. 없으면 [].\n'
    '3) scenarios: 상황별 대처 1~3개. 없으면 [].\n'
    '4) timestamps는 출력하지 않음 — 별도 처리됨.\n'
    '5) 순수 JSON만. 펜스·설명 금지.'
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
        ts_type = str(item.get("type", "")).strip()
        if ts_type not in ("교정", "드릴", "전술"):
            ts_type = "교정"
        out.append({
            "sec": sec,
            "type": ts_type,
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

        # sec는 Gemini 추정 대신 offset으로 고정 (10초 청크이므로 오차 최대 10초)
        for fb in parsed.get("feedbacks", []):
            fb["sec"] = offset

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
        mins = offset // 60
        feedbacks = r.get("feedbacks", [])
        keywords = r.get("keywords", [])
        lines = [f"\n## {mins}분~{mins+10}분 구간"]
        if feedbacks:
            for fb in feedbacks:
                fb_type = fb.get("type", "교정")
                label = fb.get("label") or fb.get("problem", "")
                lines.append(f"- [{fb['sec']}초][{fb_type}] {label} / 발언: {fb.get('quote','')}")
                # timestamps 직접 수집
                raw_timestamps.append({
                    "sec": fb.get("sec", offset),  # _analyze_chunk에서 이미 offset으로 세팅됨
                    "type": fb_type,
                    "category": str(fb.get("category", "")).strip() or None,
                    "label": str(label).strip()[:20] or "피드백",
                    "quote": str(fb.get("quote", "")).strip()[:30] or None,
                    "fix": str(fb.get("fix", "")).strip()[:30] or None,
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
        "card1_problem":   str(parsed.get("card1_problem") or "").strip() or None,
        "card2_cueing":    str(parsed.get("card2_cueing")  or "").strip() or None,
        "card3_action":    str(parsed.get("card3_action")  or "").strip() or None,
        "full_summary":    str(parsed.get("full_summary")  or "").strip() or None,
        "keywords":        _coerce_keywords(parsed.get("keywords")),
        "lesson_type":     _coerce_lesson_type(parsed.get("lesson_type")),
        "steps":           _coerce_steps(parsed.get("steps")),
        "scenarios":       _coerce_scenarios(parsed.get("scenarios")),
        "timestamps":      _coerce_timestamps(parsed.get("timestamps")),
        "gemini_model":    settings.GEMINI_MODEL,
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
        "timestamps":    _coerce_timestamps(parsed.get("timestamps")),
        "gemini_model":  settings.GEMINI_MODEL,
        "transcript_text": transcript_text,
    }
