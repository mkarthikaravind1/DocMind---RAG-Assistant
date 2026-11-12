# routes/eval_routes.py
# Admin-only views of the answer quality scores (see evaluation.py).
from datetime import timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

import evaluation
from database import get_db
from dependencies import require_role
from guardrails import check_pii_in_response
from models import Evaluation, QueryLog, User

router = APIRouter()


def _utc_iso(ts):
    if ts is None:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.isoformat()


def _round(value):
    return None if value is None else round(float(value), 3)


def eval_fields(row: Evaluation | None) -> dict:
    """The score fields shown next to a query (all None when it was not evaluated)."""
    return {
        "eval_status":      row.status if row else None,
        "faithfulness":     _round(row.faithfulness) if row else None,
        "answer_relevancy": _round(row.answer_relevancy) if row else None,
    }


@router.get("/stats")
def evaluation_stats(
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    counts = dict(db.query(Evaluation.status, func.count(Evaluation.id)).group_by(Evaluation.status).all())
    scored = counts.get(evaluation.SCORED, 0)
    not_answered = counts.get(evaluation.NOT_ANSWERED, 0)

    avg_faith, avg_relevancy = (
        db.query(func.avg(Evaluation.faithfulness), func.avg(Evaluation.answer_relevancy))
        .filter(Evaluation.status == evaluation.SCORED)
        .one()
    )
    low = (
        db.query(func.count(Evaluation.id))
        .filter(Evaluation.status == evaluation.SCORED, Evaluation.faithfulness < evaluation.LOW_SCORE)
        .scalar()
        or 0
    )
    asked = scored + not_answered
    return {
        "evaluated":            scored,
        "avg_faithfulness":     _round(avg_faith),
        "avg_answer_relevancy": _round(avg_relevancy),
        "low_faithfulness":     low,
        "not_answered":         not_answered,
        "not_answered_rate":    round(not_answered / asked, 3) if asked else 0.0,
        "failed":               counts.get(evaluation.FAILED, 0),
        "low_score_threshold":  evaluation.LOW_SCORE,
        "low_relevancy_threshold": evaluation.LOW_RELEVANCY,
        "sample_rate":          evaluation.SAMPLE_RATE,
        "judge_model":          evaluation.judge_model_name(),
    }


@router.get("")
def recent_evaluations(
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    """The latest evaluations, newest first. Scores only: no answer or document text."""
    rows = (
        db.query(Evaluation, QueryLog)
        .outerjoin(QueryLog, QueryLog.id == Evaluation.query_log_id)
        .order_by(Evaluation.id.desc())
        .limit(100)
        .all()
    )
    return [
        {
            "id":                   ev.id,
            "query_log_id":         ev.query_log_id,
            # The question is the user's own text; redact any PII typed into it
            "question":             check_pii_in_response(str(log.question))[0] if log else None,
            "user_role":            log.user_role if log else None,
            **eval_fields(ev),
            "statements_total":     ev.statements_total,
            "statements_supported": ev.statements_supported,
            "judge_model":          ev.judge_model,
            "eval_time":            ev.eval_time,
            "timestamp":            _utc_iso(ev.created_at),
        }
        for ev, log in rows
    ]
