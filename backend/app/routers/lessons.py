"""레슨 리소스 라우터 (POST/GET/DELETE).

엔드포인트:
  - POST   /api/v1/lessons/analyze
  - GET    /api/v1/lessons
  - GET    /api/v1/lessons/{lesson_id}
  - DELETE /api/v1/lessons/{lesson_id}
"""

from __future__ import annotations

import logging
from datetime import date as date_cls
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Path,
    Query,
    Response,
    status,
)

from app.auth import get_current_user_id
from app.config import get_settings
from app.database import get_supabase_client
from app.models.lesson import (
    LessonAnalyzeRequest,
)
from app.services import gemini_service, stt_service, youtube_service
from app.services import court_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/lessons", tags=["lessons"])


# ─────────────────────────────────────────────────────────────────────
# 직렬화 헬퍼
# ─────────────────────────────────────────────────────────────────────


def _err(code: str, message: str, *, details: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    body: Dict[str, Any] = {"code": code, "message": message}
    if details is not None:
        body["details"] = details
    return {"error": body}


def _serialize_lesson_summary(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "lesson_id": row.get("id"),
        "youtube_url": row.get("youtube_url"),
        "youtube_video_id": row.get("youtube_video_id"),
        "title": row.get("title"),
        "lesson_date": row.get("lesson_date"),
        "thumbnail_url": row.get("thumbnail_url"),
        "duration_sec": row.get("duration_sec"),
        "lesson_type": row.get("lesson_type") or [],
        "processing_status": row.get("processing_status") or "PENDING",
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def _serialize_report(row: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not row:
        return None
    return {
        "card1_problem": row.get("card1_problem"),
        "card2_cueing": row.get("card2_cueing"),
        "card3_action": row.get("card3_action"),
        "keywords": row.get("keywords") or [],
        "steps": row.get("steps") or [],
        "scenarios": row.get("scenarios") or [],
        "timestamps": row.get("timestamps") or [],
        "ai_context": row.get("ai_context") or [],
        # 15문서 2-A: null이면 프론트가 구버전 레슨(마이그레이션 이전 생성)으로
        # 취급 — quote 노출 여부 판단 시 null도 "신뢰 불가"로 처리해야 함.
        "transcript_quality": row.get("transcript_quality"),
        "full_summary": row.get("full_summary"),
        "transcript_source": row.get("transcript_source") or "UNKNOWN",
        "gemini_model": row.get("gemini_model"),
        "error_message": row.get("error_message"),
        "completed_at": row.get("completed_at"),
        "progress_step": row.get("progress_step") or 0,
        "progress_message": row.get("progress_message"),
        # Phase 2: Court Tactics
        "court_tactics": row.get("court_tactics"),
        "court_analysis_status": row.get("court_analysis_status"),
    }


# ─────────────────────────────────────────────────────────────────────
# 진행 상태 헬퍼
# ─────────────────────────────────────────────────────────────────────


def _update_progress(sb, lesson_id: str, step: int, message: str, now_fn) -> None:
    """PROCESSING 중 진행 단계/메시지를 lesson_reports에 기록."""
    try:
        sb.table("lesson_reports").update(
            {
                "progress_step": step,
                "progress_message": message,
                "updated_at": now_fn(),
            }
        ).eq("lesson_id", lesson_id).execute()
    except Exception as e:
        logger.warning("[%s] progress update failed: %s", lesson_id, e)


# ─────────────────────────────────────────────────────────────────────
# 백그라운드 분석 작업
# ─────────────────────────────────────────────────────────────────────


def _run_analysis_pipeline(lesson_id: str, youtube_url: str, analyze_court: bool = False) -> None:
    """비동기 BackgroundTask로 실행되는 전체 파이프라인.

    상태 전이:
      PENDING → PROCESSING → (DONE | FAILED)
    """
    sb = get_supabase_client()
    settings = get_settings()
    now = lambda: datetime.now(timezone.utc).isoformat()

    # 1) lesson 상태 PROCESSING으로
    try:
        sb.table("lessons").update(
            {"updated_at": now()}
        ).eq("id", lesson_id).execute()
        sb.table("lesson_reports").update(
            {"processing_status": "PROCESSING", "updated_at": now()}
        ).eq("lesson_id", lesson_id).execute()
    except Exception as e:
        logger.warning("[%s] failed to mark PROCESSING: %s", lesson_id, e)

    transcript_source = "UNKNOWN"

    try:
        engine = settings.TRANSCRIPT_ENGINE
        if engine in ("whisper", "whisper-verified"):
            # 기본 경로: STT 전사 → Gemini 구조화 → 코드 레벨 인용 검증 (할루시네이션 최소)
            _update_progress(sb, lesson_id, 0, "🎵 오디오 다운로드 중... (1/3)", now)
            logger.info("[%s] TRANSCRIPT_ENGINE=%s (whisper 검증 경로) 사용", lesson_id, engine)
            report = gemini_service.generate_lesson_report_whisper(
                youtube_url,
                on_progress=lambda step, msg: _update_progress(sb, lesson_id, step, msg, now),
            )
            transcript_source = "WHISPER_STT"
            if report.get("verification"):
                logger.info("[%s] 인용 검증 통계: %s", lesson_id, report["verification"])
        elif engine == "gemini-youtube":
            _update_progress(sb, lesson_id, 0, "🎬 YouTube 영상을 Gemini로 불러오는 중... (1/3)", now)
            logger.info("[%s] TRANSCRIPT_ENGINE=gemini-youtube 경로 사용", lesson_id)
            report = gemini_service.generate_lesson_report_youtube_url(
                youtube_url,
                on_progress=lambda step, msg: _update_progress(sb, lesson_id, step, msg, now),
            )
        else:
            _update_progress(sb, lesson_id, 0, "🎵 오디오 다운로드 중... (1/3)", now)
            report = gemini_service.generate_lesson_report(
                youtube_url,
                on_progress=lambda step, msg: _update_progress(sb, lesson_id, step, msg, now),
            )
    except Exception as e:
        logger.error("[%s] gemini failed: %s", lesson_id, e)
        try:
            sb.table("lesson_reports").update(
                {
                    "processing_status": "FAILED",
                    "transcript_source": transcript_source,
                    "error_message": f"Gemini 분석 실패: {e}",
                    "progress_message": None,
                    "progress_step": 0,
                    "updated_at": now(),
                    "completed_at": now(),
                }
            ).eq("lesson_id", lesson_id).execute()
        except Exception as e2:
            logger.error("[%s] failed to write FAILED state: %s", lesson_id, e2)
        return

    # 5) 정상 완료 저장
    try:
        sb.table("lesson_reports").update(
            {
                "card1_problem": report.get("card1_problem"),
                "card2_cueing": report.get("card2_cueing"),
                "card3_action": report.get("card3_action"),
                "full_summary": report.get("full_summary"),
                "keywords": report.get("keywords") or [],
                "steps": report.get("steps") or [],
                "scenarios": report.get("scenarios") or [],
                "timestamps": report.get("timestamps") or [],
                "ai_context": report.get("ai_context") or [],
                "transcript_quality": report.get("transcript_quality"),
                "stt_stats": report.get("stt_stats"),
                "verification": report.get("verification"),
                "transcript_source": transcript_source,
                "gemini_model": report.get("gemini_model") or settings.GEMINI_MODEL,
                "processing_status": "DONE",
                "error_message": None,
                "progress_message": None,
                "progress_step": 4,
                "updated_at": now(),
                "completed_at": now(),
            }
        ).eq("lesson_id", lesson_id).execute()

        # lesson 메타가 비어있다면 보강 (제목 자동 채움) + 카테고리 업데이트
        try:
            patch: Dict[str, Any] = {"updated_at": now()}
            if report.get("video_title"):
                # gemini-youtube 경로: Gemini가 영상에서 직접 읽은 제목 사용.
                # duration_sec/thumbnail_url은 레슨 생성 시 이미 yt-dlp로 조회했으므로
                # (실패했더라도 그때 이미 폴백 썸네일이 저장됨) 여기서 재조회하지 않는다.
                patch["title"] = report["video_title"]
            else:
                video_id = youtube_service.extract_video_id(youtube_url)
                meta = youtube_service.get_video_metadata(video_id)
                if meta.get("title"):
                    patch["title"] = meta["title"]
                if meta.get("duration_sec"):
                    patch["duration_sec"] = meta["duration_sec"]
                if meta.get("thumbnail_url"):
                    patch["thumbnail_url"] = meta["thumbnail_url"]
            # lesson_type은 메타데이터 조회 성공 여부와 무관하게 갱신
            patch["lesson_type"] = report.get("lesson_type") or []
            sb.table("lessons").update(patch).eq("id", lesson_id).execute()
        except Exception as e:
            logger.info("[%s] metadata fill skipped: %s", lesson_id, e)
            # 메타 보강은 실패해도 lesson_type만이라도 별도로 저장 시도
            try:
                sb.table("lessons").update(
                    {
                        "lesson_type": report.get("lesson_type") or [],
                        "updated_at": now(),
                    }
                ).eq("id", lesson_id).execute()
            except Exception as e2:
                logger.warning("[%s] lesson_type update failed: %s", lesson_id, e2)

    except Exception as e:
        logger.error("[%s] failed to save DONE state: %s", lesson_id, e)
        return

    # 크레딧 차감 (로그인 유저만)
    from app.auth import ANONYMOUS_USER_ID
    lesson_row = sb.table("lessons").select("user_id").eq("id", lesson_id).limit(1).execute()
    lesson_user_id = (lesson_row.data or [{}])[0].get("user_id")
    if lesson_user_id and lesson_user_id != ANONYMOUS_USER_ID:
        try:
            sb.rpc("decrement_credits", {"p_user_id": lesson_user_id, "p_lesson_id": lesson_id}).execute()
        except Exception as e:
            logger.warning("[%s] credit deduction failed: %s", lesson_id, e)

    # Phase 2: Transcript + Court Tactics 병렬 실행
    from concurrent.futures import ThreadPoolExecutor

    def _run_court() -> None:
        if not (analyze_court and get_settings().COURT_ANALYSIS_ENABLED and report.get("timestamps")):
            return
        try:
            sb.table("lesson_reports").update(
                {"court_analysis_status": "PROCESSING", "updated_at": now()}
            ).eq("lesson_id", lesson_id).execute()

            court_tactics = court_service.analyze_court_tactics(
                youtube_url,
                report["timestamps"],
                on_progress=lambda step, msg: _update_progress(sb, lesson_id, step, msg, now),
            )
            sb.table("lesson_reports").update(
                {"court_tactics": court_tactics, "court_analysis_status": "DONE", "updated_at": now()}
            ).eq("lesson_id", lesson_id).execute()
            logger.info("[%s] court analysis done: %d tactics", lesson_id, len(court_tactics))
        except Exception as e:
            logger.warning("[%s] court analysis failed: %s", lesson_id, e)
            try:
                sb.table("lesson_reports").update(
                    {"court_analysis_status": "FAILED", "updated_at": now()}
                ).eq("lesson_id", lesson_id).execute()
            except Exception:
                pass

    with ThreadPoolExecutor(max_workers=1) as executor:
        futures = [executor.submit(_run_court)]
        for f in futures:
            try:
                f.result()
            except Exception as e:
                logger.warning("[%s] post-processing error: %s", lesson_id, e)


# ─────────────────────────────────────────────────────────────────────
# Background court analysis task (separate trigger)
# ─────────────────────────────────────────────────────────────────────


def _run_court_analysis(lesson_id: str, youtube_url: str) -> None:
    """Background task for standalone court analysis trigger."""
    sb = get_supabase_client()
    now = lambda: datetime.now(timezone.utc).isoformat()

    try:
        sb.table("lesson_reports").update(
            {"court_analysis_status": "PROCESSING", "updated_at": now()}
        ).eq("lesson_id", lesson_id).execute()
    except Exception as e:
        logger.warning("[%s] court: failed to mark PROCESSING: %s", lesson_id, e)

    try:
        # Fetch timestamps from existing report
        report_res = (
            sb.table("lesson_reports")
            .select("timestamps")
            .eq("lesson_id", lesson_id)
            .limit(1)
            .execute()
        )
        timestamps = []
        if report_res.data:
            timestamps = report_res.data[0].get("timestamps") or []

        if not timestamps:
            logger.info("[%s] court: no timestamps, marking DONE with empty", lesson_id)
            sb.table("lesson_reports").update(
                {"court_tactics": [], "court_analysis_status": "DONE", "updated_at": now()}
            ).eq("lesson_id", lesson_id).execute()
            return

        court_tactics = court_service.analyze_court_tactics(youtube_url, timestamps)
        sb.table("lesson_reports").update(
            {"court_tactics": court_tactics, "court_analysis_status": "DONE", "updated_at": now()}
        ).eq("lesson_id", lesson_id).execute()
        logger.info("[%s] court analysis done: %d tactics", lesson_id, len(court_tactics))

    except Exception as e:
        logger.error("[%s] court analysis failed: %s", lesson_id, e)
        try:
            sb.table("lesson_reports").update(
                {"court_analysis_status": "FAILED", "updated_at": now()}
            ).eq("lesson_id", lesson_id).execute()
        except Exception as e2:
            logger.warning("[%s] court status update failed: %s", lesson_id, e2)


# ─────────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────────


@router.post("/analyze", status_code=status.HTTP_202_ACCEPTED)
def analyze_lesson(
    payload: LessonAnalyzeRequest,
    background_tasks: BackgroundTasks,
    user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    """YouTube URL을 받아 분석 작업을 큐잉한다. 즉시 202 + lesson_id 반환."""
    settings = get_settings()
    sb = get_supabase_client()

    youtube_url = str(payload.youtube_url)

    # 0) 크레딧 체크 (로그인 유저만)
    from app.auth import ANONYMOUS_USER_ID
    if user_id != ANONYMOUS_USER_ID:
        try:
            credit_res = sb.table("user_credits").select("credits").eq("user_id", user_id).limit(1).execute()
            if not credit_res.data:
                # 크레딧 행이 없으면 생성 (3크레딧)
                sb.table("user_credits").insert({"user_id": user_id, "credits": 3}).execute()
                credits = 3
            else:
                credits = credit_res.data[0]["credits"]
            if credits <= 0:
                raise HTTPException(
                    status_code=status.HTTP_402_PAYMENT_REQUIRED,
                    detail=_err("INSUFFICIENT_CREDITS", "크레딧이 부족합니다. 충전 후 이용해주세요."),
                )
        except HTTPException:
            raise
        except Exception as e:
            logger.warning("credit check failed (skipping): %s", e)

    # 1) video_id 추출 검증
    try:
        video_id = youtube_service.extract_video_id(youtube_url)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_err("INVALID_YOUTUBE_URL", "YouTube URL을 해석할 수 없습니다.",
                       details={"youtube_url": youtube_url, "reason": str(e)}),
        )

    # 2) 메타데이터 (실패해도 진행, 폴백 썸네일)
    title: Optional[str] = payload.title
    duration_sec: Optional[int] = None
    thumbnail_url: Optional[str] = f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"
    upload_date: Optional[str] = None
    try:
        meta = youtube_service.get_video_metadata(video_id)
        if not title:
            title = meta.get("title")
        duration_sec = meta.get("duration_sec")
        thumbnail_url = meta.get("thumbnail_url") or thumbnail_url
        upload_date = meta.get("upload_date")
    except Exception as e:
        logger.info("metadata lookup skipped: %s", e)

    # 3) 영상 길이 가드
    if (
        duration_sec is not None
        and settings.YTDLP_MAX_DURATION_SEC > 0
        and duration_sec > settings.YTDLP_MAX_DURATION_SEC
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=_err(
                "VIDEO_TOO_LONG",
                "영상 길이가 한도를 초과합니다.",
                details={"duration_sec": duration_sec, "limit": settings.YTDLP_MAX_DURATION_SEC},
            ),
        )

    # 4) 동일 user + video_id 중복 차단
    try:
        existing = (
            sb.table("lessons")
            .select("id, youtube_url, created_at, lesson_reports(processing_status)")
            .eq("user_id", user_id)
            .eq("youtube_video_id", video_id)
            .limit(1)
            .execute()
        )
        if existing.data:
            existing_row = existing.data[0]
            existing_id = existing_row["id"]
            existing_report = existing_row.get("lesson_reports")
            if isinstance(existing_report, list):
                existing_report = existing_report[0] if existing_report else None
            existing_status = (existing_report or {}).get("processing_status") or "PENDING"

            if existing_status == "FAILED":
                now = lambda: datetime.now(timezone.utc).isoformat()
                try:
                    sb.table("lesson_reports").update(
                        {
                            "processing_status": "PENDING",
                            "error_message": None,
                            "progress_step": 0,
                            "progress_message": None,
                            "updated_at": now(),
                            "completed_at": None,
                        }
                    ).eq("lesson_id", existing_id).execute()
                except Exception as e:
                    logger.warning("[%s] failed to reset FAILED report: %s", existing_id, e)

                background_tasks.add_task(
                    _run_analysis_pipeline,
                    existing_id,
                    existing_row.get("youtube_url") or youtube_url,
                    payload.analyze_court,
                )
                return {
                    "data": {
                        "lesson_id": existing_id,
                        "processing_status": "PENDING",
                        "youtube_video_id": video_id,
                        "created_at": existing_row.get("created_at"),
                    }
                }

            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=_err(
                    "LESSON_ALREADY_EXISTS",
                    "이미 분석된 레슨이 있습니다.",
                    details={
                        "existing_lesson_id": existing_id,
                        "youtube_video_id": video_id,
                    },
                ),
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("duplicate check failed (skipping): %s", e)

    # 5) lessons + lesson_reports 레코드 생성
    lesson_date_str = (
        payload.lesson_date.isoformat()
        if isinstance(payload.lesson_date, date_cls)
        else upload_date  # 사용자가 지정 안 했으면 YouTube 업로드 날짜 사용
    )
    lesson_insert = {
        "user_id": user_id,
        "youtube_url": youtube_url,
        "youtube_video_id": video_id,
        "title": title,
        "lesson_date": lesson_date_str,
        "thumbnail_url": thumbnail_url,
        "duration_sec": duration_sec,
    }

    try:
        ins = sb.table("lessons").insert(lesson_insert).execute()
    except Exception as e:
        logger.exception("lesson insert failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=_err("UPSTREAM_ERROR", "Supabase 저장에 실패했습니다.", details={"reason": str(e)}),
        )

    if not ins.data:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=_err("INTERNAL_ERROR", "레슨 생성 응답이 비어 있습니다."),
        )

    lesson_row = ins.data[0]
    lesson_id = lesson_row["id"]

    # report shell 레코드 (PENDING)
    try:
        sb.table("lesson_reports").insert(
            {
                "lesson_id": lesson_id,
                "processing_status": "PENDING",
                "transcript_source": "UNKNOWN",
                "keywords": [],
                "timestamps": [],
            }
        ).execute()
    except Exception as e:
        logger.warning("report shell insert failed: %s", e)

    # 6) 백그라운드 분석 트리거
    background_tasks.add_task(_run_analysis_pipeline, lesson_id, youtube_url, payload.analyze_court)

    return {
        "data": {
            "lesson_id": lesson_id,
            "processing_status": "PENDING",
            "youtube_video_id": video_id,
            "created_at": lesson_row.get("created_at"),
        }
    }


@router.get("")
def list_lessons(
    limit: int = Query(default=20, ge=1, le=50),
    cursor: Optional[str] = Query(default=None),
    status_filter: Optional[str] = Query(default=None, alias="status"),
    lesson_type: Optional[str] = Query(
        default=None,
        description="레슨 카테고리 필터 (예: 포핸드, 백핸드, 발리, 서브, 로브, 스텝, 풋워크, 게임레슨, 드롭샷, 어프로치)",
    ),
    user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    """내 레슨 목록 (created_at desc, cursor 기반 페이지네이션).

    lesson_type 파라미터가 주어지면 해당 카테고리를 포함한 레슨만 반환.
    """
    sb = get_supabase_client()

    try:
        q = (
            sb.table("lessons")
            .select(
                "id, youtube_url, youtube_video_id, title, lesson_date, "
                "thumbnail_url, duration_sec, lesson_type, created_at, updated_at, "
                "lesson_reports(processing_status)"
            )
            .eq("user_id", user_id)
            .eq("is_hidden", False)
            .order("created_at", desc=True)
            .limit(limit + 1)  # has_more 판정용
        )
        if cursor:
            q = q.lt("created_at", cursor)
        if lesson_type:
            # PostgreSQL 배열 contains: lesson_type @> ARRAY['포핸드']
            q = q.contains("lesson_type", [lesson_type])
        res = q.execute()
    except Exception as e:
        logger.exception("list_lessons query failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=_err("UPSTREAM_ERROR", "Supabase 조회에 실패했습니다.", details={"reason": str(e)}),
        )

    rows: List[Dict[str, Any]] = list(res.data or [])

    # 상태 필터 (Python-side; 단순함을 위해)
    def _row_status(r: Dict[str, Any]) -> str:
        rep = r.get("lesson_reports")
        if isinstance(rep, list) and rep:
            rep = rep[0]
        if isinstance(rep, dict):
            return rep.get("processing_status") or "PENDING"
        return "PENDING"

    if status_filter:
        rows = [r for r in rows if _row_status(r) == status_filter]

    has_more = len(rows) > limit
    if has_more:
        rows = rows[:limit]

    next_cursor: Optional[str] = None
    if has_more and rows:
        next_cursor = rows[-1].get("created_at")

    data = []
    for r in rows:
        summary = _serialize_lesson_summary(r)
        summary["processing_status"] = _row_status(r)
        data.append(summary)

    return {
        "data": data,
        "pagination": {
            "limit": limit,
            "next_cursor": next_cursor,
            "has_more": has_more,
        },
    }


@router.get("/{lesson_id}")
def get_lesson(
    lesson_id: str = Path(..., description="레슨 UUID"),
    user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    """레슨 상세 + 리포트."""
    sb = get_supabase_client()

    try:
        res = (
            sb.table("lessons")
            .select(
                "id, user_id, youtube_url, youtube_video_id, title, lesson_date, "
                "thumbnail_url, duration_sec, lesson_type, created_at, updated_at, "
                "lesson_reports(*)"
            )
            .eq("id", lesson_id)
            .limit(1)
            .execute()
        )
    except Exception as e:
        logger.exception("get_lesson query failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=_err("UPSTREAM_ERROR", "Supabase 조회에 실패했습니다.", details={"reason": str(e)}),
        )

    if not res.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_err(
                "LESSON_NOT_FOUND",
                "해당 레슨을 찾을 수 없습니다.",
                details={"lesson_id": lesson_id},
            ),
        )

    row = res.data[0]
    if row.get("is_hidden"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_err("LESSON_NOT_FOUND", "해당 레슨을 찾을 수 없습니다.", details={"lesson_id": lesson_id}),
        )
    if row.get("user_id") != user_id:
        # 본인 소유 아님 → 404로 노출 (정보 누설 최소화)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_err(
                "LESSON_NOT_FOUND",
                "해당 레슨을 찾을 수 없습니다.",
                details={"lesson_id": lesson_id},
            ),
        )

    rep = row.get("lesson_reports")
    if isinstance(rep, list):
        rep = rep[0] if rep else None

    proc_status = (rep or {}).get("processing_status") or "PENDING"

    summary = _serialize_lesson_summary(row)
    summary["processing_status"] = proc_status

    if proc_status in ("DONE", "FAILED"):
        summary["report"] = _serialize_report(rep)
    elif proc_status in ("PENDING", "PROCESSING") and rep:
        # PROCESSING 중에는 progress 정보만 반환
        summary["report"] = {
            "progress_step": (rep or {}).get("progress_step") or 0,
            "progress_message": (rep or {}).get("progress_message"),
            # 나머지 카드 필드는 None
            "card1_problem": None,
            "card2_cueing": None,
            "card3_action": None,
            "keywords": [],
            "timestamps": [],
            "full_summary": None,
            "error_message": None,
            "transcript_source": None,
            "gemini_model": None,
            "completed_at": None,
            # Phase 2: Court Tactics
            "court_tactics": None,
            "court_analysis_status": None,
        }
    else:
        summary["report"] = None

    return {"data": summary}


@router.post("/{lesson_id}/retry", status_code=status.HTTP_202_ACCEPTED)
def retry_lesson(
    lesson_id: str = Path(..., description="레슨 UUID"),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    """실패한 레슨 분석을 재시도한다."""
    sb = get_supabase_client()

    try:
        res = (
            sb.table("lessons")
            .select("id, user_id, youtube_url, lesson_reports(processing_status)")
            .eq("id", lesson_id)
            .limit(1)
            .execute()
        )
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY,
                            detail=_err("UPSTREAM_ERROR", "조회 실패", details={"reason": str(e)}))

    if not res.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=_err("LESSON_NOT_FOUND", "해당 레슨을 찾을 수 없습니다."))

    row = res.data[0]
    if row.get("user_id") != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=_err("LESSON_NOT_FOUND", "해당 레슨을 찾을 수 없습니다."))

    rep = row.get("lesson_reports")
    if isinstance(rep, list):
        rep = rep[0] if rep else {}
    if (rep or {}).get("processing_status") not in ("FAILED", "DONE"):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail=_err("LESSON_NOT_FAILED", "실패 상태인 레슨만 재시도할 수 있습니다."))

    now = lambda: datetime.now(timezone.utc).isoformat()
    sb.table("lesson_reports").update({
        "processing_status": "PENDING",
        "error_message": None,
        "progress_step": 0,
        "progress_message": None,
        "updated_at": now(),
    }).eq("lesson_id", lesson_id).execute()

    background_tasks.add_task(_run_analysis_pipeline, lesson_id, row["youtube_url"])

    return {"data": {"lesson_id": lesson_id, "processing_status": "PENDING"}}


