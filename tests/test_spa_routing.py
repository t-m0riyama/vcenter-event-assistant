"""SPA フォールバックのパス判定テスト。"""

from vcenter_event_assistant.main import is_spa_fallback_reserved_path


def test_spa_reserved_path_matches_api_prefix_with_slash() -> None:
    assert is_spa_fallback_reserved_path("api/events")
    assert is_spa_fallback_reserved_path("api")


def test_spa_reserved_path_does_not_match_apidocs_like_names() -> None:
    assert not is_spa_fallback_reserved_path("apidocs.html")
    assert not is_spa_fallback_reserved_path("apiary")


def test_spa_reserved_path_matches_openapi_paths() -> None:
    assert is_spa_fallback_reserved_path("docs")
    assert is_spa_fallback_reserved_path("openapi.json")
    assert is_spa_fallback_reserved_path("redoc")
