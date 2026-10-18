from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    csrf_token: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ResetToken(Base):
    __tablename__ = "reset_tokens"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LoginAttempt(Base):
    __tablename__ = "login_attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), index=True)
    success: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Connection(Base):
    __tablename__ = "connections"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    provider: Mapped[str] = mapped_column(String(32))  # fyers | groww
    label: Mapped[str] = mapped_column(String(128), default="")
    # public identifiers (safe to show)
    app_id: Mapped[str] = mapped_column(String(255), default="")   # fyers app id / groww api key
    # encrypted JSON: {app_secret?, totp_secret?, access_token?}
    credentials: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(24), default="never_authed")
    # never_authed | connected | needs_auth | error
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reauth_time: Mapped[str] = mapped_column(String(5), default="07:30")
    last_error: Mapped[str] = mapped_column(Text, default="")
    last_reauth_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LlmConnection(Base):
    __tablename__ = "llm_connections"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    provider: Mapped[str] = mapped_column(String(32))  # openai|anthropic|gemini|groq|openrouter|custom
    label: Mapped[str] = mapped_column(String(128), default="")
    api_key_encrypted: Mapped[str] = mapped_column(Text, default="")
    base_url: Mapped[str] = mapped_column(String(512), default="")
    model: Mapped[str] = mapped_column(String(128), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# ---------------------------------------------------------------------------
# S4 — Igris agent: shared memory, rules, trading, chat
# ---------------------------------------------------------------------------

class Rule(Base):
    __tablename__ = "rules"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    capital: Mapped[float] = mapped_column(default=100000.0)
    risk_per_trade_pct: Mapped[float] = mapped_column(default=1.0)
    max_open_positions: Mapped[int] = mapped_column(Integer, default=3)
    daily_loss_limit_pct: Mapped[float] = mapped_column(default=2.0)
    max_daily_trades: Mapped[int] = mapped_column(Integer, default=10)
    mode: Mapped[str] = mapped_column(String(16), default="paper")  # paper | live
    autonomy: Mapped[str] = mapped_column(String(16), default="paper")
    # paper | live_approve | live_auto
    instruments_allowed: Mapped[str] = mapped_column(Text, default='["equity_intraday","equity_delivery","futures","options"]')
    strategy_id: Mapped[str] = mapped_column(String(32), default="IGRIS-1")
    kill_switch: Mapped[bool] = mapped_column(Boolean, default=False)
    notify_on_long: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WatchlistItem(Base):
    __tablename__ = "watchlist"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    symbol: Mapped[str] = mapped_column(String(64), index=True)  # NSE symbol e.g. RELIANCE
    notes: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(16), default="user")  # user | agent
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Signal(Base):
    __tablename__ = "signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    symbol: Mapped[str] = mapped_column(String(64), index=True)
    direction: Mapped[str] = mapped_column(String(8), default="long")  # long | short
    catalyst: Mapped[str] = mapped_column(Text, default="")
    score: Mapped[float] = mapped_column(default=0.5)
    source: Mapped[str] = mapped_column(String(16), default="agent")  # user | agent
    created_by: Mapped[str] = mapped_column(String(32), default="user")  # user | scout | news | macro | analyst
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ResearchNote(Base):
    __tablename__ = "research_notes"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text, default="")
    sentiment: Mapped[float | None] = mapped_column(nullable=True)  # -1..1
    entities: Mapped[str] = mapped_column(Text, default="")  # JSON list of symbols/sectors
    sources: Mapped[str] = mapped_column(Text, default="")  # JSON list of urls
    created_by: Mapped[str] = mapped_column(String(32), default="assistant")
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MemoryEdge(Base):
    __tablename__ = "memory_edges"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    from_kind: Mapped[str] = mapped_column(String(24))  # note | signal | trade | entity
    from_id: Mapped[str] = mapped_column(String(64))
    to_kind: Mapped[str] = mapped_column(String(24))
    to_id: Mapped[str] = mapped_column(String(64))
    rel: Mapped[str] = mapped_column(String(24))  # mentions | supports | supersedes | reacts_to
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Proposal(Base):
    __tablename__ = "proposals"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    symbol: Mapped[str] = mapped_column(String(64), index=True)
    side: Mapped[str] = mapped_column(String(4))  # BUY | SELL
    instrument: Mapped[str] = mapped_column(String(24))  # equity_intraday|equity_delivery|futures|options
    expiry: Mapped[str] = mapped_column(String(16), default="")  # YYYY-MM-DD for F&O
    strike: Mapped[str] = mapped_column(String(32), default="")
    entry: Mapped[float] = mapped_column(default=0.0)
    stop: Mapped[float] = mapped_column(default=0.0)
    target: Mapped[float] = mapped_column(default=0.0)
    qty: Mapped[float] = mapped_column(default=0.0)
    rationale: Mapped[str] = mapped_column(Text, default="")
    confidence: Mapped[float] = mapped_column(default=0.5)
    source: Mapped[str] = mapped_column(String(16), default="agent")  # user | agent
    status: Mapped[str] = mapped_column(String(16), default="proposed")
    # proposed | vetoed | pending_approval | approved | filled | rejected | expired
    veto_reason: Mapped[str] = mapped_column(Text, default="")
    mode: Mapped[str] = mapped_column(String(8), default="paper")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Trade(Base):
    __tablename__ = "trades"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    proposal_id: Mapped[str] = mapped_column(String(64), default="")
    symbol: Mapped[str] = mapped_column(String(64), index=True)
    side: Mapped[str] = mapped_column(String(4))
    instrument: Mapped[str] = mapped_column(String(24))
    expiry: Mapped[str] = mapped_column(String(16), default="")
    strike: Mapped[str] = mapped_column(String(32), default="")
    mode: Mapped[str] = mapped_column(String(8), default="paper")  # paper | live
    qty: Mapped[float] = mapped_column(default=0.0)
    entry_px: Mapped[float] = mapped_column(default=0.0)
    stop_px: Mapped[float] = mapped_column(default=0.0)
    target_px: Mapped[float] = mapped_column(default=0.0)
    exit_px: Mapped[float | None] = mapped_column(nullable=True)
    slippage: Mapped[float] = mapped_column(default=0.0)
    costs: Mapped[float] = mapped_column(default=0.0)
    pnl: Mapped[float | None] = mapped_column(nullable=True)  # net after costs when closed
    status: Mapped[str] = mapped_column(String(12), default="open")  # open|pending_approval|closed|rejected
    exit_reason: Mapped[str] = mapped_column(String(32), default="")  # stop|target|eod|manual|kill
    broker_order_id: Mapped[str] = mapped_column(String(64), default="")
    strategy_id: Mapped[str] = mapped_column(String(32), default="IGRIS-1")
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Lesson(Base):
    __tablename__ = "lessons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    body: Mapped[str] = mapped_column(Text)
    metric: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    actor: Mapped[str] = mapped_column(String(32))  # user | assistant | system | risk | executor
    action: Mapped[str] = mapped_column(String(64))
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(32))  # long_trade | veto | kill | reauth | job | system
    title: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text, default="")
    read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CronJob(Base):
    __tablename__ = "cron_jobs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(128))
    tool_name: Mapped[str] = mapped_column(String(64))
    args: Mapped[str] = mapped_column(Text, default="")  # JSON
    interval_minutes: Mapped[int] = mapped_column(Integer, default=60)
    market_hours_only: Mapped[bool] = mapped_column(Boolean, default=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_result: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(255), default="New chat")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), index=True)
    role: Mapped[str] = mapped_column(String(16))  # user | assistant | tool | system
    content: Mapped[str] = mapped_column(Text, default="")
    tool_json: Mapped[str] = mapped_column(Text, default="")  # tool calls/results transcript
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AgentSettings(Base):
    __tablename__ = "agent_settings"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    llm_connection_id: Mapped[str] = mapped_column(String(64), default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ConfirmToken(Base):
    __tablename__ = "confirm_tokens"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # token
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    tool_name: Mapped[str] = mapped_column(String(64))
    args: Mapped[str] = mapped_column(Text, default="")  # JSON
    summary: Mapped[str] = mapped_column(Text, default="")
    used: Mapped[bool] = mapped_column(Boolean, default=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
