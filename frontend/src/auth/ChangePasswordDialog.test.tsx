/**
 * @vitest-environment happy-dom
 */
import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ChangePasswordDialog } from './ChangePasswordDialog'

function fill(current: string, next: string, confirm: string) {
  fireEvent.change(screen.getByLabelText('現在のパスワード'), { target: { value: current } })
  fireEvent.change(screen.getByLabelText('新しいパスワード'), { target: { value: next } })
  fireEvent.change(screen.getByLabelText('新しいパスワード（確認）'), { target: { value: confirm } })
}

describe('ChangePasswordDialog', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('確認欄が一致しなければ送信できない', () => {
    vi.stubGlobal('fetch', vi.fn())
    render(<ChangePasswordDialog onClose={() => {}} />)
    fill('old password', 'new long password', 'different')
    expect(screen.getByText('新しいパスワードが一致しません。')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '変更する' })).toBeDisabled()
  })

  it('変更に成功したら完了を表示し、入力欄を空にする', async () => {
    const fetchMock = vi.fn(() => Promise.resolve(new Response(null, { status: 204 })))
    vi.stubGlobal('fetch', fetchMock)
    render(<ChangePasswordDialog onClose={() => {}} />)
    fill('old password', 'new long password', 'new long password')
    fireEvent.click(screen.getByRole('button', { name: '変更する' }))
    expect(await screen.findByRole('status')).toHaveTextContent('パスワードを変更しました')
    expect(screen.getByLabelText('現在のパスワード')).toHaveValue('')
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe('/api/auth/me/password')
    expect(JSON.parse(String(init.body))).toEqual({
      current_password: 'old password',
      new_password: 'new long password',
    })
  })

  it('サーバの理由（400 の detail）を表示する', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() =>
        Promise.resolve(
          new Response(JSON.stringify({ detail: '現在のパスワードが正しくありません。' }), { status: 400 }),
        ),
      ),
    )
    render(<ChangePasswordDialog onClose={() => {}} />)
    fill('wrong', 'new long password', 'new long password')
    fireEvent.click(screen.getByRole('button', { name: '変更する' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('現在のパスワードが正しくありません。')
  })
})
