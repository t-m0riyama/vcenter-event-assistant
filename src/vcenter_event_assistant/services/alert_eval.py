from __future__ import annotations
import logging
from datetime import datetime, timezone, timedelta
from sqlalchemy import select, desc
from vcenter_event_assistant.db.models import AlertRule, AlertState, AlertHistory, EventRecord, MetricSample
from vcenter_event_assistant.db.session import session_scope
from vcenter_event_assistant.alert_levels import alert_level_label_ja
from vcenter_event_assistant.services.notification.renderer import NotificationRenderer
from vcenter_event_assistant.services.notification.email_channel import EmailChannel

logger = logging.getLogger(__name__)

class AlertEvaluator:
    def __init__(self):
        self.renderer = NotificationRenderer()
        self.email_channel = EmailChannel()

    async def evaluate_all(self) -> None:
        """全有効ルールを評価する。"""
        async with session_scope() as session:
            res = await session.execute(select(AlertRule).where(AlertRule.is_enabled.is_(True)))
            rules = res.scalars().all()
        
        for rule in rules:
            try:
                if rule.rule_type == "event_score":
                    await self._evaluate_event_score(rule)
                elif rule.rule_type == "metric_threshold":
                    await self._evaluate_metric_threshold(rule)
            except Exception as e:
                logger.error(f"Error evaluating rule {rule.name} ({rule.id}): {e}", exc_info=True)

    async def _evaluate_event_score(self, rule: AlertRule) -> None:
        threshold = rule.config.get("threshold", 60)
        cooldown_mins = rule.config.get("cooldown_minutes", 10)
        
        async with session_scope() as session:
            # 最新の閾値超えイベントを検索
            res = await session.execute(
                select(EventRecord)
                .where(EventRecord.notable_score >= threshold)
                .order_by(desc(EventRecord.occurred_at))
                .limit(1)
            )
            latest_event = res.scalar_one_or_none()
            
            # 現在の状態を取得
            res = await session.execute(
                select(AlertState).where(AlertState.rule_id == rule.id)
            )
            current_state = res.scalar_one_or_none()
            
            now = datetime.now(timezone.utc)
            
            if latest_event:
                context_key = latest_event.event_type
                # 発火条件: イベントが存在し、現在発火中でないか、別の種類のイベントの場合（イベントタイプごとに管理する場合）
                # 今回はシンプルに「ルールに対して1つの状態」とする
                if not current_state or current_state.state == "resolved":
                    # 発火！
                    new_state = AlertState(
                        rule_id=rule.id,
                        state="firing",
                        context_key=context_key,
                        fired_at=latest_event.occurred_at
                    )
                    session.add(new_state)
                    if current_state:
                        await session.delete(current_state)
                    await session.flush()
                    await self._notify(rule, new_state, {"details": f"Notable event detected: {latest_event.message} (Score: {latest_event.notable_score})"})
                else:
                    # すでに発火中。fired_at を更新（延長）
                    current_state.fired_at = latest_event.occurred_at
                    current_state.context_key = context_key
            else:
                # 該当イベントなし。発火中の場合、クールダウン期間を過ぎていれば回復
                if current_state and current_state.state == "firing":
                    fired_at = current_state.fired_at
                    if fired_at.tzinfo is None:
                        fired_at = fired_at.replace(tzinfo=timezone.utc)
                    
                    if now - fired_at > timedelta(minutes=cooldown_mins):
                        current_state.state = "resolved"
                        current_state.resolved_at = now
                        await session.flush()
                        await self._notify(rule, current_state, {"details": f"No notable events (score >= {threshold}) for {cooldown_mins} minutes."})

    async def _evaluate_metric_threshold(self, rule: AlertRule) -> None:
        metric_key = rule.config.get("metric_key")
        threshold = rule.config.get("threshold")
        if not metric_key or threshold is None:
            return

        async with session_scope() as session:
            # 各エンティティ（ホスト等）ごとに状態を管理したいため、最新のサンプルをエンティティごとに取得
            # 今回は簡略化のため、全エンティティの最新をチェック
            res = await session.execute(
                select(MetricSample)
                .where(MetricSample.metric_key == metric_key)
                .order_by(MetricSample.entity_moid, desc(MetricSample.sampled_at))
            )
            # entity_moid ごとの最新値を抽出
            latest_samples = {}
            for s in res.scalars().all():
                if s.entity_moid not in latest_samples:
                    latest_samples[s.entity_moid] = s

            # 現在の状態を取得
            res = await session.execute(
                select(AlertState).where(AlertState.rule_id == rule.id)
            )
            states = {st.context_key: st for st in res.scalars().all()}
            
            for moid, sample in latest_samples.items():
                is_above = sample.value >= threshold
                current = states.get(moid)
                
                if is_above:
                    if not current or current.state == "resolved":
                        # 発火
                        new_state = AlertState(
                            rule_id=rule.id,
                            state="firing",
                            context_key=moid,
                            fired_at=sample.sampled_at
                        )
                        session.add(new_state)
                        if current:
                            await session.delete(current)
                        await session.flush()
                        await self._notify(rule, new_state, {"details": f"Metric {metric_key} reached {sample.value} (threshold: {threshold}) on {sample.entity_name}"})
                else:
                    if current and current.state == "firing":
                        # 回復
                        current.state = "resolved"
                        current.resolved_at = sample.sampled_at
                        await session.flush()
                        await self._notify(rule, current, {"details": f"Metric {metric_key} dropped to {sample.value} (threshold: {threshold}) on {sample.entity_name}"})

    async def _notify(self, rule: AlertRule, state: AlertState, extra_context: dict) -> None:
        fired_at = state.fired_at
        if fired_at and fired_at.tzinfo is None:
            fired_at = fired_at.replace(tzinfo=timezone.utc)
        
        resolved_at = state.resolved_at
        if resolved_at and resolved_at.tzinfo is None:
            resolved_at = resolved_at.replace(tzinfo=timezone.utc)

        level = getattr(rule, "alert_level", None) or "warning"
        context = {
            "rule_name": rule.name,
            "state": state.state,
            "context_key": state.context_key,
            "fired_at": fired_at,
            "resolved_at": resolved_at,
            "alert_level": level,
            "alert_level_label": alert_level_label_ja(level),
            **extra_context,
        }
        
        subject, body = self.renderer.render(rule, state, context)
        
        success = True
        error_msg = None
        try:
            await self.email_channel.notify(rule, state, subject, body)
        except Exception as e:
            success = False
            error_msg = str(e)
            logger.error(f"Failed to send notification for rule {rule.id}: {e}")

        # 履歴を保存
        async with session_scope() as session:
            history = AlertHistory(
                rule_id=rule.id,
                alert_level=level,
                state=state.state,
                context_key=state.context_key,
                notified_at=datetime.now(timezone.utc),
                channel="email",
                success=success,
                error_message=error_msg,
            )
            session.add(history)
