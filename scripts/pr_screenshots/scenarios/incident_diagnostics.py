"""場面 incident-diagnostics: インシデントの対応手順・診断の実行・結果。

デモデータは、起動時のスクリーンショット用のシード（``SCREENSHOT_E2E_SEED``）が入れる。
診断のデモ（承認済みの接続先、実行の対象、結果）は、モックモードで診断が有効のときだけ入る。
"""

SERVER_ENV = {"SCREENSHOT_E2E_SEED": "1"}
