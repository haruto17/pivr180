import { describe, expect, it, vi } from 'vitest'
import { CONFIRM_MESSAGE, createShutdownSection, SHUTDOWN_URL, type ShutdownDeps } from './shutdown'

function setUp(confirmed: boolean, fetch: ShutdownDeps['fetch']) {
  const deps = { confirm: vi.fn(() => confirmed), fetch: vi.fn(fetch) }
  const section = createShutdownSection(deps)
  const button = section.querySelector('button')
  const status = section.querySelector('[role="status"]')
  if (button === null || status === null) {
    throw new Error('shutdown button or status not rendered')
  }
  return { deps, button, status }
}

describe('createShutdownSection', () => {
  it('shows a shutdown button', () => {
    const { button } = setUp(false, async () => new Response())

    expect(button.textContent).toBe('シャットダウン')
    expect(button.disabled).toBe(false)
  })

  it('asks for confirmation before requesting a shutdown', async () => {
    const { deps, button, status } = setUp(true, async () => new Response(null, { status: 202 }))

    button.click()

    expect(deps.confirm).toHaveBeenCalledWith(CONFIRM_MESSAGE)
    expect(deps.fetch).toHaveBeenCalledWith(SHUTDOWN_URL, { method: 'POST' })
    await vi.waitFor(() => expect(status.textContent).toContain('受け付けました'))
    expect(button.disabled).toBe(true)
  })

  it('does not request a shutdown when the confirmation is cancelled', () => {
    const { deps, button, status } = setUp(false, async () => new Response(null, { status: 202 }))

    button.click()

    expect(deps.confirm).toHaveBeenCalledOnce()
    expect(deps.fetch).not.toHaveBeenCalled()
    expect(button.disabled).toBe(false)
    expect(status.textContent).toBe('')
  })

  it('disables the button while the request is in flight', () => {
    const { button, status } = setUp(true, () => new Promise<Response>(() => {}))

    button.click()

    expect(button.disabled).toBe(true)
    expect(status.textContent).toContain('要求しています')
  })

  it('reports a rejected request and lets the user try again', async () => {
    const { button, status } = setUp(true, async () => new Response(null, { status: 500 }))

    button.click()

    await vi.waitFor(() => expect(status.textContent).toContain('できませんでした'))
    expect(button.disabled).toBe(false)
  })

  it('reports an unreachable device and lets the user try again', async () => {
    const { button, status } = setUp(true, async () => {
      throw new TypeError('Failed to fetch')
    })

    button.click()

    await vi.waitFor(() => expect(status.textContent).toContain('できませんでした'))
    expect(button.disabled).toBe(false)
  })
})
