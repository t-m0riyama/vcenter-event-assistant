"""ORM models."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from vcenter_event_assistant.db.base import Base
from vcenter_event_assistant.db.encrypted_string import EncryptedString


class VCenter(Base):
    __tablename__ = "vcenters"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    host: Mapped[str] = mapped_column(String(512))
    protocol: Mapped[str] = mapped_column(String(16), default="https")
    port: Mapped[int] = mapped_column(Integer, default=443)
    username: Mapped[str] = mapped_column(String(512))
    password: Mapped[str] = mapped_column(EncryptedString(2048))
    verify_ssl: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    events: Mapped[list["EventRecord"]] = relationship(
        back_populates="vcenter",
        passive_deletes=True,
    )
    metric_samples: Mapped[list["MetricSample"]] = relationship(
        back_populates="vcenter",
        passive_deletes=True,
    )
    ingestion_states: Mapped[list["IngestionState"]] = relationship(
        back_populates="vcenter",
        passive_deletes=True,
    )


class EventRecord(Base):
    __tablename__ = "events"
    __table_args__ = (
        UniqueConstraint(
            "vcenter_id",
            "collector_id",
            "vmware_key",
            name="uq_event_collector_vmware_key",
        ),
        Index("ix_events_vcenter_id_occurred_at", "vcenter_id", "occurred_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    collector_id: Mapped[str] = mapped_column(
        String(64), default="builtin.vcenter.events", index=True
    )
    vcenter_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("vcenters.id", ondelete="CASCADE")
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    event_type: Mapped[str] = mapped_column(String(512), index=True)
    message: Mapped[str] = mapped_column(Text, default="")
    severity: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    user_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    entity_name: Mapped[str | None] = mapped_column(
        String(1024), nullable=True, index=True
    )
    entity_type: Mapped[str | None] = mapped_column(String(256), nullable=True)
    vmware_key: Mapped[int] = mapped_column(Integer, index=True)
    chain_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notable_score: Mapped[int] = mapped_column(Integer, default=0, index=True)
    notable_tags: Mapped[list | None] = mapped_column(JSON, nullable=True)
    user_comment: Mapped[str | None] = mapped_column(Text, nullable=True)

    vcenter: Mapped["VCenter"] = relationship(back_populates="events")


class LogRecord(Base):
    __tablename__ = "log_records"
    __table_args__ = (
        UniqueConstraint(
            "vcenter_id",
            "collector_id",
            "source_id",
            "log_kind",
            "file_generation",
            "byte_offset",
            name="uq_log_source_position",
        ),
        Index("ix_log_vcenter_effective_time", "vcenter_id", "effective_at", "id"),
        Index("ix_log_effective_time_id", "effective_at", "id"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vcenter_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("vcenters.id", ondelete="CASCADE")
    )
    collector_id: Mapped[str] = mapped_column(String(64))
    source_id: Mapped[str] = mapped_column(String(128), index=True)
    host: Mapped[str] = mapped_column(String(512))
    log_kind: Mapped[str] = mapped_column(String(64), index=True)
    file_generation: Mapped[str] = mapped_column(String(128))
    byte_offset: Mapped[int] = mapped_column(BigInteger)
    occurred_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    severity: Mapped[str | None] = mapped_column(String(64), nullable=True)
    message: Mapped[str] = mapped_column(Text)


class EventScoreRule(Base):
    """Per-event-type additive adjustment to ``score_event`` base score (stored in ``events.notable_score``)."""

    __tablename__ = "event_score_rules"
    __table_args__ = (
        UniqueConstraint("event_type", name="uq_event_score_rules_event_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(512), nullable=False)
    score_delta: Mapped[int] = mapped_column(Integer, nullable=False)


class EventTypeGuide(Base):
    """イベント種別ごとの一般的な説明・原因・対処（運用者が登録）。"""

    __tablename__ = "event_type_guides"
    __table_args__ = (
        UniqueConstraint("event_type", name="uq_event_type_guides_event_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(512), nullable=False)
    general_meaning: Mapped[str | None] = mapped_column(Text, nullable=True)
    typical_causes: Mapped[str | None] = mapped_column(Text, nullable=True)
    remediation: Mapped[str | None] = mapped_column(Text, nullable=True)
    action_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )


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
        Index(
            "ix_metric_samples_vcenter_entity_metric_sampled",
            "vcenter_id",
            "entity_moid",
            "metric_key",
            "sampled_at",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    collector_id: Mapped[str] = mapped_column(
        String(64), default="builtin.vcenter.host_quickstats", index=True
    )
    vcenter_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("vcenters.id", ondelete="CASCADE")
    )
    sampled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    entity_type: Mapped[str] = mapped_column(String(128), index=True)
    entity_moid: Mapped[str] = mapped_column(String(256), index=True)
    entity_name: Mapped[str] = mapped_column(String(1024), default="")
    metric_key: Mapped[str] = mapped_column(String(256), index=True)
    value: Mapped[float] = mapped_column(Float)

    vcenter: Mapped["VCenter"] = relationship(back_populates="metric_samples")


class IngestionState(Base):
    __tablename__ = "ingestion_state"
    __table_args__ = (
        UniqueConstraint("vcenter_id", "kind", name="uq_ingestion_vcenter_kind"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vcenter_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("vcenters.id", ondelete="CASCADE")
    )
    kind: Mapped[str] = mapped_column(String(64), index=True)
    cursor_value: Mapped[str | None] = mapped_column(Text, nullable=True)

    vcenter: Mapped["VCenter"] = relationship(back_populates="ingestion_states")


class CollectorRunState(Base):
    """Latest execution state for one collector and vCenter."""

    __tablename__ = "collector_run_states"
    __table_args__ = (
        UniqueConstraint(
            "vcenter_id", "collector_id", name="uq_collector_run_vcenter_plugin"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vcenter_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("vcenters.id", ondelete="CASCADE")
    )
    collector_id: Mapped[str] = mapped_column(String(64), index=True)
    collector_version: Mapped[str] = mapped_column(String(64), default="")
    status: Mapped[str] = mapped_column(String(16), index=True)
    last_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_success_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_failure_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    events_inserted: Mapped[int] = mapped_column(Integer, default=0)
    metrics_inserted: Mapped[int] = mapped_column(Integer, default=0)
    logs_inserted: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class CollectorPluginSetting(Base):
    """Operator-managed collector configuration edited through the API.

    NULL は「未設定」を意味し、下位の設定ソース（TOML → manifest 既定値）へ委譲する。
    環境変数は常にこの層より優先される。
    """

    __tablename__ = "collector_plugin_settings"

    plugin_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    enabled: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    interval_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    timeout_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    config_values: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    configuration_managed: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class InstalledPlugin(Base):
    """Record of one dynamically installed plugin distribution."""

    __tablename__ = "installed_plugins"
    __table_args__ = (
        UniqueConstraint("distribution", name="uq_installed_plugin_distribution"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    distribution: Mapped[str] = mapped_column(String(255), index=True)
    version: Mapped[str] = mapped_column(String(64), default="")
    source: Mapped[str] = mapped_column(String(16))
    origin: Mapped[str] = mapped_column(String(1024), default="")
    install_path: Mapped[str] = mapped_column(String(1024), default="")
    status: Mapped[str] = mapped_column(String(16), index=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    installed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )


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
    # UTC で保存（ローカル now だと SQLite 等で tz 欠落時に naive が UTC 扱いされ、表示が 9h ずれる）。
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )


class EventTypeResearch(Base):
    """event_type 単位の WEB 調査結果キャッシュ（原因・対処情報の要約と出典）。

    status: ok（要約または出典あり）/ no_result（有用な情報なし）/ error（検索失敗）。
    origin: auto（事前調査ジョブ）/ chat（ユーザー起点の同期調査）。
    """

    __tablename__ = "event_type_research"
    __table_args__ = (
        UniqueConstraint("event_type", name="uq_event_type_research_event_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), index=True)
    query: Mapped[str] = mapped_column(Text, default="")
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    sources: Mapped[list | None] = mapped_column(JSON, nullable=True)
    llm_model: Mapped[str | None] = mapped_column(String(256), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    origin: Mapped[str] = mapped_column(String(16), default="auto")
    searched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )


class AlertRule(Base):
    """アラートルール定義。"""

    __tablename__ = "alert_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    rule_type: Mapped[str] = mapped_column(
        String(64), index=True
    )  # "event_score" or "metric_threshold"
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # critical / error / warning（運用上の重大度）
    alert_level: Mapped[str] = mapped_column(
        String(32), nullable=False, default="warning", index=True
    )
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    states: Mapped[list["AlertState"]] = relationship(
        back_populates="rule", cascade="all, delete-orphan"
    )
    history: Mapped[list["AlertHistory"]] = relationship(
        back_populates="rule", cascade="all, delete-orphan"
    )


class AlertState(Base):
    """現在のアラート発火状態。"""

    __tablename__ = "alert_states"
    __table_args__ = (
        UniqueConstraint(
            "rule_id", "context_key", name="uq_alert_states_rule_id_context_key"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rule_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("alert_rules.id", ondelete="CASCADE")
    )
    state: Mapped[str] = mapped_column(
        String(32), index=True
    )  # firing / resolved / stale
    context_key: Mapped[str] = mapped_column(String(512), index=True)
    fired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_notified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    rule: Mapped["AlertRule"] = relationship(back_populates="states")


class AlertHistory(Base):
    """通知履歴。"""

    __tablename__ = "alert_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rule_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("alert_rules.id", ondelete="CASCADE")
    )
    # 通知送信時点のレベル（ルール変更後も履歴上の重大度を保つ）
    alert_level: Mapped[str] = mapped_column(
        String(32), nullable=False, default="warning", index=True
    )
    state: Mapped[str] = mapped_column(String(32), index=True)
    context_key: Mapped[str] = mapped_column(String(512), index=True)
    notified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    channel: Mapped[str] = mapped_column(String(64))  # email / none
    success: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    delivery_status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=lambda ctx: (
            "skipped"
            if ctx.get_current_parameters().get("success") is None
            else "succeeded"
            if ctx.get_current_parameters()["success"]
            else "failed"
        ),
    )
    attempt_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    next_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    rule: Mapped["AlertRule"] = relationship(back_populates="history")


class AlertNotificationOutbox(Base):
    """One durable delivery intent per history row; contains no SMTP credentials."""

    __tablename__ = "alert_notification_outbox"
    __table_args__ = (Index("ix_alert_outbox_due", "next_attempt_at", "created_at"),)

    history_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("alert_history.id", ondelete="CASCADE"),
        primary_key=True,
    )
    subject: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text)
    from_address: Mapped[str] = mapped_column(Text)
    to_address: Mapped[str] = mapped_column(Text)
    message_id: Mapped[str] = mapped_column(String(255), unique=True)
    notification: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class IncidentTimelineManualSnapshot(Base):
    """手動保存したインシデントタイムラインスナップショット。"""

    __tablename__ = "incident_timeline_manual_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    from_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    to_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    timestamp_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    operator_note: Mapped[str] = mapped_column(Text, nullable=False)
    build_request_payload: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    snapshot_kind: Mapped[str] = mapped_column(
        String(16), nullable=False, default="manual", index=True
    )
    trigger_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True, index=True
    )
    trigger_evidence: Mapped[dict[str, object] | None] = mapped_column(
        JSON, nullable=True
    )
    graph_context: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )


class PluginConfigurationDraft(Base):
    __tablename__ = "plugin_configuration_drafts"
    plugin_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    config_values: Mapped[dict] = mapped_column(JSON, default=dict)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    tests: Mapped[dict] = mapped_column(JSON, default=dict)


class SSHCredential(Base):
    __tablename__ = "ssh_credentials"
    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255))
    private_key: Mapped[str] = mapped_column(EncryptedString(65536))
    public_key: Mapped[str] = mapped_column(Text)


class SSHConnection(Base):
    __tablename__ = "ssh_connections"
    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255))
    host: Mapped[str] = mapped_column(String(512))
    port: Mapped[int] = mapped_column(Integer, default=22)
    username: Mapped[str] = mapped_column(String(512))
    credential_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("ssh_credentials.id")
    )
    candidate_key: Mapped[str | None] = mapped_column(Text)
    approved_key: Mapped[str | None] = mapped_column(Text)
    revision: Mapped[int] = mapped_column(Integer, default=1)


class User(Base):
    """ログインユーザー（ローカル / ディレクトリ由来の両方）。"""

    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("realm_key", "subject", name="uq_users_realm_subject"),
        CheckConstraint(
            "role IN ('admin', 'operator', 'viewer')", name="ck_users_role"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # ``local`` またはディレクトリ由来の ``dir:<uuid>``。NULL を使わないことで一意制約を効かせる。
    realm_key: Mapped[str] = mapped_column(String(64), default="local")
    # 認証元での不変 ID（ローカルは小文字化したユーザー名、AD は objectGUID など）。
    subject: Mapped[str] = mapped_column(String(512))
    username: Mapped[str] = mapped_column(String(256))
    display_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    directory_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True, index=True
    )
    password_hash: Mapped[str | None] = mapped_column(String(512), nullable=True)
    role: Mapped[str] = mapped_column(String(16), default="viewer")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    password_changed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    sessions: Mapped[list["AuthSession"]] = relationship(
        back_populates="user",
        passive_deletes=True,
    )


class AuthSession(Base):
    """ブラウザのログインセッション。トークンそのものは保存せず SHA-256 だけを持つ。"""

    __tablename__ = "auth_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    client_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(256), nullable=True)
    # 認証に使ったパスワードの世代（User.password_changed_at）。変更後は一致しなくなり無効になる。
    credential_marker: Mapped[str | None] = mapped_column(String(64), nullable=True)

    user: Mapped["User"] = relationship(back_populates="sessions")


class DirectoryConfig(Base):
    """認証先の AD / LDAP ディレクトリ。管理画面（``/api/auth/directories``）から編集する。"""

    __tablename__ = "directory_configs"
    __table_args__ = (
        CheckConstraint("kind IN ('ad', 'ldap')", name="ck_directory_configs_kind"),
        CheckConstraint(
            "transport_security IN ('ldaps', 'starttls', 'none')",
            name="ck_directory_configs_transport",
        ),
        CheckConstraint(
            "group_mode IN ('ad_nested', 'member_of', 'group_search')",
            name="ck_directory_configs_group_mode",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(128), unique=True)
    kind: Mapped[str] = mapped_column(String(8))
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # 接続
    server_uris: Mapped[list[str]] = mapped_column(JSON, default=list)
    transport_security: Mapped[str] = mapped_column(String(8), default="ldaps")
    # LDAPS / StartTLS でサーバ証明書（とホスト名）を検証するか
    tls_verify: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    ca_cert_pem: Mapped[str | None] = mapped_column(Text, nullable=True)
    bind_dn: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    bind_password: Mapped[str | None] = mapped_column(
        EncryptedString(2048), nullable=True
    )
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    # ユーザー検索
    user_search_base: Mapped[str] = mapped_column(String(1024))
    # LDAP のみ。``{username}`` をエスケープしたユーザー名に置き換える（未指定なら ``(<username_attribute>={username})``）
    user_search_filter: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    username_attribute: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # AD のみ。ドメインを付けずに入力されたユーザー名を UPN として探すときの接尾辞（例: example.com）
    ad_upn_suffix: Mapped[str | None] = mapped_column(String(256), nullable=True)
    display_name_attribute: Mapped[str | None] = mapped_column(
        String(128), nullable=True
    )
    email_attribute: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # グループの所属
    group_mode: Mapped[str] = mapped_column(String(16), default="member_of")
    group_search_base: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    group_search_filter: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    # group_search のとき、グループ側でメンバーを表す属性（member / uniqueMember / memberUid）
    group_member_attribute: Mapped[str | None] = mapped_column(
        String(128), nullable=True
    )
    # その属性の値がユーザーの DN（``dn``）かユーザー名（``username``）か
    group_member_value: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    mappings: Mapped[list["DirectoryGroupRoleMapping"]] = relationship(
        back_populates="directory",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="DirectoryGroupRoleMapping.group_dn",
    )


class DirectoryGroupRoleMapping(Base):
    """ディレクトリのグループ DN とロールの対応。ログインのたびに評価し、最も強いロールを使う。"""

    __tablename__ = "directory_group_role_mappings"
    __table_args__ = (
        UniqueConstraint(
            "directory_id",
            "group_dn_normalized",
            name="uq_directory_group_role_mappings_group",
        ),
        CheckConstraint(
            "role IN ('admin', 'operator', 'viewer')",
            name="ck_directory_group_role_mappings_role",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    directory_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("directory_configs.id", ondelete="CASCADE"),
        index=True,
    )
    group_dn: Mapped[str] = mapped_column(String(1024))
    # 照合用（属性名・値の大文字小文字と空白の違いをならした DN）
    group_dn_normalized: Mapped[str] = mapped_column(String(1024))
    role: Mapped[str] = mapped_column(String(16))

    directory: Mapped["DirectoryConfig"] = relationship(back_populates="mappings")
