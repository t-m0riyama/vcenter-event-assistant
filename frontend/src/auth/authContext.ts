import { createContext } from 'react'
import type { Me, Role } from '../api/schemas'

export type AuthContextValue = {
  /** ログイン中の利用者（認証が無効なサーバでは暗黙の admin）。 */
  readonly me: Me
  /** ``role`` 以上のロールを持つか。画面の表示を切り替えるためだけに使い、最終判断はサーバが行う。 */
  readonly hasRole: (role: Role) => boolean
  /** サーバでセッションを失効させてからログイン画面へ戻す。失効できなければ例外を投げる。 */
  readonly logout: () => Promise<void>
  /** ログイン中の利用者をサーバから読み直す（自分の表示名などを画面で変えた後に呼ぶ）。 */
  readonly refresh: () => Promise<void>
}

/** 認証が無効なサーバ（従来動作）と同じ扱い。AuthGate の外（単体テスト等）でもこの値になる。 */
export const AUTH_DISABLED_ME: Me = {
  auth_enabled: false,
  username: 'anonymous',
  display_name: null,
  role: 'admin',
  realm: 'disabled',
  can_change_password: false,
}

export const AuthContext = createContext<AuthContextValue>({
  me: AUTH_DISABLED_ME,
  hasRole: () => true,
  logout: async () => {},
  refresh: async () => {},
})
