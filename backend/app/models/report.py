"""레슨 리포트 도메인 Pydantic 모델."""

from datetime import datetime
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field

TranscriptSource = Literal["YOUTUBE_CAPTION", "WHISPER_STT", "UNKNOWN"]

ReactionValue = Literal["up", "down"]

CourtPosition = Literal[
    "net_left", "net_center", "net_right",
    "service_line_left", "service_line_center", "service_line_right",
    "baseline_left", "baseline_center", "baseline_right",
    "unknown",
]

CourtAnalysisStatus = Literal["PROCESSING", "DONE", "FAILED"]


class LessonTimestamp(BaseModel):
    """타임스탬프 마커 (영상 내 핵심 피드백 시점)."""

    sec: int = Field(ge=0)
    label: str
    quote: Optional[str] = None


class CourtTactic(BaseModel):
    """코트 위치 기반 전술 마커."""

    sec: int = Field(ge=0)
    position: CourtPosition
    position_x: float = Field(ge=0.0, le=1.0)
    position_y: float = Field(ge=0.0, le=1.0)
    category: Optional[str] = None
    tactic: str
    label: str
    quote: Optional[str] = None


class LessonReport(BaseModel):
    """Gemini가 생성한 3단 오답노트 + 메타."""

    card1_problem: Optional[str] = None
    card2_cueing: Optional[str] = None
    card3_action: Optional[str] = None
    keywords: List[str] = []
    timestamps: List[LessonTimestamp] = []
    full_summary: Optional[str] = None
    transcript_source: TranscriptSource = "UNKNOWN"
    gemini_model: Optional[str] = None
    error_message: Optional[str] = None
    completed_at: Optional[datetime] = None
    court_tactics: Optional[List[CourtTactic]] = None
    court_analysis_status: Optional[CourtAnalysisStatus] = None
    # 13문서 대체카드: 카드/타임스탬프별 👍/👎, 텍스트 한 줄 수요 테스트
    reactions: Dict[str, ReactionValue] = Field(default_factory=dict)
    quick_note: Optional[str] = None


class ReactionUpdateRequest(BaseModel):
    """PUT /lessons/{lesson_id}/reactions 요청 본문."""

    target_key: str = Field(min_length=1, max_length=64)
    value: Optional[ReactionValue] = None  # None이면 반응 취소(토글 해제)


class QuickNoteUpdateRequest(BaseModel):
    """PATCH /lessons/{lesson_id}/quick-note 요청 본문."""

    quick_note: Optional[str] = Field(default=None, max_length=500)


class CoachCommentRequest(BaseModel):
    """POST /public/lessons/{share_token}/coach-comment 요청 본문."""

    verdict: Literal["confirmed", "needs_fix"]
    comment: Optional[str] = Field(default=None, max_length=300)
