---
name: capture-ui-screenshots
description: >-
  ドキュメント用 UI スクリーンショットを Playwright で取得し docs/images に保存する。
  ユーザーガイドの画面説明（ログイン含む）、frontend.md の画面例、docs/images の再取得、
  スクリーンショット追加・更新を依頼されたときに使う。
---

# UI スクリーンショット取得

リポジトリルートで作業する。依頼がなければコミットしない。

## いつ使うか

- `docs/images/*.png` を最新化する
- 利用者ガイド（`docs/userguide/`）や [docs/development/frontend.md](../../docs/development/frontend.md) に画面画像を載せる
- 新しいタブ・設定サブタブ・ログイン画面のキャプチャを追加する
- ログイン画面は未ログイン状態で撮る（`screenshots.spec.ts` 内の `storageState: { cookies: [], origins: [] }`）。資格情報は画像に入れない

## 手順

1. **新規画面があるとき**
   - [frontend/e2e/screenshots.spec.ts](../../frontend/e2e/screenshots.spec.ts) にステップを追加する（ビューポート **1280×720**、`fullPage: false`）。
   - メインタブ／設定サブタブの切替は `openMainTab` / `openSettingsSubTab` を使う（`.active` 確認と下線アニメ・フォーカスリングを落ち着かせてから撮る）。
   - 空画面を避けるデータが必要なら [src/vcenter_event_assistant/dev/screenshot_e2e_seed.py](../../src/vcenter_event_assistant/dev/screenshot_e2e_seed.py) を最小限拡張し、[tests/test_screenshot_e2e_seed.py](../../tests/test_screenshot_e2e_seed.py) を合わせる。
   - [docs/development/development.md](../../docs/development/development.md) の「出力ファイル」表を更新する。

2. **PNG を取得する（リポジトリへ書き込む）**
   - デモ用シード付きで取る（実環境のホスト名・アカウントを画像に残さない）:
     ```bash
     uv run scripts/capture_ui_screenshots.py --spawn-server
     ```
   - フロントを変えた直後は `--build` を付ける:
     ```bash
     uv run scripts/capture_ui_screenshots.py --spawn-server --build
     ```
   - 詳細・既存サーバー向けの取得は [docs/development/development.md](../../docs/development/development.md) の「UI スクリーンショット」を参照する。

3. **ドキュメントへ埋め込む**
   - 利用者ガイドの該当見出し（多くは「画面別操作」）の直後に `![画面名](../images/....png)` を置く。
   - 開発者向けの画面カタログは [docs/development/frontend.md](../../docs/development/frontend.md)。

4. **検証**
   - 出力 PNG が **1280×720** であること。
   - Markdown の画像パスが `docs/images/` の実ファイルと一致すること。

## 注意

- `WRITE_DOC_SCREENSHOTS_TO_REPO=1` が付く経路（`capture_ui_screenshots.py` / `npm run screenshots*`）だけが `docs/images` を更新する。
- `npm run e2e` は `screenshots.spec.ts` を実行しない。
