import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  captureTime,
  renderCaptures,
  thumbnailUrl,
  type CaptureSummary,
} from './captures'

const NEWER: CaptureSummary = {
  id: '20261108-090000-000',
  complete: true,
  sync_warning: true,
}
const OLDER: CaptureSummary = {
  id: '20261107-123456-001',
  complete: true,
  sync_warning: false,
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function api(captures: CaptureSummary[], deleteStatus = 204) {
  return vi.fn(async (input: string, init?: RequestInit) => {
    if (init?.method === 'DELETE') {
      return new Response(null, { status: deleteStatus })
    }
    return json(captures)
  })
}

function ids(root: HTMLElement): string[] {
  return [...root.querySelectorAll<HTMLElement>('li')].map(
    (item) => item.dataset.id ?? '',
  )
}

function item(root: HTMLElement, id: string): HTMLElement {
  return root.querySelector<HTMLElement>(`li[data-id="${id}"]`)!
}

async function settle(): Promise<void> {
  await new Promise((resolve) => setTimeout(resolve, 0))
}

describe('captureTime', () => {
  it('reads the UTC time the capture was saved from its id', () => {
    expect(captureTime('20261107-123456-001')?.toISOString()).toBe(
      '2026-11-07T12:34:56.000Z',
    )
  })

  it('is null for ids that are not capture names', () => {
    expect(captureTime('notes')).toBeNull()
  })
})

describe('renderCaptures', () => {
  let root: HTMLElement

  beforeEach(() => {
    root = document.createElement('section')
  })

  it('lists the captures in the order the API returns them', async () => {
    await renderCaptures(root, { fetch: api([NEWER, OLDER]) })

    expect(ids(root)).toEqual([NEWER.id, OLDER.id])
    expect(root.querySelector('.captures-status')?.textContent).toContain('2 件')
  })

  it('shows when each capture was taken', async () => {
    await renderCaptures(root, { fetch: api([OLDER]) })

    const time = item(root, OLDER.id).querySelector('time')!
    expect(time.dateTime).toBe('2026-11-07T12:34:56.000Z')
    expect(time.textContent).toBe(
      new Date('2026-11-07T12:34:56Z').toLocaleString('ja-JP'),
    )
  })

  it('shows lazily loaded thumbnails of both sides', async () => {
    await renderCaptures(root, { fetch: api([OLDER]) })

    const images = [...item(root, OLDER.id).querySelectorAll('img')]
    expect(images.map((image) => image.getAttribute('src'))).toEqual([
      thumbnailUrl(OLDER.id, 'left'),
      thumbnailUrl(OLDER.id, 'right'),
    ])
    expect(images.map((image) => image.alt)).toEqual(['左', '右'])
    expect(images.every((image) => image.loading === 'lazy')).toBe(true)
  })

  it('marks captures with a sync warning or left incomplete', async () => {
    const incomplete = { id: '20261106-000000-000', complete: false, sync_warning: null }

    await renderCaptures(root, { fetch: api([NEWER, OLDER, incomplete]) })

    const badges = (id: string) =>
      [...item(root, id).querySelectorAll('.capture-badge')].map((b) => b.textContent)
    expect(badges(NEWER.id)).toEqual(['同期警告'])
    expect(badges(OLDER.id)).toEqual([])
    expect(badges(incomplete.id)).toEqual(['不完全'])
  })

  it('says there are no captures when the list is empty', async () => {
    await renderCaptures(root, { fetch: api([]) })

    expect(ids(root)).toEqual([])
    expect(root.querySelector('.captures-status')?.textContent).toBe(
      '撮影データはありません。',
    )
  })

  it('says the list could not be loaded when the API fails', async () => {
    await renderCaptures(root, { fetch: vi.fn(async () => json({}, 500)) })

    expect(ids(root)).toEqual([])
    expect(root.querySelector('.captures-status')?.textContent).toBe(
      '撮影データを読み込めませんでした。',
    )
  })

  it('deletes the capture after confirmation and drops it from the list', async () => {
    const fetch = api([NEWER, OLDER])
    const confirm = vi.fn(() => true)
    await renderCaptures(root, { fetch, confirm })

    item(root, OLDER.id).querySelector('button')!.click()
    await settle()

    expect(confirm).toHaveBeenCalledOnce()
    expect(confirm.mock.calls[0]).toEqual([expect.stringContaining('削除しますか')])
    expect(fetch).toHaveBeenCalledWith(`/api/captures/${OLDER.id}`, {
      method: 'DELETE',
    })
    expect(ids(root)).toEqual([NEWER.id])
    expect(root.querySelector('.captures-status')?.textContent).toContain('1 件')
  })

  it('keeps the capture when the confirmation is cancelled', async () => {
    const fetch = api([OLDER])
    await renderCaptures(root, { fetch, confirm: () => false })

    item(root, OLDER.id).querySelector('button')!.click()
    await settle()

    expect(fetch).toHaveBeenCalledTimes(1)
    expect(ids(root)).toEqual([OLDER.id])
  })

  it('drops a capture that was already deleted elsewhere', async () => {
    await renderCaptures(root, { fetch: api([OLDER], 404), confirm: () => true })

    item(root, OLDER.id).querySelector('button')!.click()
    await settle()

    expect(ids(root)).toEqual([])
  })

  it('keeps the capture and says so when the deletion fails', async () => {
    await renderCaptures(root, { fetch: api([OLDER], 500), confirm: () => true })

    const button = item(root, OLDER.id).querySelector('button')!
    button.click()
    await settle()

    expect(ids(root)).toEqual([OLDER.id])
    expect(button.disabled).toBe(false)
    expect(root.querySelector('.captures-status')?.textContent).toContain(
      '削除できませんでした',
    )
  })
})
