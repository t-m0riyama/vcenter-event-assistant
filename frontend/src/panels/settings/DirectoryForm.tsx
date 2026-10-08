import type { Directory, DirectoryPolicy, GroupMode, TransportSecurity } from '../../api/schemas'
import { GroupRoleMappingsEditor } from './GroupRoleMappingsEditor'
import { connectionWarnings, withKind, type DirectoryFormState } from './directoryFormState'

const TRANSPORT_LABELS: Record<TransportSecurity, string> = {
  ldaps: 'LDAPS（ldaps://）',
  starttls: 'StartTLS（ldap://）',
  none: '暗号化しない（ldap://）',
}

const GROUP_MODE_LABELS: Record<GroupMode, string> = {
  ad_nested: '入れ子のグループも含める（AD）',
  member_of: 'ユーザーの memberOf 属性',
  group_search: 'グループを検索する（member / uniqueMember / memberUid）',
}

/**
 * 認証ディレクトリの設定の入力欄（admin のみ）。
 *
 * 操作できない項目（全体の方針で禁止された接続、ユーザーがいる間の ID 属性）は無効にして理由を出す。
 * 最終的な判断はサーバが行う（保存時に 422）。
 */
export function DirectoryForm({
  value,
  onChange,
  original,
  policy,
}: {
  readonly value: DirectoryFormState
  readonly onChange: (next: DirectoryFormState) => void
  /** 編集中の保存済みの設定。新規作成なら undefined。 */
  readonly original?: Directory
  /** 接続の方針。読み込めていなければ null（制限せず、保存時のサーバの検証に任せる）。 */
  readonly policy: DirectoryPolicy | null
}) {
  const set = <K extends keyof DirectoryFormState>(key: K, v: DirectoryFormState[K]) =>
    onChange({ ...value, [key]: v })
  const isAd = value.kind === 'ad'
  const editing = original !== undefined
  const idLocked = editing && original.user_count > 0
  const insecureForbidden = policy !== null && !policy.allow_insecure_tls
  const plaintextForbidden = policy !== null && !policy.allow_no_transport_security
  const groupModes: GroupMode[] = isAd ? ['ad_nested', 'member_of'] : ['member_of', 'group_search']
  const warnings = connectionWarnings(value)

  const setTlsVerify = (next: boolean) => {
    if (!next) {
      const ok = confirm(
        'サーバ証明書を検証しないと、通信の相手が本物のディレクトリか確かめられず、中間者攻撃でパスワードを盗まれるおそれがあります。' +
          '検証をやめますか？（可能なら CA 証明書を設定してください）',
      )
      if (!ok) return
    }
    set('tls_verify', next)
  }

  return (
    <div className="directories-panel__form">
      {warnings.length > 0 && (
        <p className="directories-panel__badges">
          {warnings.map((w) => (
            <span key={w} className="badge badge--warning">
              {w}
            </span>
          ))}
        </p>
      )}

      <fieldset className="directories-panel__group">
        <legend>基本</legend>
        <div className="form-grid">
          <label>
            名前
            <input value={value.name} maxLength={128} onChange={(e) => set('name', e.target.value)} />
          </label>
          <label>
            種類
            <select
              value={value.kind}
              disabled={editing}
              title={editing ? '種類は作成後に変えられません' : undefined}
              onChange={(e) => onChange(withKind(value, e.target.value === 'ad' ? 'ad' : 'ldap'))}
            >
              <option value="ldap">LDAP</option>
              <option value="ad">Active Directory</option>
            </select>
          </label>
          <label>
            表示順
            <input
              type="number"
              min={0}
              max={10000}
              value={value.sort_order}
              onChange={(e) => set('sort_order', e.target.value)}
            />
          </label>
          <label className="check">
            <input type="checkbox" checked={value.is_enabled} onChange={(e) => set('is_enabled', e.target.checked)} />
            有効（ログイン画面の認証先に出す）
          </label>
        </div>
      </fieldset>

      <fieldset className="directories-panel__group">
        <legend>接続</legend>
        <div className="form-grid">
          <label className="directories-panel__wide">
            サーバ（1 行に 1 つ。上から順に試す）
            <textarea
              rows={3}
              placeholder={value.transport_security === 'ldaps' ? 'ldaps://dc1.example.com' : 'ldap://dc1.example.com'}
              value={value.server_uris}
              onChange={(e) => set('server_uris', e.target.value)}
            />
          </label>
          <label>
            暗号化
            <select
              value={value.transport_security}
              onChange={(e) => set('transport_security', e.target.value as TransportSecurity)}
            >
              {(Object.keys(TRANSPORT_LABELS) as TransportSecurity[]).map((t) => (
                <option
                  key={t}
                  value={t}
                  disabled={t === 'none' && plaintextForbidden && value.transport_security !== 'none'}
                >
                  {TRANSPORT_LABELS[t]}
                </option>
              ))}
            </select>
          </label>
          <label>
            タイムアウト（秒）
            <input
              type="number"
              min={1}
              max={60}
              value={value.timeout_seconds}
              onChange={(e) => set('timeout_seconds', e.target.value)}
            />
          </label>
          {value.transport_security !== 'none' && (
            <label className="check">
              <input
                type="checkbox"
                checked={value.tls_verify}
                // 禁止されていても、検証する側へ戻す操作はできるようにする
                disabled={insecureForbidden && value.tls_verify}
                onChange={(e) => setTlsVerify(e.target.checked)}
              />
              サーバ証明書を検証する
            </label>
          )}
        </div>
        {plaintextForbidden && (
          <p className="hint">本番環境では暗号化しない接続は使えません。</p>
        )}
        {insecureForbidden && value.transport_security !== 'none' && (
          <p className="hint">
            証明書を検証しない設定は禁止されています（VEA_DIRECTORY_ALLOW_INSECURE_TLS=false）。自己署名の証明書なら、CA
            証明書を設定してください。
          </p>
        )}
        {value.transport_security !== 'none' && (
          <div className="form-grid">
            <label className="directories-panel__wide">
              CA 証明書（PEM。空ならシステムの証明書ストアを使う）
              <textarea
                rows={4}
                placeholder="-----BEGIN CERTIFICATE-----"
                value={value.ca_cert_pem}
                onChange={(e) => set('ca_cert_pem', e.target.value)}
              />
            </label>
          </div>
        )}
      </fieldset>

      <fieldset className="directories-panel__group">
        <legend>サービスアカウント</legend>
        <div className="form-grid">
          <label>
            サービスアカウントの DN（空なら匿名で検索）
            <input value={value.bind_dn} onChange={(e) => set('bind_dn', e.target.value)} />
          </label>
          <label>
            サービスアカウントのパスワード
            <input
              type="password"
              autoComplete="new-password"
              placeholder={editing && original.has_bind_password ? '設定済み（変えるときだけ入力）' : ''}
              value={value.bind_password}
              disabled={value.clear_bind_password}
              onChange={(e) => set('bind_password', e.target.value)}
            />
          </label>
          {editing && original.has_bind_password && (
            <label className="check">
              <input
                type="checkbox"
                checked={value.clear_bind_password}
                onChange={(e) => onChange({ ...value, clear_bind_password: e.target.checked, bind_password: '' })}
              />
              保存済みのパスワードを消す
            </label>
          )}
        </div>
      </fieldset>

      <fieldset className="directories-panel__group">
        <legend>ユーザーの検索</legend>
        <div className="form-grid">
          <label>
            検索ベース
            <input
              placeholder="ou=people,dc=example,dc=com"
              value={value.user_search_base}
              onChange={(e) => set('user_search_base', e.target.value)}
            />
          </label>
          {/* AD は sAMAccountName / UPN / DOMAIN\user で探すので、フィルタと属性は使わない */}
          {!isAd && (
            <>
              <label>
                検索フィルタ（任意。{'{username}'} を含める）
                <input
                  placeholder="(uid={username})"
                  value={value.user_search_filter}
                  onChange={(e) => set('user_search_filter', e.target.value)}
                />
              </label>
              <label>
                ユーザー名の属性（任意）
                <input
                  placeholder="uid"
                  value={value.username_attribute}
                  onChange={(e) => set('username_attribute', e.target.value)}
                />
              </label>
            </>
          )}
          {isAd ? (
            <label>
              UPN サフィックス（任意）
              <input
                placeholder="example.com"
                value={value.ad_upn_suffix}
                onChange={(e) => set('ad_upn_suffix', e.target.value)}
              />
            </label>
          ) : (
            <label>
              ID 属性（空なら entryUUID）
              <input
                placeholder="entryUUID"
                value={value.unique_id_attribute}
                readOnly={idLocked}
                aria-describedby={idLocked ? 'directory-id-locked' : undefined}
                onChange={(e) => set('unique_id_attribute', e.target.value)}
              />
            </label>
          )}
          <label>
            表示名の属性（任意）
            <input
              placeholder={isAd ? 'displayName' : 'cn'}
              value={value.display_name_attribute}
              onChange={(e) => set('display_name_attribute', e.target.value)}
            />
          </label>
          <label>
            メールアドレスの属性（任意）
            <input
              placeholder="mail"
              value={value.email_attribute}
              onChange={(e) => set('email_attribute', e.target.value)}
            />
          </label>
        </div>
        {!isAd && (
          <p className="hint" id={idLocked ? 'directory-id-locked' : undefined}>
            {idLocked
              ? 'このディレクトリのユーザーがいるため、ID 属性は変更できません。変えるには、ディレクトリを無効にして削除し、作り直してください（配下のユーザーとグループの対応表も削除されます）。'
              : 'ユーザーを見分ける属性です。389 DS は nsUniqueId、FreeIPA は ipaUniqueID、eDirectory は GUID を指定します。ユーザーがログインした後は変更できません。'}
          </p>
        )}
      </fieldset>

      <fieldset className="directories-panel__group">
        <legend>グループ</legend>
        <div className="form-grid">
          <label>
            グループの調べ方
            <select value={value.group_mode} onChange={(e) => set('group_mode', e.target.value as GroupMode)}>
              {groupModes.map((m) => (
                <option key={m} value={m}>
                  {GROUP_MODE_LABELS[m]}
                </option>
              ))}
            </select>
          </label>
          {value.group_mode === 'group_search' && (
            <>
              <label>
                グループの検索ベース
                <input
                  placeholder="ou=groups,dc=example,dc=com"
                  value={value.group_search_base}
                  onChange={(e) => set('group_search_base', e.target.value)}
                />
              </label>
              <label>
                グループの検索フィルタ（任意）
                <input
                  placeholder="(objectClass=groupOfNames)"
                  value={value.group_search_filter}
                  onChange={(e) => set('group_search_filter', e.target.value)}
                />
              </label>
              <label>
                メンバーの属性（任意）
                <input
                  placeholder="member"
                  value={value.group_member_attribute}
                  onChange={(e) => set('group_member_attribute', e.target.value)}
                />
              </label>
              <label>
                メンバーの値
                <select
                  value={value.group_member_value}
                  onChange={(e) => set('group_member_value', e.target.value as DirectoryFormState['group_member_value'])}
                >
                  <option value="">既定（属性に合わせる）</option>
                  <option value="dn">ユーザーの DN</option>
                  <option value="username">ユーザー名（memberUid）</option>
                </select>
              </label>
            </>
          )}
        </div>
        <h4 className="directories-panel__subheading">グループとロールの対応</h4>
        <p className="hint">ログインのたびに評価し、一致したもののうち最も強いロールにします。</p>
        <GroupRoleMappingsEditor value={value.mappings} onChange={(m) => set('mappings', m)} />
      </fieldset>
    </div>
  )
}
