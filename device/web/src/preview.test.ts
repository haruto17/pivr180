import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { PREVIEW_URL, renderPreview } from './preview'

describe('renderPreview', () => {
  let root: HTMLElement

  beforeEach(() => {
    vi.useFakeTimers()
    root = document.createElement('section')
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  function image(): HTMLImageElement {
    const found = root.querySelector('img')
    if (found === null) {
      throw new Error('img not found')
    }
    return found
  }

  function status(): HTMLParagraphElement {
    const found = root.querySelector('p')
    if (found === null) {
      throw new Error('p not found')
    }
    return found
  }

  it('shows the live preview stream in an image', () => {
    renderPreview(root)

    expect(root.querySelector('h2')?.textContent).toBe('プレビュー')
    expect(new URL(image().src).pathname).toBe(PREVIEW_URL)
    expect(image().alt).not.toBe('')
    expect(status().hidden).toBe(true)
  })

  it('replaces whatever the root showed before', () => {
    root.textContent = 'loading'

    renderPreview(root)

    expect(root.textContent).not.toContain('loading')
    expect(root.querySelectorAll('img')).toHaveLength(1)
  })

  it('tells the user and reconnects after the retry delay when the stream fails', () => {
    renderPreview(root, 1000)
    const first = image().src

    image().dispatchEvent(new Event('error'))

    expect(status().hidden).toBe(false)
    expect(status().textContent).toContain('再接続')
    vi.advanceTimersByTime(999)
    expect(image().src).toBe(first)
    vi.advanceTimersByTime(1)
    expect(image().src).not.toBe(first)
    expect(new URL(image().src).pathname).toBe(PREVIEW_URL)
  })

  it('hides the message once a frame arrives', () => {
    renderPreview(root, 1000)
    image().dispatchEvent(new Event('error'))
    vi.advanceTimersByTime(1000)

    image().dispatchEvent(new Event('load'))

    expect(status().hidden).toBe(true)
  })
})
