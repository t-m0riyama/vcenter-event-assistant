import { useRef, useState } from 'react'
import { diagnosticSSHPath } from '../../api/diagnostics'
import { DiagnosticCommands } from './DiagnosticCommands'
import { DiagnosticTargets } from './DiagnosticTargets'
import { SSHField, type SSHConnectionsState, type SSHFieldHandle } from './SSHField'
import './DiagnosticsPanel.css'

const diagnosticSshCopy = {
  keyName: '診断用 SSH 鍵',
  connectionHint: 'ログ収集とは別に用意した診断用のアカウントと鍵を登録してください。',
  registrationRequest: (username: string) =>
    `接続先で SSH を有効化し、診断用ユーザー「${username}」に次の公開鍵を登録してください。ESXi では診断用のローカルユーザーに Administrator ロールと Shell Access を与えてください。登録後、SSH ホスト鍵の SHA-256 指紋を別経路でお知らせください。`,
}

export function DiagnosticsPanel() {
  const ssh = useRef<SSHFieldHandle>(null)
  const [selected, setSelected] = useState('')
  const [connections, setConnections] = useState<SSHConnectionsState>({ status: 'loading' })

  return <>
    <p className="hint">診断用の接続先、実行の対象、追加のコマンドを設定します。</p>
    <div className="diagnostics-panel">
      <section className="panel" aria-labelledby="diagnostic-ssh-title">
        <h2 id="diagnostic-ssh-title">SSH の鍵と接続先</h2>
        <p className="hint">診断用のアカウントは強い権限を持ちます。ログ収集とは別のアカウントと鍵を使用してください。</p>
        <SSHField ref={ssh} phase="all" value={selected} onChange={setSelected} apiPath={diagnosticSSHPath}
          copy={diagnosticSshCopy} allowUpdate onConnectionsChange={setConnections} />
      </section>
      <DiagnosticTargets ssh={connections} reloadSSH={async () => ssh.current?.reload()} />
      <DiagnosticCommands />
    </div>
  </>
}
