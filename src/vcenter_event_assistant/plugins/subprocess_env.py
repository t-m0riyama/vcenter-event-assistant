"""プラグイン関連の子プロセスに渡す環境変数。

ワーカーやインストーラは第三者コードを実行するため、起動にしか使わない秘密は渡さない
（監査 M-1 の一部対応）。
"""

from __future__ import annotations

import os

# 子プロセスに引き継がない環境変数（大文字で比較）。
# Settings は環境変数名の大文字小文字を区別せず、フィールド名の別名も受け付けるため、
# 受け付けるすべての綴りを対象にする（``settings.AuthSettingsMixin.bootstrap_admin_password``）。
WITHHELD_ENV_VARS = frozenset(
    {"VEA_BOOTSTRAP_ADMIN_PASSWORD", "BOOTSTRAP_ADMIN_PASSWORD"}
)


def child_process_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k.upper() not in WITHHELD_ENV_VARS}
