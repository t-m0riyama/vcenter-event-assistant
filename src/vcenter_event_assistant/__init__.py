"""vCenter Event Assistant パッケージ。

vCenter イベントとホストメトリクスを収集し、ダッシュボード向け API を提供する。
"""

__version__ = "0.1.0"


def main() -> None:
    """Uvicorn で FastAPI アプリを起動する CLI エントリポイント。"""
    import uvicorn

    from vcenter_event_assistant.main import create_app

    uvicorn.run(create_app, factory=True, host="0.0.0.0", port=8000)
