import { useCallback, useEffect, useImperativeHandle, useRef, useState, type Ref } from 'react'
import { ApiError, apiDelete, apiGet, apiPost, apiPut } from '../../api'
import {
  sshConnectionSchema, sshConnectionsSchema, sshCredentialSchema, sshCredentialsSchema, sshPublicKeySchema,
  type SSHConnection, type SSHCredential,
} from '../../api/schemas/sshSetup'
import { errorText } from './setupError'
import { privateKeyHeader, reflectsPrivateKey } from './sshUploadErrors'

export type SSHConnectionsState =
  | { status: 'loading' | 'error' }
  | { status: 'ready'; connections: SSHConnection[] }

export type SSHFieldHandle = { reload: () => Promise<SSHConnection[] | undefined> }

function downloadPublicKey(key: SSHCredential) {
  const url = URL.createObjectURL(new Blob([key.public_key], { type: 'text/plain' }))
  const link = document.createElement('a')
  link.href = url
  link.download = 'ssh-public-key.pub'
  link.click()
  URL.revokeObjectURL(url)
}

export function SSHField({
  value, onChange, hostHint = '', phase, apiPath, copy, allowUpdate = false, onConnectionsChange, ref,
}: {
  value: unknown
  onChange: (value: string) => void
  hostHint?: string
  phase: 'all' | 'ssh' | 'trust'
  apiPath: string
  copy: { keyName: string; connectionHint: string; registrationRequest: (username: string) => string }
  allowUpdate?: boolean
  onConnectionsChange?: (state: SSHConnectionsState) => void
  ref?: Ref<SSHFieldHandle>
}) {
  const credentialsPath = `${apiPath}/credentials`
  const connectionsPath = `${apiPath}/connections`
  const [keys, setKeys] = useState<SSHCredential[]>([])
  const [connections, setConnections] = useState<SSHConnection[]>([])
  const [loadStatus, setLoadStatus] = useState<SSHConnectionsState['status']>('loading')
  const loaded = loadStatus === 'ready'
  const [editing, setEditing] = useState<'create' | 'update' | null>(null)
  const [host, setHost] = useState(hostHint)
  const [port, setPort] = useState(22)
  const [username, setUsername] = useState('')
  const [credentialId, setCredentialId] = useState('')
  const [keyName, setKeyName] = useState(copy.keyName)
  const [keyFile, setKeyFile] = useState<File | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [confirmed, setConfirmed] = useState(false)
  const [keyMethod, setKeyMethod] = useState('existing')
  const selected = connections.find(c => c.id === value)
  const selectedKey = keys.find(k => k.id === (editing ? credentialId : selected?.credential_id ?? credentialId)
    && !privateKeyHeader.test(k.public_key))
  const clearKeyFile = () => {
    setKeyFile(null)
    if (fileInput.current) fileInput.current.value = ''
  }

  const showConnections = useCallback((items: SSHConnection[]) => {
    setConnections(items)
    setLoadStatus('ready')
    onConnectionsChange?.({ status: 'ready', connections: items })
  }, [onConnectionsChange])

  const reload = useCallback(async (signal?: AbortSignal) => {
    setLoadStatus('loading')
    onConnectionsChange?.({ status: 'loading' })
    try {
      const [rawKeys, rawConnections] = await Promise.all([
        apiGet<SSHCredential[]>(credentialsPath, signal),
        apiGet<SSHConnection[]>(connectionsPath, signal),
      ])
      if (signal?.aborted) return
      // プラグインでは従来の鍵の形式を受け付ける。
      const ks = allowUpdate ? sshCredentialsSchema.parse(rawKeys) : rawKeys
      const cs = allowUpdate ? sshConnectionsSchema.parse(rawConnections) : rawConnections
      setKeys(ks)
      showConnections(cs)
      if (!ks.length) setKeyMethod('generate')
      return cs
    } catch (e) {
      if (signal?.aborted) return
      setLoadStatus('error')
      onConnectionsChange?.({ status: 'error' })
      throw e
    }
  }, [allowUpdate, connectionsPath, credentialsPath, onConnectionsChange, showConnections])

  useEffect(() => {
    const controller = new AbortController()
    void reload(allowUpdate ? controller.signal : undefined).catch(e => {
      if (!controller.signal.aborted) setError(errorText(e))
    })
    return () => controller.abort()
  }, [allowUpdate, reload])

  const run = async <T,>(work: () => Promise<T>) => {
    setBusy(true)
    setError('')
    try {
      return await work()
    } catch (e) {
      setError(errorText(e))
      if (allowUpdate && e instanceof ApiError && e.status === 409) setConfirmed(false)
    } finally {
      setBusy(false)
    }
  }

  const refresh = () => {
    if (busy || loadStatus === 'loading') return Promise.resolve(undefined)
    setConfirmed(false)
    return run(reload)
  }
  useImperativeHandle(ref, () => ({ reload: refresh }))

  const beginEditing = (mode: 'create' | 'update') => {
    const original = mode === 'update' || !allowUpdate ? selected : undefined
    setHost(hostHint || original?.host || '')
    setPort(original?.port ?? 22)
    setUsername(original?.username ?? '')
    setCredentialId(original?.credential_id ?? '')
    if (allowUpdate) {
      clearKeyFile()
      setKeyMethod(keys.length ? 'existing' : 'generate')
      setConfirmed(false)
      setError('')
    }
    setEditing(editing === mode ? null : mode)
  }

  const saveKey = async (file?: File | null) => {
    let key: SSHCredential
    if (file === undefined) {
      const response = await apiPost<SSHCredential>(credentialsPath, { name: keyName })
      key = allowUpdate ? sshCredentialSchema.parse(response) : response
    } else {
      if (allowUpdate) clearKeyFile()
      if (!file || file.size > 32768) {
        throw new Error(allowUpdate ? '32 KiB 以下の秘密鍵を選択してください。' : '32KiB以下の秘密鍵を選択してください。')
      }
      const privateKey = await file.text()
      let response: SSHCredential
      try {
        response = await apiPost<SSHCredential>(credentialsPath, { name: keyName, private_key: privateKey })
      } catch (e) {
        if (reflectsPrivateKey(errorText(e), privateKey)) throw new Error('秘密鍵を登録できませんでした。')
        throw e
      }
      if (
        !sshPublicKeySchema.safeParse(response.public_key).success
        || privateKeyHeader.test(response.public_key)
        || reflectsPrivateKey(response.public_key, privateKey, 'lenient')
      ) {
        throw new Error('秘密鍵を登録できませんでした。')
      }
      key = allowUpdate ? sshCredentialSchema.parse(response) : response
      if (!allowUpdate) setKeyFile(null)
    }
    setCredentialId(key.id)
    if (allowUpdate) setKeys(current => [...current, key])
    else await reload()
  }

  const refreshAfterConnectionChange = async (response: unknown) => {
    if (allowUpdate) {
      const saved = sshConnectionSchema.parse(response)
      showConnections(connections.some(item => item.id === saved.id)
        ? connections.map(item => item.id === saved.id ? saved : item)
        : [...connections, saved])
    } else {
      await reload()
    }
  }

  const saveConnection = async () => {
    const original = editing === 'update' ? selected : undefined
    const name = original && original.name !== original.host ? original.name : host
    const body = { name, host, port, username, credential_id: credentialId }
    const saved = original
      ? await apiPut<SSHConnection>(`${connectionsPath}/${original.id}`, body)
      : await apiPost<SSHConnection>(connectionsPath, body)
    await refreshAfterConnectionChange(saved)
    onChange(saved.id)
    setEditing(null)
    setConfirmed(false)
  }

  const removeKey = async (id: string) => {
    await apiDelete(`${credentialsPath}/${id}`)
    setCredentialId('')
    if (allowUpdate) {
      setKeys(keys.filter(key => key.id !== id))
      if (keys.length === 1) setKeyMethod('generate')
    } else {
      await reload()
    }
  }

  const probeHostKey = async (connection: SSHConnection) => {
    const saved = await apiPost(`${connectionsPath}/${connection.id}/host-key`, {})
    setConfirmed(false)
    onChange(connection.id)
    await refreshAfterConnectionChange(saved)
  }

  const approveHostKey = async (connection: SSHConnection) => {
    const saved = await apiPost(`${connectionsPath}/${connection.id}/approve`, {
      fingerprint: connection.candidate_fingerprint, revision: connection.revision,
    })
    if (allowUpdate) setConfirmed(false)
    onChange(connection.id)
    await refreshAfterConnectionChange(saved)
  }

  return <div className="plugin-ssh-field">
    {phase !== 'trust' && <>
      <select disabled={allowUpdate && (!loaded || busy)} aria-label={allowUpdate ? '登録済みの SSH 接続先' : '登録済みSSH接続先'} value={String(value ?? '')} onChange={e => {
        onChange(e.target.value)
        setConfirmed(false)
        if (allowUpdate) {
          clearKeyFile()
          setEditing(null)
          setCredentialId('')
          setError('')
        }
      }}>
        <option value="">{allowUpdate ? 'SSH 接続先を選択' : 'SSH接続先を選択'}</option>
        {connections.map(c => <option key={c.id} value={c.id}>{allowUpdate ? `${c.name}（${c.host}）` : `${c.name} (${c.host})`}</option>)}
      </select>
      <button type="button" className="btn btn--gray" disabled={allowUpdate && (!loaded || busy)} onClick={() => beginEditing('create')}>
        {allowUpdate ? '接続先を追加' : '接続先を追加・変更'}
      </button>
      {allowUpdate && selected && <button type="button" className="btn btn--gray" disabled={busy} onClick={() => beginEditing('update')}>選択した接続先を変更</button>}
      {allowUpdate && <button type="button" className="btn btn--gray" disabled={busy || loadStatus === 'loading'}
        onClick={() => void refresh()}>SSH の設定を再取得</button>}
      {allowUpdate && loadStatus === 'loading' && <p role="status">SSH の設定を読み込み中です…</p>}
      {editing && <fieldset className={allowUpdate ? 'form-grid' : undefined} disabled={busy}>
        <legend>{editing === 'update' ? 'SSH 接続を変更' : allowUpdate ? 'SSH 接続を登録' : 'SSH接続を登録'}</legend>
        <p className={allowUpdate ? 'diagnostic-wide' : undefined}>{copy.connectionHint}</p>
        <label>ホスト名<input value={host} onChange={e => setHost(e.target.value)} /></label>
        <label>{allowUpdate ? 'SSH ポート' : 'SSHポート'}<input type="number" min={1} max={65535} value={port} onChange={e => setPort(Number(e.target.value))} /></label>
        <label>{allowUpdate ? 'SSH ユーザー名' : 'SSHユーザー名'}<input value={username} onChange={e => setUsername(e.target.value)} autoComplete="off" /></label>
        {keyMethod === 'existing' && <label>登録済みの鍵
          <select value={credentialId} onChange={e => setCredentialId(e.target.value)}>
            <option value="">鍵を選択</option>
            {keys.map(k => <option key={k.id} value={k.id}>{k.name}</option>)}
          </select>
        </label>}
        <label>鍵の用意方法
          <select value={keyMethod} onChange={e => { setKeyMethod(e.target.value); setCredentialId(''); if (allowUpdate) clearKeyFile() }}>
            <option value="existing">登録済みの鍵を使う</option>
            <option value="generate">新しい鍵を生成する</option>
            <option value="upload">秘密鍵をアップロードする</option>
          </select>
        </label>
        {keyMethod !== 'existing' && <div className={allowUpdate ? 'form-grid diagnostic-wide' : undefined}>
          <label>鍵の名前<input value={keyName} onChange={e => setKeyName(e.target.value)} /></label>
          {keyMethod === 'generate' && !credentialId && <button type="button" className={allowUpdate ? 'btn btn--gray diagnostic-grid-action' : 'btn btn--gray'} onClick={() => void run(() => saveKey())}>アプリで鍵を生成</button>}
          {keyMethod === 'upload' && !credentialId && <>
            <label>既存の秘密鍵をアップロード<input ref={fileInput} type="file" onChange={e => setKeyFile(e.target.files?.[0] ?? null)} /></label>
            <button type="button" className={allowUpdate ? 'btn btn--gray diagnostic-grid-action' : 'btn btn--gray'} disabled={!keyFile} onClick={() => void run(() => saveKey(keyFile))}>選択した鍵を登録</button>
          </>}
          {credentialId && <p className={allowUpdate ? 'diagnostic-wide' : undefined} role="status">鍵を用意しました。公開鍵を管理者へ渡してください。</p>}
        </div>}
        <button type="button" className={allowUpdate ? 'btn btn--gray diagnostic-grid-action diagnostic-wide' : 'btn btn--gray'} disabled={!host || !username || !credentialId} onClick={() => void run(saveConnection)}>接続先を保存</button>
      </fieldset>}
      {selectedKey && <details>
        <summary>管理者へ渡す公開鍵と登録依頼</summary>
        <p>{copy.registrationRequest((editing && allowUpdate ? username : selected?.username) || username)}</p>
        <pre>{selectedKey.public_key}</pre>
        <button type="button" className="btn btn--gray" onClick={() => void navigator.clipboard.writeText(selectedKey.public_key).catch(e => setError(errorText(e)))}>公開鍵をコピー</button>
        <button type="button" className="btn btn--gray" onClick={() => downloadPublicKey(selectedKey)}>公開鍵をダウンロード</button>
        <details>
          <summary>鍵の管理</summary>
          <button type="button" className="btn btn--gray" disabled={allowUpdate && busy} onClick={() => void run(() => removeKey(selectedKey.id))}>未使用の鍵を削除</button>
        </details>
      </details>}
    </>}
    {phase !== 'ssh' && selected && (!allowUpdate || !editing) && <fieldset disabled={busy || (allowUpdate && !loaded)}>
      <legend>接続先のホスト鍵を確認</legend>
      <p>{selected.host}:{selected.port} / {selected.username} — {selected.approved ? '承認済み' : '承認待ち'}</p>
      {selected.fingerprint && <p>承認済み指紋: <code>{selected.fingerprint}</code></p>}
      {!selected.approved && !selected.candidate_fingerprint && <button type="button" className="btn btn--gray" onClick={() => void run(() => probeHostKey(selected))}>ホスト鍵を取得</button>}
      {selected.candidate_fingerprint && (!selected.approved || selected.candidate_fingerprint !== selected.fingerprint) && <>
        <p>取得した指紋: <code>{selected.candidate_fingerprint}</code></p>
        <label><input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)} />管理者から入手した指紋と一致することを確認しました</label>
        <button type="button" className="btn btn--gray" disabled={!confirmed} onClick={() => void run(() => approveHostKey(selected))}>このホスト鍵を承認</button>
      </>}
      <details>
        <summary>ホスト鍵を再確認する</summary>
        <button type="button" className="btn btn--gray" onClick={() => void run(() => probeHostKey(selected))}>ホスト鍵を再取得</button>
      </details>
    </fieldset>}
    {phase === 'trust' && !selected && <p className={allowUpdate ? 'error-banner' : undefined} role="alert">前の手順でSSH接続先を選択してください。</p>}
    {error && <p className={allowUpdate ? 'error-banner' : undefined} role="alert">{error}</p>}
  </div>
}
