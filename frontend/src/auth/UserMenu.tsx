import { useEffect, useId, useRef, useState, type KeyboardEvent } from 'react'
import { ChangePasswordDialog } from './ChangePasswordDialog'
import { ROLE_LABELS } from './roles'
import { useAuth } from './useAuth'

/** アバターに出す 1 文字（表示名か利用者名の先頭。英字は大文字）。 */
function avatarInitial(name: string): string {
  const first = Array.from(name.trim())[0] ?? '?'
  return first.toUpperCase()
}

/**
 * ヘッダーの利用者メニュー。アバターを押すと、名前・ロール・パスワード変更・ログアウトをまとめた
 * メニューを開く。認証が無効なら出さない。
 */
export function UserMenu() {
  const { me, logout } = useAuth()
  const [open, setOpen] = useState(false)
  const [changingPassword, setChangingPassword] = useState(false)
  const [loggingOut, setLoggingOut] = useState(false)
  const [logoutError, setLogoutError] = useState<string | null>(null)
  const rootRef = useRef<HTMLDivElement>(null)
  const buttonRef = useRef<HTMLButtonElement>(null)
  const menuRef = useRef<HTMLDivElement>(null)
  const menuId = useId()

  const menuItems = () =>
    Array.from(menuRef.current?.querySelectorAll<HTMLButtonElement>('[role="menuitem"]:not(:disabled)') ?? [])

  const close = (restoreFocus: boolean) => {
    setOpen(false)
    if (restoreFocus) buttonRef.current?.focus()
  }

  // 開いたら最初の項目へフォーカスを移し、メニューの外を押したら閉じる。
  useEffect(() => {
    if (!open) return
    menuRef.current?.querySelector<HTMLButtonElement>('[role="menuitem"]:not(:disabled)')?.focus()
    const onPointerDown = (e: PointerEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('pointerdown', onPointerDown)
    return () => document.removeEventListener('pointerdown', onPointerDown)
  }, [open])

  if (!me.auth_enabled) return null

  const name = me.display_name?.trim() || me.username

  const onMenuKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    const items = menuItems()
    const index = items.indexOf(document.activeElement as HTMLButtonElement)
    if (e.key === 'Escape') {
      e.preventDefault()
      close(true)
    } else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault()
      const step = e.key === 'ArrowDown' ? 1 : -1
      items[(index + step + items.length) % items.length]?.focus()
    } else if (e.key === 'Home' || e.key === 'End') {
      e.preventDefault()
      items[e.key === 'Home' ? 0 : items.length - 1]?.focus()
    } else if (e.key === 'Tab') {
      // メニューの外へフォーカスが出たら閉じる（フォーカスの移動は止めない）。
      setOpen(false)
    }
  }

  return (
    <div className="user-menu" ref={rootRef}>
      {logoutError && (
        <span className="user-menu__error" role="alert">
          {logoutError}
        </span>
      )}
      <button
        ref={buttonRef}
        type="button"
        className={`user-menu__avatar user-menu__avatar--${me.role}`}
        aria-label={`アカウントメニュー（${name}・${ROLE_LABELS[me.role]}）`}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        title={name}
        onClick={() => setOpen((v) => !v)}
        onKeyDown={(e) => {
          if (e.key === 'ArrowDown' && !open) {
            e.preventDefault()
            setOpen(true)
          }
        }}
      >
        <span aria-hidden="true">{avatarInitial(name)}</span>
      </button>
      {open && (
        <div
          ref={menuRef}
          id={menuId}
          className="user-menu__panel"
          role="menu"
          aria-label="アカウント"
          onKeyDown={onMenuKeyDown}
        >
          <div className="user-menu__identity">
            <span className="user-menu__name" title={me.username}>
              {name}
            </span>
            {name !== me.username && <span className="user-menu__username">{me.username}</span>}
            <span className={`user-menu__role user-menu__role--${me.role}`}>{ROLE_LABELS[me.role]}</span>
          </div>
          {me.can_change_password && (
            <button
              type="button"
              role="menuitem"
              className="user-menu__item"
              onClick={() => {
                close(true)
                setChangingPassword(true)
              }}
            >
              パスワード変更
            </button>
          )}
          <button
            type="button"
            role="menuitem"
            className="user-menu__item"
            // disabled にするとフォーカスを置けず、処理中に開き直したメニューをキーボードで操作できなくなる。
            aria-disabled={loggingOut || undefined}
            onClick={() => {
              if (loggingOut) return
              close(true)
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
        </div>
      )}
      {changingPassword && <ChangePasswordDialog onClose={() => setChangingPassword(false)} />}
    </div>
  )
}
