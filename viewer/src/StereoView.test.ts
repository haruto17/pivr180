// @vitest-environment jsdom
import { flushSync, mount, tick, unmount } from 'svelte'
import { PerspectiveCamera, Quaternion, Texture } from 'three'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import StereoView from './StereoView.svelte'

const renderer = vi.hoisted(() => ({
  setSession: vi.fn(async () => {}),
  setAnimationLoop: vi.fn(),
  dispose: vi.fn(),
  render: vi.fn(),
  xrListeners: new Map<string, () => void>(),
}))

vi.mock('./stereo', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./stereo')>()),
  createRenderer: () => ({
    xr: {
      isPresenting: false,
      setSession: renderer.setSession,
      setReferenceSpaceType: () => {},
      getSession: () => null,
      addEventListener: (type: string, listener: () => void) => renderer.xrListeners.set(type, listener),
      removeEventListener: (type: string) => renderer.xrListeners.delete(type),
    },
    setPixelRatio: () => {},
    setSize: () => {},
    setAnimationLoop: renderer.setAnimationLoop,
    render: renderer.render,
    dispose: renderer.dispose,
  }),
  loadTexture: async () => new Texture(),
}))

const session = { end: vi.fn(async () => {}) }
let component: ReturnType<typeof mount> | undefined

function stubXr(supported: boolean) {
  const xr = {
    isSessionSupported: vi.fn(async () => supported),
    requestSession: vi.fn(async () => session),
  }
  Object.defineProperty(navigator, 'xr', { value: xr, configurable: true })
  return xr
}

async function render() {
  component = mount(StereoView, { target: document.body, props: { src: '/photo.jpg' } })
  await tick()
  await tick()
  flushSync()
}

function vrButton() {
  return Array.from(document.querySelectorAll('button')).find((b) => b.textContent === 'VR で見る')
}

beforeEach(() => {
  vi.clearAllMocks()
})

afterEach(() => {
  if (component) unmount(component)
  component = undefined
  Reflect.deleteProperty(navigator, 'xr')
  document.body.innerHTML = ''
})

describe('StereoView', () => {
  it('requests an immersive-vr session and hands it to the renderer when 「VR で見る」 is pressed', async () => {
    const xr = stubXr(true)
    await render()

    vrButton()!.click()
    await tick()
    await tick()

    expect(xr.requestSession).toHaveBeenCalledWith('immersive-vr')
    expect(renderer.setSession).toHaveBeenCalledWith(session)
  })

  it('ends the acquired session and shows the error when the renderer cannot start it', async () => {
    stubXr(true)
    renderer.setSession.mockRejectedValueOnce(new Error('layer failed'))
    await render()

    vrButton()!.click()
    await tick()
    await tick()
    flushSync()

    expect(session.end).toHaveBeenCalled()
    expect(document.querySelector('[role="alert"]')?.textContent).toContain('layer failed')
  })

  it('faces the preview camera back to the photo when the VR session ends', async () => {
    stubXr(true)
    await render()
    const loop = renderer.setAnimationLoop.mock.calls.at(-1)![0] as () => void
    loop()
    const camera = (renderer.render.mock.calls.at(-1) as unknown[])[1] as PerspectiveCamera
    camera.position.set(0, 1.6, 0.2)
    camera.rotation.set(0, Math.PI, 0)

    renderer.xrListeners.get('sessionend')!()

    expect(camera.position.toArray()).toEqual([0, 0, 0])
    expect(camera.quaternion.equals(new Quaternion())).toBe(true)
  })

  it('stops listening for VR session end when destroyed', async () => {
    stubXr(true)
    await render()

    unmount(component!)
    component = undefined

    expect(renderer.xrListeners.has('sessionend')).toBe(false)
  })

  it('shows a message instead of the button when immersive-vr is not supported', async () => {
    stubXr(false)
    await render()

    expect(vrButton()).toBeUndefined()
    expect(document.body.textContent).toContain('WebXR（immersive-vr）に対応していません')
  })

  it('shows a message instead of the button when the browser has no WebXR', async () => {
    await render()

    expect(vrButton()).toBeUndefined()
    expect(document.body.textContent).toContain('WebXR（immersive-vr）に対応していません')
  })

  it('renders the photo every frame', async () => {
    stubXr(true)
    await render()

    const loop = renderer.setAnimationLoop.mock.calls.at(-1)![0] as () => void
    loop()

    expect(renderer.render).toHaveBeenCalled()
  })

  it('stops rendering and releases the renderer when destroyed', async () => {
    stubXr(true)
    await render()

    unmount(component!)
    component = undefined

    expect(renderer.setAnimationLoop).toHaveBeenLastCalledWith(null)
    expect(renderer.dispose).toHaveBeenCalled()
  })
})
