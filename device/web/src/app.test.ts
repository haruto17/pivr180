import { beforeEach, describe, expect, it } from 'vitest'
import { renderApp } from './app'

describe('renderApp', () => {
  let root: HTMLElement

  beforeEach(() => {
    root = document.createElement('main')
  })

  it('shows the device name as the heading', () => {
    renderApp(root)

    expect(root.querySelector('h1')?.textContent).toBe('pivr180')
  })

  it('shows the shutdown button', () => {
    renderApp(root)

    expect(root.querySelector('section button')?.textContent).toBe('シャットダウン')
  })

  it('replaces whatever the root showed before', () => {
    root.textContent = 'loading'

    renderApp(root)

    expect(root.textContent).not.toContain('loading')
    expect(root.querySelectorAll('h1')).toHaveLength(1)
  })
})
