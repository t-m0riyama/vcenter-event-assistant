# 出典表（priority v1）

イベント種別ガイドの本文は公式ドキュメントを **要約** したものです。転載ではありません。争いが生じた場合は **参照 URL の原文** を優先してください。

## 列の意味

| 列 | 説明 |
|----|------|
| `event_type` | vCenter に記録される種別文字列。**アプリ・DB と完全一致**（大文字小文字・区切り含む） |
| `参照 URL` | Broadcom／VMware 公式（製品ドキュメント、Web Services API リファレンス、KB 等） |
| `参照日` | 当方が内容を確認した日（YYYY-MM-DD） |
| `メモ` | どの節・どの型定義を根拠にしたか、一言 |

## テンプレ（行を複製して追記）

| event_type | 参照 URL | 参照日 | メモ |
|------------|----------|--------|------|
| （例）`vim.event.VmPoweredOnEvent` | （例）https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.VmPoweredOnEvent.html | YYYY-MM-DD | `VmPoweredOnEvent` データオブジェクト説明 |

（以下、第1弾の行を追加）
