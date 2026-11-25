import { fireEvent, render, screen } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import { DiagnosticSettingForm } from './DiagnosticSettingForm'

it('保存できないフォームは直接 submit されても送信しない', () => {
  const submit = vi.fn()
  render(<DiagnosticSettingForm title="対象を追加" editing={false} busy={false} conflict={false}
    error="" canSave={false} onSubmit={submit} onClose={vi.fn()} onReload={vi.fn()} onDelete={vi.fn()}>
    <input />
  </DiagnosticSettingForm>)

  fireEvent.submit(screen.getByRole('form', { name: '対象を追加' }))
  expect(submit).not.toHaveBeenCalled()
})
