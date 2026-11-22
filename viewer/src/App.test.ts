// @vitest-environment jsdom
import { flushSync, mount, unmount } from 'svelte'
import { Texture } from 'three'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App.svelte'

const loadTexture = vi.hoisted(() => vi.fn())

vi.mock('./stereo', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./stereo')>()),
  createRenderer: () => ({
    xr: {
      isPresenting: false,
      setReferenceSpaceType: () => {},
      getSession: () => null,
      addEventListener: () => {},
      removeEventListener: () => {},
    },
    setPixelRatio: () => {},
    setSize: () => {},
    setAnimationLoop: () => {},
    render: () => {},
    dispose: () => {},
  }),
  loadTexture,
}))

const photos = [
  { name: '20260102-090000-000_180_LR.jpg', url: '/photos/20260102-090000-000_180_LR.jpg' },
  { name: '20260101-090000-000_180_LR.jpg', url: '/photos/20260101-090000-000_180_LR.jpg' },
]
let component: ReturnType<typeof mount> | undefined

function serve(response: Response) {
  const fetchFn = vi.fn(async () => response)
  vi.stubGlobal('fetch', fetchFn)
  return fetchFn
}

async function render() {
  component = mount(App, { target: document.body })
  await vi.waitFor(() => expect(document.body.textContent).not.toContain('読み込んでいます'))
}

function button(text: string) {
  return Array.from(document.querySelectorAll('button')).find((b) => b.textContent?.includes(text))
}

beforeEach(() => {
  loadTexture.mockReset()
  loadTexture.mockResolvedValue(new Texture())
})

afterEach(() => {
  if (component) unmount(component)
  component = undefined
  vi.unstubAllGlobals()
  document.body.innerHTML = ''
})

describe('App', () => {
  it('lists the photos from the photo list API', async () => {
    const fetchFn = serve(Response.json(photos))
    await render()

    expect(fetchFn).toHaveBeenCalledWith('/api/photos')
    expect(Array.from(document.querySelectorAll('img')).map((img) => img.getAttribute('src'))).toEqual(
      photos.map((p) => p.url),
    )
    expect(document.querySelector('canvas')).toBeNull()
  })

  it('shows the chosen photo in stereo', async () => {
    serve(Response.json(photos))
    await render()

    button(photos[1].name)!.click()
    flushSync()

    expect(document.querySelector('canvas')).not.toBeNull()
    expect(loadTexture).toHaveBeenCalledWith(photos[1].url)
    expect(document.querySelector('img')).toBeNull()
  })

  it('goes back to the list from the stereo view', async () => {
    serve(Response.json(photos))
    await render()
    button(photos[0].name)!.click()
    flushSync()

    button('一覧に戻る')!.click()
    flushSync()

    expect(document.querySelector('canvas')).toBeNull()
    expect(document.querySelectorAll('img')).toHaveLength(photos.length)
  })

  it('shows why the photo list could not be loaded', async () => {
    serve(new Response('', { status: 500 }))
    await render()

    expect(document.querySelector('[role="alert"]')?.textContent).toContain('HTTP 500')
  })
})
