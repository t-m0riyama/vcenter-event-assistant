"""Collector plugin registry and runtime."""

from .registry import CollectorRegistry, get_collector_registry, set_collector_registry

__all__ = ["CollectorRegistry", "get_collector_registry", "set_collector_registry"]
