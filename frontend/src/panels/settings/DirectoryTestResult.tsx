import type { DirectoryTestResponse, DirectoryTestStageName } from '../../api/schemas'

const STAGE_LABELS: Record<DirectoryTestStageName, string> = {
  connect: '接続',
  user_search: 'ユーザーの検索',
  unique_id: 'ユーザーの ID',
  user_bind: '本人としての認証',
  groups: 'グループとロール',
}

/** 接続試験の結果。段階（接続・ユーザーの検索・ID・本人としての認証・グループ）ごとの成否を出す。 */
export function DirectoryTestResult({ result }: { readonly result: DirectoryTestResponse }) {
  const missingId = result.stages.some((s) => s.stage === 'unique_id' && !s.ok)
  return (
    <div className="directories-panel__test-result" aria-label="接続試験の結果">
      <p className={result.ok ? 'directories-panel__test-ok' : 'directories-panel__test-ng'} role="status">
        {result.ok ? '接続試験に成功しました。' : '接続試験に失敗しました。'}
      </p>
      <ol className="directories-panel__stages">
        {result.stages.map((s) => (
          <li key={s.stage}>
            <span className={s.ok ? 'badge badge--info' : 'badge badge--error'}>{s.ok ? '成功' : '失敗'}</span>{' '}
            <span className="directories-panel__stage-name">{STAGE_LABELS[s.stage]}</span>
            {s.message && <span className="directories-panel__stage-message">{s.message}</span>}
          </li>
        ))}
      </ol>
      {missingId && (
        <p className="directories-panel__warning" role="alert">
          このユーザーは ID 属性の値が取れないため、ログインできません。ID 属性の設定と、サービスアカウントの読み取り権限を確かめてください。
        </p>
      )}
    </div>
  )
}
