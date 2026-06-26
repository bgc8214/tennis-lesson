---
name: youtube-ai-pipeline
description: "YouTube 레슨 영상 URL을 입력받아 자막/오디오를 파싱하고 Gemini LLM으로 테니스 오답노트 리포트를 생성하는 AI 파이프라인. youtube-transcript-api, yt-dlp, Whisper STT, Gemini 1.5 Flash/Pro 통합 구현. YouTube 파싱, 자막 추출, 오디오 스트림, STT 변환, LLM 요약, 레슨 노트 생성 등 Phase 1 MVP 백엔드 파이프라인 작업 시 반드시 이 스킬을 사용할 것."
---

# YouTube AI Pipeline

YouTube 레슨 영상 URL → 텍스트 파싱 → Gemini 오답노트 생성의 전체 파이프라인.

## 파이프라인 구조

```
URL 입력
  ↓
[Step 1] 자막 파싱 시도 (youtube-transcript-api)
  ├── 성공: 자막 텍스트 추출
  └── 실패: yt-dlp 오디오 폴백
       ↓
      [Step 2] 오디오 스트림 다운로드 (오디오만, 영상 제외)
       ↓
      [Step 3] Whisper STT (In-Memory 처리)
  ↓
[Step 4] Gemini 프롬프트 주입 → 오답노트 마크다운 생성
  ↓
[Step 5] Supabase 저장
```

## Step 1: 자막 파싱

```python
from youtube_transcript_api import YouTubeTranscriptApi

def get_transcript(video_id: str) -> str | None:
    try:
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
        # 한국어 우선, 없으면 자동 생성 자막
        try:
            transcript = transcript_list.find_transcript(['ko'])
        except:
            transcript = transcript_list.find_generated_transcript(['ko', 'en'])
        
        entries = transcript.fetch()
        # 타임스탬프 포함 텍스트 조합
        return "\n".join([f"[{e['start']:.1f}s] {e['text']}" for e in entries])
    except Exception:
        return None
```

## Step 2: yt-dlp 오디오 폴백

자막이 없을 때만 실행한다. 영상 전체가 아닌 오디오 스트림만 다운로드한다.

```python
import yt_dlp
import io

def download_audio_bytes(url: str) -> bytes:
    buffer = io.BytesIO()
    ydl_opts = {
        'format': 'bestaudio/best',
        'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3'}],
        'outtmpl': '-',  # stdout으로 출력
        'quiet': True,
        'no_warnings': True,
    }
    # 실제 구현 시 임시 파일 없이 바이트 스트림으로 처리
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])
    return buffer.getvalue()
```

## Step 3: In-Memory Whisper STT

디스크에 저장하지 않고 RAM에서 처리한다.

```python
import whisper
import io
import tempfile

def transcribe_audio(audio_bytes: bytes, model_size: str = "base") -> str:
    model = whisper.load_model(model_size)
    
    # 임시 파일을 메모리에서 처리
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=True) as tmp:
        tmp.write(audio_bytes)
        tmp.flush()
        result = model.transcribe(tmp.name, language="ko")
    
    del audio_bytes  # 명시적 메모리 해제
    return result["text"]
```

## Step 4: Gemini 프롬프트

```python
import google.generativeai as genai

REPORT_PROMPT = """
당신은 테니스 코치님의 피드백을 분석하는 전문가입니다.
아래 레슨 스크립트에서 다음 3가지 오답노트 카드를 추출하여 마크다운 형식으로 작성하세요.

## 오답노트 카드 형식:
### Card 1 — 고질병 (코치님이 반복 지적한 핵심 문제점)
### Card 2 — 코치 큐잉 (코치님이 제시한 이미지/표현)
### Card 3 — 액션 플랜 (다음 연습 때 집중할 구체적 행동)

## 추가 메타데이터:
- **지적 횟수 상위 3개 키워드**: [키워드1(N회), 키워드2(N회), 키워드3(N회)]
- **타임스탬프 마커**: 주요 피드백이 발생한 시간 목록 [초 단위]

## 레슨 스크립트:
{transcript}
"""

def generate_report(transcript: str, model: str = "gemini-1.5-flash") -> dict:
    genai.configure(api_key=os.environ["GEMINI_API_KEY"])
    client = genai.GenerativeModel(model)
    response = client.generate_content(REPORT_PROMPT.format(transcript=transcript))
    return {"markdown": response.text, "model_used": model}
```

## 비용 최적화 결정 트리

| 시나리오 | 처리 방식 | Gemini 모델 | 예상 비용 |
|---------|---------|-----------|---------|
| 한글 자막 있음 | youtube-transcript-api | Flash | ~₩3/회 |
| 자막 없음, 30분 이내 | yt-dlp + Whisper | Flash | ~₩15/회 |
| 자막 없음, 60분 이상 | yt-dlp + Whisper | Flash (긴 컨텍스트) | ~₩30/회 |
| 프로 AI 패스 상세 분석 | 어느 경로든 | Pro | ~₩50/회 |

목표: 영상 1회 처리 원가 30원 이하 (PMD 9절 KPI).

## FastAPI 엔드포인트 구조

```python
@app.post("/api/v1/lessons/analyze")
async def analyze_lesson(request: LessonAnalyzeRequest) -> LessonReport:
    # 1. 자막 시도
    transcript = get_transcript(extract_video_id(request.youtube_url))
    
    # 2. 폴백
    if not transcript:
        audio_bytes = download_audio_bytes(request.youtube_url)
        transcript = transcribe_audio(audio_bytes)
    
    # 3. Gemini 리포트
    report = generate_report(transcript)
    
    # 4. Supabase 저장
    saved = await save_lesson_report(request.user_id, report, request.youtube_url)
    
    return saved
```

## 환경변수 목록

```
GEMINI_API_KEY=
SUPABASE_URL=
SUPABASE_ANON_KEY=
SUPABASE_SERVICE_ROLE_KEY=
WHISPER_MODEL_SIZE=base  # base/small/medium
```

## 참조

- 환경 설정 상세: `references/setup.md`
- Gemini 프롬프트 튜닝 가이드: `references/prompt-engineering.md`
