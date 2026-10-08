import { useContext } from 'react'
import { AuthContext, type AuthContextValue } from './authContext'

/** ログイン中の利用者とロール判定。 */
export function useAuth(): AuthContextValue {
  return useContext(AuthContext)
}
