from __future__ import annotations
import os
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, PackageLoader, select_autoescape
from vcenter_event_assistant.alert_levels import alert_level_label_ja
from vcenter_event_assistant.db.models import AlertRule, AlertState
from vcenter_event_assistant.settings import get_settings

class NotificationRenderer:
    def __init__(self):
        # 埋め込みテンプレート用（パッケージ内）
        self.pkg_env = Environment(
            loader=PackageLoader("vcenter_event_assistant", "templates"),
            autoescape=select_autoescape()
        )
        # 外部ディレクトリ用（空なら使用しない）
        self.fs_env = None

    def _get_template_content(self, state_name: str, custom_path: str | None, default_file: str) -> str:
        """
        カスタムパスが指定されている場合はそちらを優先し、
        なければパッケージ内のデフォルトテンプレートを使用する。
        """
        if custom_path and os.path.exists(custom_path):
            return Path(custom_path).read_text(encoding="utf-8")
        
        # パッケージ内から読み込む
        template = self.pkg_env.get_template(default_file)
        return template.render() # ここでは render ではなくソースを返す必要があるが、Jinja の仕組み上 template オブジェクトを返す

    def render(self, rule: AlertRule, state: AlertState, context: dict) -> tuple[str, str]:
        """
        (件名, 本文) のタプルを返す。
        """
        settings = get_settings()

        merged: dict = {**context}
        level = getattr(rule, "alert_level", None) or merged.get("alert_level") or "warning"
        merged.setdefault("alert_level", level)
        merged.setdefault("alert_level_label", alert_level_label_ja(str(merged["alert_level"])))
        
        if state.state == "firing":
            custom_path = settings.alert_template_firing_path
            default_file = "alert_firing.txt.j2"
        else:
            custom_path = settings.alert_template_resolved_path
            default_file = "alert_resolved.txt.j2"

        # Jinja2 テンプレートの解決
        if custom_path and os.path.exists(custom_path):
            # 外部ファイルを使用
            p = Path(custom_path)
            env = Environment(loader=FileSystemLoader(str(p.parent)))
            template = env.get_template(p.name)
        else:
            # 同梱テンプレートを使用
            template = self.pkg_env.get_template(default_file)

        rendered = template.render(**merged)
        
        # 1行目を件名、2行目以降を本文とする
        lines = rendered.strip().splitlines()
        if not lines:
            return "No Subject", ""
        
        subject = lines[0]
        body = "\n".join(lines[1:]).strip()
        
        return subject, body
