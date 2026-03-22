# 出典表（priority v1）

イベント種別ガイドの本文は公式ドキュメントを **要約** したものです。転載ではありません。争いが生じた場合は **参照 URL の原文** を優先してください。

## 列の意味

| 列 | 説明 |
|----|------|
| `event_type` | vCenter に記録される種別文字列。**アプリ・DB と完全一致**（大文字小文字・区切り含む） |
| `参照 URL` | Broadcom／VMware 公式（製品ドキュメント、Web Services API リファレンス、KB 等） |
| `参照日` | 当方が内容を確認した日（YYYY-MM-DD） |
| `メモ` | どの節・どの型定義を根拠にしたか、一言 |

## 共通参照（イベント全般）

| event_type | 参照 URL | 参照日 | メモ |
|------------|----------|--------|------|
| （共通） | https://techdocs.broadcom.com/us/en/vmware-cis/vsphere/vsphere-sdks-tools/8-0/web-services-sdk-programming-guide/events-and-alarms/understanding-events.html | 2026-03-22 | Event データオブジェクトの概要、永続化の考え方 |

## 第1弾（データオブジェクト別）

| event_type | 参照 URL | 参照日 | メモ |
|------------|----------|--------|------|
| `vim.event.VmPoweredOnEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.VmPoweredOnEvent.html | 2026-03-22 | Data Object Description（電源オン完了） |
| `vim.event.VmPoweredOffEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.VmPoweredOffEvent.html | 2026-03-22 | Data Object Description（電源オフ完了） |
| `vim.event.VmSuspendedEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.VmSuspendedEvent.html | 2026-03-22 | Data Object Description（サスペンド完了） |
| `vim.event.VmRelocatedEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.VmRelocatedEvent.html | 2026-03-22 | Data Object Description（リロケーション完了）とプロパティ説明 |
| `vim.event.VmGuestShutdownEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.VmGuestShutdownEvent.html | 2026-03-22 | Data Object Description（ゲストシャットダウン要求） |
| `vim.event.HostDisconnectedEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.HostDisconnectedEvent.html | 2026-03-22 | Data Object Description（ホスト切断）と `reason` |

**注:** API リファレンスは **vSphere Web Services API 7.0** のページを使用（型定義の説明はバージョン間で共通部分が多い）。より新しい API バージョンの同型ページが利用可能な場合は、チーム方針に合わせて差し替えてよい。
