import { afterEach, describe, expect, it, vi } from 'vitest'
import { downloadTextFile } from './downloadTextFile'

describe('downloadTextFile', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('creates a Blob with the given UTF-8 text and triggers object URL download', async () => {
    const createSpy = vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:mock')
    const revokeSpy = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {})
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})

    downloadTextFile('out.md', 'hello')

    expect(createSpy).toHaveBeenCalled()
    const blob = createSpy.mock.calls[0]?.[0] as Blob
    expect(blob).toBeInstanceOf(Blob)
    await expect(blob.text()).resolves.toBe('hello')

    expect(clickSpy).toHaveBeenCalled()
    expect(revokeSpy).toHaveBeenCalledWith('blob:mock')
  })
})
