// @vitest-environment jsdom
import { flushSync, mount, tick, unmount } from 'svelte'
import { PerspectiveCamera, Quaternion, Texture, type Mesh, type Scene } from 'three'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { reactiveProps } from './reactive-props.svelte'
import StereoView from './StereoView.svelte'

const renderer = vi.hoisted(() => ({
  setSession: vi.fn(async () => {}),
  setAnimationLoop: vi.fn(),
  dispose: vi.fn(),
  render: vi.fn(),
  xrListeners: new Map<string, () => void>(),
  create: vi.fn(),
}))
const loadTexture = vi.hoisted(() => vi.fn())

vi.mock('./stereo', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./stereo')>()),
  createRenderer: () => (renderer.create(), {
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
  loadTexture,
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

function swapButton() {
  return Array.from(document.querySelectorAll('button')).find((b) => b.textContent === '左右を入れ替える')
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((r) => (resolve = r))
  return { promise, resolve }
}

async function settle() {
  await tick()
  await tick()
  flushSync()
}

function renderedScene() {
  const loop = renderer.setAnimationLoop.mock.calls.at(-1)![0] as () => void
  loop()
  const scene = (renderer.render.mock.calls.at(-1) as unknown[])[0] as Scene
  const [left, right] = scene.children as Mesh[]
  return { left, right }
}

beforeEach(() => {
  vi.clearAllMocks()
  loadTexture.mockReset()
  loadTexture.mockImplementation(async () => new Texture())
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

  it('shows the left half to the right eye and the right half to the left eye when 「左右を入れ替える」 is pressed', async () => {
    stubXr(true)
    await render()

    swapButton()!.click()
    flushSync()

    const { left, right } = renderedScene()
    expect(left.layers.mask).toBe(1 << 2)
    expect(right.layers.mask).toBe(1 << 1)
    expect(swapButton()!.getAttribute('aria-pressed')).toBe('true')
  })

  it('restores each half to its own eye when 「左右を入れ替える」 is pressed again', async () => {
    stubXr(true)
    await render()

    swapButton()!.click()
    swapButton()!.click()
    flushSync()

    const { left, right } = renderedScene()
    expect(left.layers.mask).toBe(1 << 1)
    expect(right.layers.mask).toBe(1 << 2)
    expect(swapButton()!.getAttribute('aria-pressed')).toBe('false')
  })

  it('keeps the eyes swapped when 「左右を入れ替える」 was pressed before the photo loaded', async () => {
    stubXr(true)
    component = mount(StereoView, { target: document.body, props: { src: '/photo.jpg' } })
    flushSync()

    swapButton()!.click()
    await tick()
    await tick()
    flushSync()

    const { left, right } = renderedScene()
    expect(left.layers.mask).toBe(1 << 2)
    expect(right.layers.mask).toBe(1 << 1)
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

  it('shows the new photo without recreating the renderer when the photo changes', async () => {
    stubXr(true)
    const props = reactiveProps({ src: '/first.jpg' })
    component = mount(StereoView, { target: document.body, props })
    await settle()
    const next = new Texture()
    loadTexture.mockResolvedValueOnce(next)

    props.src = '/second.jpg'
    await settle()

    expect(loadTexture).toHaveBeenLastCalledWith('/second.jpg')
    expect(renderedScene().left.material).toHaveProperty('map', next)
    expect(renderer.create).toHaveBeenCalledTimes(1)
    expect(renderer.dispose).not.toHaveBeenCalled()
  })

  it('shows only the last chosen photo when an earlier one finishes loading later', async () => {
    stubXr(true)
    const props = reactiveProps({ src: '/first.jpg' })
    component = mount(StereoView, { target: document.body, props })
    await settle()
    const slow = deferred<Texture>()
    const late = new Texture()
    const last = new Texture()
    loadTexture.mockReturnValueOnce(slow.promise).mockResolvedValueOnce(last)

    props.src = '/second.jpg'
    flushSync()
    props.src = '/third.jpg'
    await settle()
    slow.resolve(late)
    await settle()

    expect(renderedScene().left.material).toHaveProperty('map', last)
  })

  it('keeps the eyes swapped when the photo changes', async () => {
    stubXr(true)
    const props = reactiveProps({ src: '/first.jpg' })
    component = mount(StereoView, { target: document.body, props })
    await settle()
    swapButton()!.click()
    flushSync()

    props.src = '/second.jpg'
    await settle()

    const { left, right } = renderedScene()
    expect(left.layers.mask).toBe(1 << 2)
    expect(right.layers.mask).toBe(1 << 1)
    expect(swapButton()!.getAttribute('aria-pressed')).toBe('true')
  })

  it('shows which photo could not be loaded', async () => {
    stubXr(true)
    loadTexture.mockRejectedValueOnce(new Error('404'))
    await render()

    expect(document.querySelector('[role="alert"]')?.textContent).toContain('/photo.jpg')
  })
})
