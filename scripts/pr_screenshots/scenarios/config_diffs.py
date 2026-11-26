"""場面 config-diffs: 構成の差分（タイムラインの欄、変更のカード、設定の vCenter の読み取りの状態）。

デモデータは、起動時のスクリーンショット用のシード（``SCREENSHOT_E2E_SEED``）が入れる。
``demo-vm-01``（vm-9001）の CPU とメモリの差分はカードに添い、``demo-esxi-01``（host-9001）の
VLAN の差分は対象の欄でだけ見える。
"""

# 構成の読み取りを「有効」として見せるため、スケジューラを動かす（モックの観測はシードと同じ値なので、
# 差分は増えない）。
SERVER_ENV = {"SCREENSHOT_E2E_SEED": "1", "SCHEDULER_ENABLED": "true"}
