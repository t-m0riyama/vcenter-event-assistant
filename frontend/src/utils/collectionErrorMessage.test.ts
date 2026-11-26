import { describe, expect, it } from 'vitest'

import { collectionErrorMessage } from './collectionErrorMessage'

it.each([
  ['ConfigReadTimeout: 構成の読み取りがタイムアウトしました。', /タイムアウトしました。.*インベントリの収集のタイムアウト設定（INVENTORY_SYNC_TIMEOUT_SECONDS）/],
  ['ConfigReadMissing: 構成の読み取り結果を受け取れませんでした。', /受け取れませんでした。次の収集で自動的にやり直します。続く場合は管理者に連絡してください。/],
  ['InventoryReadsClosed: インベントリの読み取り受付は終了しました。', /受付は終了しました。.*管理者/],
])('構成にも記録される %s に案内を出す', (record, advice) => {
  expect(collectionErrorMessage(record)).toMatch(advice)
})

describe('collectionErrorMessage', () => {
  const connectionAdvice = '接続先、ポート、ネットワーク、vCenter の状態を確認してください。'

  it.each([
    'AttributeError', 'TypeError', 'KeyError', 'IndexError', 'NameError', 'UnboundLocalError',
    'AssertionError', 'ZeroDivisionError', 'RecursionError',
    'vmodl.fault.InvalidArgument', 'InvalidType', 'InvalidRequest',
  ])('%s は管理者への連絡を案内する', (name) => {
    expect(collectionErrorMessage(`${name}: collector execution failed`)).toBe(
      `アプリまたはプラグインの内部エラーの可能性があります。設定を確かめても直らなければ、管理者に連絡してください。（種類: ${name}）`,
    )
  })

  it.each([
    'InvalidLogin', 'NoPermission', 'NotAuthenticated', 'vim.fault.InvalidLogin', 'vim.fault.PasswordExpired',
    'vmodl.fault.SecurityError', 'PermissionDenied',
  ])('%s は認証と権限の確認を案内する', (name) => {
    expect(collectionErrorMessage(`${name}: collector execution failed`)).toBe(
      `認証または権限の問題で収集できませんでした。ユーザー名、パスワード、接続先での権限を確認してください。（種類: ${name}）`,
    )
  })

  it.each([
    'ConnectionRefusedError', 'ConnectionResetError', 'ConnectionError', 'gaierror', 'HostConnectFault', 'OSError',
    'RemoteDisconnected', 'ConnectionAbortedError', 'BrokenPipeError', 'vmodl.fault.HostCommunication', 'ConnectError', 'ConnectionLost',
  ])('%s は接続先の確認を案内する', (name) => {
    expect(collectionErrorMessage(`${name}: collector execution failed`)).toBe(
      `接続できなかったため収集できませんでした。${connectionAdvice}（種類: ${name}）`,
    )
  })

  it.each(['TimeoutError', 'ConnectTimeout', 'ReadTimeout'])('%s はタイムアウトと実行間隔の見直しを案内する', (name) => {
    expect(collectionErrorMessage(`${name}: collector execution failed`)).toBe(
      `収集がタイムアウトしました。${connectionAdvice}コレクタの「タイムアウト（秒）」と「実行間隔（秒）」も見直してください。（種類: ${name}）`,
    )
  })

  it.each(['SSLError', 'SSLCertVerificationError', 'SSLEOFError', 'SSLZeroReturnError'])('%s は証明書と検証設定の確認を案内する', (name) => {
    expect(collectionErrorMessage(`${name}: collector execution failed`)).toBe(
      `証明書のエラーで収集できませんでした。vCenter の証明書と検証の設定（verify_ssl、CA バンドル）を確認してください。（種類: ${name}）`,
    )
  })

  it.each(['ImportError', 'ModuleNotFoundError', 'EntryPointNotFound'])('%s はプラグインの導入の確認を案内する', (name) => {
    expect(collectionErrorMessage(`${name}: No module named 'example'`)).toBe(
      `プラグインの読み込みに失敗したため収集できませんでした。プラグインが正しく導入されているか確認してください。（種類: ${name}）`,
    )
  })

  it('SSH のホスト鍵を検証できない場合は接続先とホスト鍵の確認を案内する', () => {
    expect(collectionErrorMessage('HostKeyNotVerifiable: collector execution failed'))
      .toBe('SSH 接続先のホスト鍵を検証できませんでした。SSH の接続先と登録したホスト鍵を確認してください。（種類: HostKeyNotVerifiable）')
  })

  it('ValueError は接続設定と SSH の接続先・ホスト鍵・鍵の確認を案内する', () => {
    expect(collectionErrorMessage('ValueError: collector execution failed'))
      .toBe('接続の設定に問題がある可能性があります。接続先のホスト名、ポート、プロトコル、許可された接続先などの設定を確認してください。SSH を使う場合は、接続先が選択されているか、ホスト鍵が承認されているか、SSH 鍵が登録されているかも確認してください。（種類: ValueError）')
  })

  it('Exception は接続先が想定どおりに応答しなかった可能性を案内する', () => {
    expect(collectionErrorMessage('Exception: collector execution failed'))
      .toBe('接続先（vCenter など）が想定どおりに応答しなかった可能性があります。接続先の設定、ポート、接続先の稼働状態を確認してください。（種類: Exception）')
  })

  it('関係の読み取りの時間切れは、記録に続けて管理者への設定見直し依頼を案内する', () => {
    expect(collectionErrorMessage('InventoryReadTimeout: 読み取りがタイムアウトしました。'))
      .toBe('読み取りがタイムアウトしました。vCenter の応答に時間がかかっていないか確認し、インベントリの収集のタイムアウト設定（INVENTORY_SYNC_TIMEOUT_SECONDS）の見直しを管理者に依頼してください。（種類: InventoryReadTimeout）')
  })

  it.each([
    ['InventoryReadStillRunning', '前回の読み取りがまだ実行中です。'],
    ['InventoryWorkerUnavailable', '専用スレッドに空きがありません。'],
  ])('%s は自動での再実行と管理者への連絡を案内する', (name, detail) => {
    expect(collectionErrorMessage(`${name}: ${detail}`))
      .toBe(`${detail}前回の読み取りが長引いている可能性があります。次の収集で自動的にやり直します。続く場合は管理者に連絡してください。（種類: ${name}）`)
  })

  it.each([
    'BatchValidationError', '_BatchValidationError', 'ManifestValidationError', '_ManifestValidationError', 'NotImplementedError',
  ])('%s はプラグインの修正を案内する', (name) => {
    expect(collectionErrorMessage(`${name}: collector execution failed`))
      .toBe(`プラグインの修正が必要です。プラグインの提供元または管理者に連絡してください。（種類: ${name}）`)
  })

  it.each([
    'plugin worker service is unavailable',
    'worker is not running',
    'worker pipe is closed',
    'worker exited before responding',
    'worker sent malformed response',
    'worker sent an invalid response ID',
    'unknown error',
    'CollectorWorkerError',
    'CollectorWorkerServiceError',
  ])('ワーカーの記録「%s」を種類として表示する', (kind) => {
    expect(collectionErrorMessage(`${kind}: collector execution failed`))
      .toBe(`収集を実行するプロセスが異常終了したか、利用できません。続く場合は管理者に連絡してください。（種類: ${kind}）`)
  })

  it.each([
    ['plugin worker request exceeds size limit', '要求'],
    ['worker response exceeds size limit', '応答'],
    ['ResponseTooLarge', '応答'],
  ])('ワーカーの記録「%s」は%sのサイズ超過を案内する', (kind, payload) => {
    expect(collectionErrorMessage(`${kind}: collector execution failed`))
      .toBe(`プラグインの${payload}が大きすぎます。取得の範囲を見直すか、プラグインの提供元に連絡してください。（種類: ${kind}）`)
  })

  it('既知の型に日本語の説明がある場合は、案内に元の説明を添える', () => {
    expect(collectionErrorMessage('ImportError: 温度プラグインを読み込めません。'))
      .toBe('プラグインの読み込みに失敗したため収集できませんでした。プラグインが正しく導入されているか確認してください。温度プラグインを読み込めません。（種類: ImportError）')
    expect(collectionErrorMessage('TimeoutError: 応答が遅すぎます。'))
      .toBe(`収集がタイムアウトしました。${connectionAdvice}コレクタの「タイムアウト（秒）」と「実行間隔（秒）」も見直してください。応答が遅すぎます。（種類: TimeoutError）`)
  })

  it('未知の型の日本語は種類と合わせてそのまま表示する', () => {
    expect(collectionErrorMessage('CustomReadFault: 読み取り受付は終了しました。'))
      .toBe('読み取り受付は終了しました。（種類: CustomReadFault）')
  })

  it('型名のない日本語はそのまま表示する', () => {
    const policyError = 'APP_ENV=production では vCenter protocol は https のみ許可されます'
    expect(collectionErrorMessage(policyError)).toBe(policyError)
  })

  it('未知のエラーは分かる範囲で種類を添える', () => {
    expect(collectionErrorMessage('example.CustomError: worker returned an error'))
      .toBe('収集できませんでした。（種類: example.CustomError）')
    expect(collectionErrorMessage('worker exited before responding')).toBe('収集できませんでした。')
    expect(collectionErrorMessage('unknown')).toBe('収集できませんでした。')
  })

  it('型名だけが記録されている場合も説明する', () => {
    expect(collectionErrorMessage('InvalidLogin'))
      .toBe('認証または権限の問題で収集できませんでした。ユーザー名、パスワード、接続先での権限を確認してください。（種類: InvalidLogin）')
    expect(collectionErrorMessage('CustomError')).toBe('収集できませんでした。（種類: CustomError）')
  })
})
