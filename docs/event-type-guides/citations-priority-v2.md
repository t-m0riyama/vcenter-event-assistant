# 出典表（priority v2）

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

## 第2弾（データオブジェクト別）

| event_type | 参照 URL | 参照日 | メモ |
|------------|----------|--------|------|
| `vim.event.DrsVmPoweredOnEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.DrsVmPoweredOnEvent.html | 2026-03-22 | Data Object Description（DRS による電源オン） |
| `vim.event.HostConnectedEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.HostConnectedEvent.html | 2026-03-22 | Data Object Description（接続成功） |
| `vim.event.HostShutdownEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.HostShutdownEvent.html | 2026-03-22 | Data Object Description・`reason` |
| `vim.event.VmClonedEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.VmClonedEvent.html | 2026-03-22 | Data Object Description・`sourceVm` |
| `vim.event.VmRegisteredEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.VmRegisteredEvent.html | 2026-03-22 | Data Object Description（登録成功） |
| `vim.event.VmRemovedEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.VmRemovedEvent.html | 2026-03-22 | Data Object Description（管理からの削除） |
| `vim.event.VmResettingEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.VmResettingEvent.html | 2026-03-22 | Data Object Description（リセット） |
| `vim.event.VmStartingEvent` | https://developer.broadcom.com/xapis/vsphere-web-services-api/7.0/vim.event.VmStartingEvent.html | 2026-03-22 | Data Object Description（電源オン進行と記載。完了は `VmPoweredOnEvent` と区別） |

**注:** API リファレンスは **vSphere Web Services API 7.0** のページを使用（型定義の説明はバージョン間で共通部分が多い）。より新しい API バージョンの同型ページが利用可能な場合は、チーム方針に合わせて差し替えてよい。
