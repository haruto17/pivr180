// @vitest-environment jsdom
import { flushSync, mount, tick, unmount } from 'svelte'
import { Texture } from 'three'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App.svelte'
import type { ControllerInput } from './controller'

const loadTexture = vi.hoisted(() => vi.fn())
const xr = vi.hoisted(() => ({
  presenting: false,
  inputSources: [] as ControllerInput[],
  loop: undefined as (() => void) | undefined,
  end: vi.fn(async () => {}),
}))

vi.mock('./stereo', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./stereo')>()),
  createRenderer: () => ({
    xr: {
      get isPresenting() {
        return xr.presenting
      },
      setReferenceSpaceType: () => {},
      getSession: () => (xr.presenting ? { inputSources: xr.inputSources, end: xr.end } : null),
      addEventListener: () => {},
      removeEventListener: () => {},
    },
    setPixelRatio: () => {},
    setSize: () => {},
    setAnimationLoop: (loop: (() => void) | null) => (xr.loop = loop ?? undefined),
    render: () => {},
    dispose: () => {},
  }),
  loadTexture,
}))

const photos = [
  { name: '20260102-090000-000_180_LR.jpg', url: '/photos/20260102-090000-000_180_LR.jpg' },
  { name: '20260101-090000-000_180_LR.jpg', url: '/photos/20260101-090000-000_180_LR.jpg' },
  { name: '20251231-090000-000_180_LR.jpg', url: '/photos/20251231-090000-000_180_LR.jpg' },
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

async function openInVR(index: number) {
  serve(Response.json(photos))
  await render()
  button(photos[index].name)!.click()
  flushSync()
  await vi.waitFor(() => expect(xr.loop).toBeDefined())
  xr.presenting = true
}

async function useController(input: { x?: number; back?: boolean }) {
  const buttons = Array.from({ length: 7 }, (_, i) => ({ pressed: i === 5 && !!input.back }))
  xr.inputSources = [{ handedness: 'right', gamepad: { axes: [0, 0, input.x ?? 0, 0], buttons } }]
  xr.loop!()
  await tick()
  flushSync()
}

beforeEach(() => {
  xr.presenting = false
  xr.inputSources = []
  xr.loop = undefined
  xr.end.mockClear()
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

  it('shows the next photo when the thumbstick is pushed right in VR', async () => {
    await openInVR(0)

    await useController({ x: 0.9 })

    expect(loadTexture).toHaveBeenLastCalledWith(photos[1].url)
    expect(xr.end).not.toHaveBeenCalled()
  })

  it('shows the previous photo when the thumbstick is pushed left in VR', async () => {
    await openInVR(1)

    await useController({ x: -0.9 })

    expect(loadTexture).toHaveBeenLastCalledWith(photos[0].url)
    expect(xr.end).not.toHaveBeenCalled()
  })

  it('wraps from the last photo to the first', async () => {
    await openInVR(photos.length - 1)

    await useController({ x: 0.9 })

    expect(loadTexture).toHaveBeenLastCalledWith(photos[0].url)
  })

  it('wraps from the first photo to the last', async () => {
    await openInVR(0)

    await useController({ x: -0.9 })

    expect(loadTexture).toHaveBeenLastCalledWith(photos[photos.length - 1].url)
  })

  it('leaves VR and goes back to the list when B or Y is pressed', async () => {
    await openInVR(0)

    await useController({ back: true })

    expect(xr.end).toHaveBeenCalled()
    expect(document.querySelector('canvas')).toBeNull()
    expect(document.querySelectorAll('img')).toHaveLength(photos.length)
  })
})
