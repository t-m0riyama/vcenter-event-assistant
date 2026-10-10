import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { Me } from '../api/schemas'
import { AuthContext } from './authContext'
import { roleAtLeast } from './roles'
import { UserMenu } from './UserMenu'

function renderMenu(overrides: Partial<Me> = {}, logout: () => Promise<void> = async () => {}) {
  const me: Me = {
    auth_enabled: true,
    username: 'alice',
    display_name: null,
    role: 'admin',
    realm: 'local',
    can_change_password: true,
    ...overrides,
  }
  return render(
    <AuthContext.Provider value={{ me, hasRole: (r) => roleAtLeast(me.role, r), logout, refresh: async () => {} }}>
      <button type="button">外のボタン</button>
      <UserMenu />
    </AuthContext.Provider>,
  )
}

const avatar = () => screen.getByRole('button', { name: /アカウントメニュー/ })

describe('UserMenu', () => {
  it('アバターに頭文字を出し、押すと名前・ロール・操作をまとめたメニューを開く', () => {
    renderMenu({ display_name: 'Alice Smith' })
    expect(avatar()).toHaveTextContent('A')
    expect(avatar()).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()

    fireEvent.click(avatar())
    expect(avatar()).toHaveAttribute('aria-expanded', 'true')
    const menu = screen.getByRole('menu', { name: 'アカウント' })
    expect(within(menu).getByText('Alice Smith')).toBeInTheDocument()
    expect(within(menu).getByText('alice')).toBeInTheDocument()
    expect(within(menu).getByText('管理者')).toBeInTheDocument()
    expect(within(menu).getAllByRole('menuitem').map((el) => el.textContent)).toEqual(['パスワード変更', 'ログアウト'])
    // 開いたら最初の項目にフォーカスを移す
    expect(within(menu).getByRole('menuitem', { name: 'パスワード変更' })).toHaveFocus()
  })

  it('上下キーで項目を移り、Esc で閉じてアバターへフォーカスを戻す', () => {
    renderMenu()
    fireEvent.click(avatar())
    const menu = screen.getByRole('menu')
    const [password, logout] = within(menu).getAllByRole('menuitem')
    fireEvent.keyDown(menu, { key: 'ArrowDown' })
    expect(logout).toHaveFocus()
    fireEvent.keyDown(menu, { key: 'ArrowDown' })
    expect(password).toHaveFocus()
    fireEvent.keyDown(menu, { key: 'ArrowUp' })
    expect(logout).toHaveFocus()
    fireEvent.keyDown(menu, { key: 'Escape' })
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
    expect(avatar()).toHaveFocus()
  })

  it('アバターで下キーを押しても開く', () => {
    renderMenu()
    fireEvent.keyDown(avatar(), { key: 'ArrowDown' })
    expect(screen.getByRole('menu')).toBeInTheDocument()
  })

  it('メニューの外を押すと閉じる', () => {
    renderMenu()
    fireEvent.click(avatar())
    fireEvent.pointerDown(screen.getByRole('button', { name: '外のボタン' }))
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
  })

  it('パスワード変更を選ぶとメニューを閉じてダイアログを開く。変更できない利用者には出さない', () => {
    const { unmount } = renderMenu()
    fireEvent.click(avatar())
    fireEvent.click(screen.getByRole('menuitem', { name: 'パスワード変更' }))
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    unmount()

    renderMenu({ can_change_password: false })
    fireEvent.click(avatar())
    expect(screen.queryByRole('menuitem', { name: 'パスワード変更' })).not.toBeInTheDocument()
  })

  it('ログアウトに失敗したら、メニューを閉じた後もアバターの横に理由を出す', async () => {
    const logout = vi.fn(() => Promise.reject(new Error('network')))
    renderMenu({}, logout)
    fireEvent.click(avatar())
    fireEvent.click(screen.getByRole('menuitem', { name: 'ログアウト' }))
    expect(logout).toHaveBeenCalled()
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('ログアウトできませんでした（network）'))
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
  })

  it('ログアウトの処理中に開き直しても、項目にフォーカスが移り Esc で閉じられる', async () => {
    let reject: (e: Error) => void = () => {}
    const logout = vi.fn(() => new Promise<void>((_, r) => (reject = r)))
    renderMenu({ can_change_password: false }, logout)
    fireEvent.click(avatar())
    fireEvent.click(screen.getByRole('menuitem', { name: 'ログアウト' }))
    fireEvent.click(avatar())
    const item = screen.getByRole('menuitem', { name: 'ログアウト' })
    expect(item).toHaveAttribute('aria-disabled', 'true')
    expect(item).toHaveFocus()
    // 処理中にもう一度押しても 2 回目は送らない
    fireEvent.click(item)
    expect(logout).toHaveBeenCalledTimes(1)
    fireEvent.keyDown(screen.getByRole('menu'), { key: 'Escape' })
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
    reject(new Error('network'))
    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())
  })

  it('認証が無効なら何も出さない', () => {
    renderMenu({ auth_enabled: false })
    expect(screen.queryByRole('button', { name: /アカウントメニュー/ })).not.toBeInTheDocument()
  })
})
