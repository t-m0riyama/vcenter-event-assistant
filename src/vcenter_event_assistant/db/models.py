"""ORM models."""

import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from vcenter_event_assistant.db.base import Base


class VCenter(Base):
    __tablename__ = "vcenters"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    host: Mapped[str] = mapped_column(String(512))
    port: Mapped[int] = mapped_column(Integer, default=443)
    username: Mapped[str] = mapped_column(String(512))
    password: Mapped[str] = mapped_column(String(2048))
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now().astimezone())

    events: Mapped[list["EventRecord"]] = relationship(back_populates="vcenter")
    metric_samples: Mapped[list["MetricSample"]] = relationship(back_populates="vcenter")
    ingestion_states: Mapped[list["IngestionState"]] = relationship(back_populates="vcenter")


class EventRecord(Base):
    __tablename__ = "events"
    __table_args__ = (UniqueConstraint("vcenter_id", "vmware_key", name="uq_event_vcenter_vmware_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vcenter_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("vcenters.id", ondelete="CASCADE"))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    event_type: Mapped[str] = mapped_column(String(512), index=True)
    message: Mapped[str] = mapped_column(Text, default="")
    severity: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    user_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    entity_name: Mapped[str | None] = mapped_column(String(1024), nullable=True, index=True)
    entity_type: Mapped[str | None] = mapped_column(String(256), nullable=True)
    vmware_key: Mapped[int] = mapped_column(Integer, index=True)
    chain_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notable_score: Mapped[int] = mapped_column(Integer, default=0, index=True)
    notable_tags: Mapped[list | None] = mapped_column(JSON, nullable=True)
    user_comment: Mapped[str | None] = mapped_column(Text, nullable=True)

    vcenter: Mapped["VCenter"] = relationship(back_populates="events")


class EventScoreRule(Base):
    """Per-event-type additive adjustment to ``score_event`` base score (stored in ``events.notable_score``)."""

    __tablename__ = "event_score_rules"
    __table_args__ = (UniqueConstraint("event_type", name="uq_event_score_rules_event_type"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(512), nullable=False)
    score_delta: Mapped[int] = mapped_column(Integer, nullable=False)


class EventTypeGuide(Base):
    """イベント種別ごとの一般的な説明・原因・対処（運用者が登録）。"""

    __tablename__ = "event_type_guides"
    __table_args__ = (UniqueConstraint("event_type", name="uq_event_type_guides_event_type"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(512), nullable=False)
    general_meaning: Mapped[str | None] = mapped_column(Text, nullable=True)
    typical_causes: Mapped[str | None] = mapped_column(Text, nullable=True)
    remediation: Mapped[str | None] = mapped_column(Text, nullable=True)
    action_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class MetricSample(Base):
    __tablename__ = "metric_samples"
    __table_args__ = (
        UniqueConstraint(
            "vcenter_id",
            "sampled_at",
            "entity_moid",
            "metric_key",
            name="uq_metric_sample_point",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vcenter_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("vcenters.id", ondelete="CASCADE"))
    sampled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    entity_type: Mapped[str] = mapped_column(String(128), index=True)
    entity_moid: Mapped[str] = mapped_column(String(256), index=True)
    entity_name: Mapped[str] = mapped_column(String(1024), default="")
    metric_key: Mapped[str] = mapped_column(String(256), index=True)
    value: Mapped[float] = mapped_column(Float)

    vcenter: Mapped["VCenter"] = relationship(back_populates="metric_samples")


class IngestionState(Base):
    __tablename__ = "ingestion_state"
    __table_args__ = (UniqueConstraint("vcenter_id", "kind", name="uq_ingestion_vcenter_kind"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vcenter_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("vcenters.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(64), index=True)
    cursor_value: Mapped[str | None] = mapped_column(Text, nullable=True)

    vcenter: Mapped["VCenter"] = relationship(back_populates="ingestion_states")


class DigestRecord(Base):
    """バッチ生成した Markdown ダイジェスト（期間・種別ごとに 1 行）。同一期間の再実行は別行として蓄積可能。"""

    __tablename__ = "digest_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    kind: Mapped[str] = mapped_column(String(64), index=True)
    body_markdown: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), index=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    llm_model: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now().astimezone(),
    )
