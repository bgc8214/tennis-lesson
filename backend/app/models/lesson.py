"""레슨 도메인 Pydantic 모델."""

from datetime import date, datetime
from typing import List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.report import LessonReport

ProcessingStatus = Literal["PENDING", "PROCESSING", "DONE", "FAILED"]

# 17문서 U-1: 레슨 소스 유형. youtube(링크 분석) | upload(영상 파일 직접 업로드)
SourceType = Literal["youtube", "upload"]

# Gemini가 분류 가능한 레슨 카테고리 화이트리스트.
# (gemini_service.ALLOWED_LESSON_TYPES와 동기화 유지할 것)
LessonType = Literal[
    "포핸드", "백핸드", "발리", "서브", "로브",
    "스텝", "풋워크", "게임레슨", "드롭샷", "어프로치",
]


class LessonAnalyzeRequest(BaseModel):
    """POST /api/v1/lessons/analyze 요청 본문."""

    # str로 받아 라우터에서 extract_video_id로 검증 → 모든 포맷 오류를 400 INVALID_YOUTUBE_URL로 통일
    youtube_url: str = Field(min_length=1, max_length=500)
    title: Optional[str] = Field(default=None, max_length=200)
    lesson_date: Optional[date] = None
    analyze_court: bool = Field(default=False, description="코트 전술 분석 실행 여부")


class LessonAnalyzeResponse(BaseModel):
    """POST /api/v1/lessons/analyze 응답 (202 Accepted)."""

    lesson_id: UUID
    processing_status: ProcessingStatus
    youtube_video_id: str
    created_at: datetime


class LessonAnalyzeUploadResponse(BaseModel):
    """POST /api/v1/lessons/analyze-upload 응답 (202 Accepted).

    17문서 U-1: 업로드 레슨은 youtube_video_id가 없으므로 별도 응답 모델.
    """

    lesson_id: UUID
    processing_status: ProcessingStatus
    created_at: datetime


class LessonSummary(BaseModel):
    """목록 조회용 가벼운 메타."""

    lesson_id: UUID
    # 17문서 U-1: 업로드 레슨은 youtube_url이 없으므로 Optional로 완화.
    youtube_url: Optional[str] = None
    youtube_video_id: Optional[str] = None
    source_type: SourceType = "youtube"
    file_hash: Optional[str] = None
    title: Optional[str] = None
    lesson_date: Optional[date] = None
    thumbnail_url: Optional[str] = None
    duration_sec: Optional[int] = None
    lesson_type: List[str] = Field(default_factory=list)
    processing_status: ProcessingStatus
    created_at: datetime
    updated_at: datetime


class LessonDetail(LessonSummary):
    """상세 + 리포트."""

    report: Optional[LessonReport] = None


# ── 공통 응답 래퍼 ──────────────────────────────────────────────────


class PaginationMeta(BaseModel):
    limit: int
    next_cursor: Optional[str] = None
    has_more: bool = False


class ApiSuccess(BaseModel):
    """일관된 단일 객체 응답 래퍼: { "data": ... }."""

    data: dict


class ApiError(BaseModel):
    code: str
    message: str
    details: Optional[dict] = None
    request_id: Optional[str] = None


class ApiErrorResponse(BaseModel):
    error: ApiError
