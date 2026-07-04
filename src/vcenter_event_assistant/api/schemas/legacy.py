"""Backward-compatible re-exports for legacy ``from .legacy import *`` consumers."""

from vcenter_event_assistant.api.schemas.alerts import (
    AlertHistoryListResponse,
    AlertHistoryRead,
    AlertRuleCreate,
    AlertRuleRead,
    AlertRulesImportRequest,
    AlertRulesImportResponse,
    AlertRuleUpdate,
    AlertStateResolveRequest,
)
from vcenter_event_assistant.api.schemas.base import _normalize_to_utc
from vcenter_event_assistant.api.schemas.config import AppConfigResponse
from vcenter_event_assistant.api.schemas.dashboard import (
    DashboardSummary,
    EventTypeCountRow,
    HighCpuHostRow,
    HighMemHostRow,
)
from vcenter_event_assistant.api.schemas.digests import (
    DigestListResponse,
    DigestRead,
    DigestRunRequest,
)
from vcenter_event_assistant.api.schemas.event_score_rules import (
    EventScoreRuleCreate,
    EventScoreRuleRead,
    EventScoreRulesImportRequest,
    EventScoreRulesImportResponse,
    EventScoreRuleUpdate,
)
from vcenter_event_assistant.api.schemas.event_type_guides import (
    EventTypeGuideCreate,
    EventTypeGuideRead,
    EventTypeGuidesImportRequest,
    EventTypeGuidesImportResponse,
    EventTypeGuideUpdate,
)
from vcenter_event_assistant.api.schemas.events import (
    EventListResponse,
    EventRateBucket,
    EventRateSeriesResponse,
    EventRead,
    EventTypeGuideSnippet,
    EventTypesResponse,
    EventUserCommentPatch,
)
from vcenter_event_assistant.api.schemas.metrics import (
    MetricKeysResponse,
    MetricPoint,
    MetricSeriesResponse,
)
from vcenter_event_assistant.api.schemas.vcenters import (
    VCenterCreate,
    VCenterRead,
    VCenterUpdate,
)

__all__ = [
    "_normalize_to_utc",
    "AlertHistoryListResponse",
    "AlertHistoryRead",
    "AlertRuleCreate",
    "AlertRuleRead",
    "AlertRulesImportRequest",
    "AlertRulesImportResponse",
    "AlertRuleUpdate",
    "AlertStateResolveRequest",
    "AppConfigResponse",
    "DashboardSummary",
    "DigestListResponse",
    "DigestRead",
    "DigestRunRequest",
    "EventListResponse",
    "EventRateBucket",
    "EventRateSeriesResponse",
    "EventRead",
    "EventScoreRuleCreate",
    "EventScoreRuleRead",
    "EventScoreRulesImportRequest",
    "EventScoreRulesImportResponse",
    "EventScoreRuleUpdate",
    "EventTypeCountRow",
    "EventTypeGuideCreate",
    "EventTypeGuideRead",
    "EventTypeGuidesImportRequest",
    "EventTypeGuidesImportResponse",
    "EventTypeGuideSnippet",
    "EventTypeGuideUpdate",
    "EventTypesResponse",
    "EventUserCommentPatch",
    "HighCpuHostRow",
    "HighMemHostRow",
    "MetricKeysResponse",
    "MetricPoint",
    "MetricSeriesResponse",
    "VCenterCreate",
    "VCenterRead",
    "VCenterUpdate",
]
