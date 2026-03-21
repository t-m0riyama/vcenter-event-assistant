"""vCenter Event Assistant — collect events and host metrics for dashboards."""

__version__ = "0.1.0"


def main() -> None:
    import uvicorn

    from vcenter_event_assistant.main import create_app

    uvicorn.run(create_app, factory=True, host="0.0.0.0", port=8000)
