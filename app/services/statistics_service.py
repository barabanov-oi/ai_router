"""Service functions aggregating metrics for the admin dashboard."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, List

from sqlalchemy import func

from app.models import ChatMessage, User


# NOTE(agents): collect_overview gathers key indicators displayed on the dashboard.
def collect_overview() -> Dict[str, int]:
    """Return aggregated statistics such as user counts and token usage."""

    total_users = User.query.count()
    active_users = User.query.filter_by(is_active=True).count()
    messages_total = ChatMessage.query.count()
    tokens_spent = (
        ChatMessage.query.with_entities(func.sum(ChatMessage.total_tokens)).scalar() or 0
    )
    recent_activity = User.query.filter(User.last_seen >= datetime.utcnow() - timedelta(days=1)).count()
    return {
        "total_users": total_users,
        "active_users": active_users,
        "messages_total": messages_total,
        "tokens_spent": int(tokens_spent),
        "recent_activity": recent_activity,
    }


# NOTE(agents): recent_messages is used to show the latest prompts/responses for debugging.
def recent_messages(limit: int = 20) -> List[ChatMessage]:
    """Return most recent chat messages limited by ``limit``."""

    return ChatMessage.query.order_by(ChatMessage.created_at.desc()).limit(limit).all()