@router.delete("/{lesson_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_lesson(
    lesson_id: str = Path(..., description="레슨 UUID"),
    user_id: str = Depends(get_current_user_id),
) -> Response:
    """레슨 + 리포트 영구 삭제 (lesson_reports는 ON DELETE CASCADE)."""
    sb = get_supabase_client()

    # 소유권 확인
    try:
        res = (
            sb.table("lessons")
            .select("id, user_id")
            .eq("id", lesson_id)
            .limit(1)
            .execute()
        )
    except Exception as e:
        logger.exception("delete pre-check failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=_err("UPSTREAM_ERROR", "Supabase 조회에 실패했습니다.", details={"reason": str(e)}),
        )

    if not res.data or res.data[0].get("user_id") != user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_err(
                "LESSON_NOT_FOUND",
                "해당 레슨을 찾을 수 없습니다.",
                details={"lesson_id": lesson_id},
            ),
        )

    try:
        sb.table("lessons").delete().eq("id", lesson_id).execute()
    except Exception as e:
        logger.exception("lesson delete failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=_err("UPSTREAM_ERROR", "Supabase 삭제에 실패했습니다.", details={"reason": str(e)}),
        )

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{lesson_id}/court-analysis", status_code=status.HTTP_202_ACCEPTED)
def trigger_court_analysis(
    lesson_id: str = Path(..., description="레슨 UUID"),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    """코트 전술 분석을 별도로 트리거한다.

    이미 Phase 1이 DONE인 레슨에 대해서만 실행 가능.
    """
    settings = get_settings()

    # Feature flag check
    if not settings.COURT_ANALYSIS_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=_err("FEATURE_DISABLED", "코트 분석 기능이 비활성화되어 있습니다."),
        )

    sb = get_supabase_client()

    # Fetch lesson + report
    try:
        res = (
            sb.table("lessons")
            .select(
                "id, user_id, youtube_url, "
                "lesson_reports(processing_status, court_analysis_status)"
            )
            .eq("id", lesson_id)
            .limit(1)
            .execute()
        )
    except Exception as e:
        logger.exception("court-analysis pre-check failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=_err("UPSTREAM_ERROR", "Supabase 조회에 실패했습니다.", details={"reason": str(e)}),
        )

    # 404: not found or not owned
    if not res.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_err(
                "LESSON_NOT_FOUND",
                "해당 레슨을 찾을 수 없습니다.",
                details={"lesson_id": lesson_id},
            ),
        )

    row = res.data[0]
    if row.get("user_id") != user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_err(
                "LESSON_NOT_FOUND",
                "해당 레슨을 찾을 수 없습니다.",
                details={"lesson_id": lesson_id},
            ),
        )

    # Extract report info
    rep = row.get("lesson_reports")
    if isinstance(rep, list):
        rep = rep[0] if rep else None

    if not rep:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_err(
                "LESSON_NOT_READY",
                "레슨 분석이 완료된 후에만 코트 분석을 실행할 수 있습니다.",
                details={"lesson_id": lesson_id, "current_status": "PENDING"},
            ),
        )

    proc_status = rep.get("processing_status") or "PENDING"
    court_status = rep.get("court_analysis_status")

    # 400: Phase 1 not done
    if proc_status != "DONE":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_err(
                "LESSON_NOT_READY",
                "레슨 분석이 완료된 후에만 코트 분석을 실행할 수 있습니다.",
                details={"lesson_id": lesson_id, "current_status": proc_status},
            ),
        )

    # 409: already processing
    if court_status == "PROCESSING":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_err(
                "COURT_ANALYSIS_IN_PROGRESS",
                "코트 분석이 이미 진행 중입니다.",
                details={"lesson_id": lesson_id, "court_analysis_status": "PROCESSING"},
            ),
        )

    youtube_url = row.get("youtube_url", "")

    # Trigger background task
    background_tasks.add_task(_run_court_analysis, lesson_id, youtube_url)

    return {
        "data": {
            "lesson_id": lesson_id,
            "court_analysis_status": "PROCESSING",
            "message": "코트 분석이 시작되었습니다.",
        }
    }
