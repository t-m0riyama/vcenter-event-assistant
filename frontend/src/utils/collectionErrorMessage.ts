const connectionAdvice = '接続先、ポート、ネットワーク、vCenter の状態を確認してください。'
const fallbackMessage = '収集できませんでした。'
const workerFailureMessage = '収集を実行するプロセスが異常終了したか、利用できません。続く場合は管理者に連絡してください。'
const sizeAdvice = '取得の範囲を見直すか、プラグインの提供元に連絡してください。'
const oversizedRequest = `プラグインの要求が大きすぎます。${sizeAdvice}`
const oversizedResponse = `プラグインの応答が大きすぎます。${sizeAdvice}`

// ワーカーの通信エラーでは、例外の型名が入る位置に remote.py の文言が記録される。
const workerMessages = new Map([
  ['plugin worker service is unavailable', workerFailureMessage],
  ['worker is not running', workerFailureMessage],
  ['plugin worker request exceeds size limit', oversizedRequest],
  ['worker response exceeds size limit', oversizedResponse],
  ['worker pipe is closed', workerFailureMessage],
  ['worker exited before responding', workerFailureMessage],
  ['worker sent malformed response', workerFailureMessage],
  ['worker sent an invalid response ID', workerFailureMessage],
  ['unknown error', workerFailureMessage],
])

const collectionErrorMessages = [
  {
    types: [
      'AttributeError', 'TypeError', 'KeyError', 'IndexError', 'NameError', 'UnboundLocalError',
      'AssertionError', 'ZeroDivisionError', 'RecursionError',
      'InvalidArgument', 'InvalidType', 'InvalidRequest',
    ],
    message: 'アプリまたはプラグインの内部エラーの可能性があります。設定を確かめても直らなければ、管理者に連絡してください。',
  },
  {
    types: ['InvalidLogin', 'NoPermission', 'NotAuthenticated', 'PasswordExpired', 'SecurityError', 'PermissionDenied'],
    message: '認証または権限の問題で収集できませんでした。ユーザー名、パスワード、接続先での権限を確認してください。',
  },
  {
    types: ['HostKeyNotVerifiable'],
    message: 'SSH 接続先のホスト鍵を検証できませんでした。SSH の接続先と登録したホスト鍵を確認してください。',
  },
  {
    types: [
      'ConnectionRefusedError', 'ConnectionResetError', 'ConnectionError', 'gaierror', 'HostConnectFault', 'OSError',
      'RemoteDisconnected', 'ConnectionAbortedError', 'BrokenPipeError', 'HostCommunication', 'ConnectError', 'ConnectionLost',
    ],
    message: `接続できなかったため収集できませんでした。${connectionAdvice}`,
  },
  {
    types: ['ValueError'],
    message: '接続の設定に問題がある可能性があります。接続先のホスト名、ポート、プロトコル、許可された接続先などの設定を確認してください。'
      + 'SSH を使う場合は、接続先が選択されているか、ホスト鍵が承認されているか、SSH 鍵が登録されているかも確認してください。',
  },
  {
    types: ['Exception'],
    message: '接続先（vCenter など）が想定どおりに応答しなかった可能性があります。接続先の設定、ポート、接続先の稼働状態を確認してください。',
  },
  {
    types: ['TimeoutError', 'ConnectTimeout', 'ReadTimeout'],
    message: `収集がタイムアウトしました。${connectionAdvice}コレクタの「タイムアウト（秒）」と「実行間隔（秒）」も見直してください。`,
  },
  {
    types: ['InventoryReadTimeout', 'ConfigReadTimeout'],
    message: 'vCenter の応答に時間がかかっていないか確認し、インベントリの収集のタイムアウト設定（INVENTORY_SYNC_TIMEOUT_SECONDS）の見直しを管理者に依頼してください。',
    detailFirst: true,
  },
  {
    types: ['InventoryReadStillRunning', 'InventoryWorkerUnavailable'],
    message: '前回の読み取りが長引いている可能性があります。次の収集で自動的にやり直します。続く場合は管理者に連絡してください。',
    detailFirst: true,
  },
  {
    types: ['ConfigReadMissing'],
    message: '次の収集で自動的にやり直します。続く場合は管理者に連絡してください。',
    detailFirst: true,
  },
  {
    types: ['InventoryReadsClosed'],
    message: '収集が再開しない場合は管理者に連絡してください。',
    detailFirst: true,
  },
  {
    types: ['SSLError', 'SSLCertVerificationError', 'SSLEOFError', 'SSLZeroReturnError'],
    message: '証明書のエラーで収集できませんでした。vCenter の証明書と検証の設定（verify_ssl、CA バンドル）を確認してください。',
  },
  {
    types: ['ImportError', 'ModuleNotFoundError', 'EntryPointNotFound'],
    message: 'プラグインの読み込みに失敗したため収集できませんでした。プラグインが正しく導入されているか確認してください。',
  },
  {
    types: ['BatchValidationError', '_BatchValidationError', 'ManifestValidationError', '_ManifestValidationError', 'NotImplementedError'],
    message: 'プラグインの修正が必要です。プラグインの提供元または管理者に連絡してください。',
  },
  {
    types: ['CollectorWorkerError', 'CollectorWorkerServiceError'],
    message: workerFailureMessage,
  },
  {
    types: ['ResponseTooLarge'],
    message: oversizedResponse,
  },
]

/** 保存済みのエラー文字列から利用者向けの説明を作る。 */
export function collectionErrorMessage(record: string): string {
  const separator = record.indexOf(':')
  const prefix = separator === -1 ? record : record.slice(0, separator)
  const workerGuidance = separator === -1 ? undefined : workerMessages.get(prefix)
  const typeName = workerGuidance || /^[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*$/.test(prefix) ? prefix : undefined
  const shortName = typeName?.split('.').at(-1)
  const category = collectionErrorMessages.find(({ types }) => shortName && types.includes(shortName))
  const guidance = workerGuidance ?? category?.message
  const detail = typeName && separator !== -1 ? record.slice(separator + 1).replace(/^[ \t]+/, '') : record
  const japaneseDetail = /[\p{Script=Hiragana}\p{Script=Katakana}\p{Script=Han}]/u.test(detail) ? detail : undefined
  const parts = category?.detailFirst ? [japaneseDetail, guidance] : [guidance, japaneseDetail]
  const message = parts.join('') || fallbackMessage
  // 型名だけを保存した記録では、既知の型名や例外の接尾辞で判別する。
  const hasType = typeName && (separator !== -1 || guidance || /(?:Error|Exception|Fault)$/.test(typeName))
  return hasType ? `${message}（種類: ${typeName}）` : message
}
