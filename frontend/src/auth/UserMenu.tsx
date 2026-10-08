import { useState } from 'react'
import { ChangePasswordDialog } from './ChangePasswordDialog'
import { ROLE_LABELS } from './roles'
import { useAuth } from './useAuth'

/** ヘッダーの利用者表示（名前・ロール・パスワード変更・ログアウト）。認証が無効なら出さない。 */
export function UserMenu() {
  const { me, logout } = useAuth()
  const [changingPassword, setChangingPassword] = useState(false)
  const [loggingOut, setLoggingOut] = useState(false)
  const [logoutError, setLogoutError] = useState<string | null>(null)

  if (!me.auth_enabled) return null

  return (
    <div className="user-menu">
      <span className="user-menu__name" title={me.username}>
        {me.display_name?.trim() || me.username}
      </span>
      <span className={`user-menu__role user-menu__role--${me.role}`}>{ROLE_LABELS[me.role]}</span>
      {me.can_change_password && (
        <button type="button" className="btn btn--gray user-menu__btn" onClick={() => setChangingPassword(true)}>
          パスワード変更
        </button>
      )}
      <button
        type="button"
        className="btn btn--gray user-menu__btn"
        disabled={loggingOut}
        onClick={() => {
          setLoggingOut(true)
          setLogoutError(null)
          logout().catch((e: unknown) => {
            setLogoutError(
              `ログアウトできませんでした（${e instanceof Error ? e.message : String(e)}）。ログインは続いています。`,
            )
            setLoggingOut(false)
          })
        }}
      >
        ログアウト
      </button>
      {logoutError && (
        <span className="user-menu__error" role="alert">
          {logoutError}
        </span>
      )}
      {changingPassword && <ChangePasswordDialog onClose={() => setChangingPassword(false)} />}
    </div>
  )
}
