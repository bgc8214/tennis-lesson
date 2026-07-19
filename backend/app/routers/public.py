"""인증 없는 공개 라우터 — 09문서 #5 코치 확인 링크.

엔드포인트:
  - GET  /api/v1/public/lessons/{share_token}
  - POST /api/v1/public/lessons/{share_token}/coach-comment

share_token은 lessons.share_token(uuid, unique index)으로 발급되며,
소유자만 /lessons/{lesson_id}/share-link 로 발급받을 수 있다. 이 라우터는
그 토큰을 아는 누구나(코치) 조회/코멘트 작성이 가능하도록 인증을 요구하지
않는다 — service role 클라이언트로 RLS를 우회해 직접 처리한다.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Path, status

from app.database import get_supabase_client
from app.models.report import CoachCommentRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/public/lessons", tags=["public"])


def _err(code: str, message: str) -> Dict[str, Any]:
    return {"error": {"code": code, "message": message}}


def _get_lesson_by_share_token(sb, share_token: str) -> Dict[str, Any]:
    try:
        res = (
            sb.table("lessons")
            .select(
                "id, title, lesson_date, youtube_video_id, duration_sec, "
                "lesson_reports(card1_problem, card2_cueing, card3_action, "
                "keywords, timestamps, transcript_quality, ai_context)"
            )
            .eq("share_token", share_token)
            .limit(1)
            .execute()
        )
    except Exception as e:
        logger.exception("public lesson lookup failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=_err("UPSTREAM_ERROR", "조회에 실패했습니다."),
        ) from e

    if not res.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_err("LESSON_NOT_FOUND", "링크가 유효하지 않습니다."),
        )
    return res.data[0]


@router.get("/{share_token}")
def get_public_lesson(
    share_token: str = Path(..., description="공유 링크 토큰"),
) -> Dict[str, Any]:
    """코치가 공유 링크로 여는 읽기전용 리포트 뷰."""
    sb = get_supabase_client()
    row = _get_lesson_by_share_token(sb, share_token)

    rep = row.get("lesson_reports")
    if isinstance(rep, list):
        rep = rep[0] if rep else None

    return {
        "data": {
            "lesson_id": row.get("id"),
            "title": row.get("title"),
            "lesson_date": row.get("lesson_date"),
            "youtube_video_id": row.get("youtube_video_id"),
            "duration_sec": row.get("duration_sec"),
            "report": {
                "card1_problem": (rep or {}).get("card1_problem"),
                "card2_cueing": (rep or {}).get("card2_cueing"),
                "card3_action": (rep or {}).get("card3_action"),
                "keywords": (rep or {}).get("keywords") or [],
                "timestamps": (rep or {}).get("timestamps") or [],
                "transcript_quality": (rep or {}).get("transcript_quality"),
                "ai_context": (rep or {}).get("ai_context") or [],
            }
            if rep
            else None,
        }
    }


@router.post("/{share_token}/coach-comment", status_code=status.HTTP_201_CREATED)
def create_coach_comment(
    payload: CoachCommentRequest,
    share_token: str = Path(..., description="공유 링크 토큰"),
) -> Dict[str, Any]:
    """코치가 남기는 검증(confirmed/needs_fix) + 한 줄 코멘트 (09문서 #5)."""
    sb = get_supabase_client()
    row = _get_lesson_by_share_token(sb, share_token)
    lesson_id = row["id"]

    try:
        ins = (
            sb.table("coach_comments")
            .insert(
                {
                    "lesson_id": lesson_id,
                    "verdict": payload.verdict,
                    "comment": (payload.comment or "").strip() or None,
                }
            )
            .execute()
        )
    except Exception as e:
        logger.exception("coach comment insert failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=_err("UPSTREAM_ERROR", "코멘트 저장에 실패했습니다."),
        ) from e

    return {"data": ins.data[0] if ins.data else {"lesson_id": lesson_id}}
