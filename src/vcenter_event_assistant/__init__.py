"""vCenter Event Assistant パッケージ。

vCenter イベントとホストメトリクスを収集し、ダッシュボード向け API を提供する。
"""

__version__ = "0.1.0"


def main() -> None:
    """Uvicorn で FastAPI アプリを起動する CLI エントリポイント。"""
    import uvicorn

    from vcenter_event_assistant.main import create_app
    from vcenter_event_assistant.settings import get_settings

    settings = get_settings()
    uvicorn.run(
        create_app,
        factory=True,
        host=settings.uvicorn_host,
        port=settings.uvicorn_port,
    )
