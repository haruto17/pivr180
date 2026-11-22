<script lang="ts">
  import { onMount } from 'svelte'
  import type { Texture, WebGLRenderer } from 'three'
  import { createControllerReader, type ControllerAction } from './controller'
  import { createRenderer, createStereoScene, loadTexture, type StereoScene } from './stereo'

  let {
    src,
    onprevious,
    onnext,
    onback,
  }: { src: string; onprevious?: () => void; onnext?: () => void; onback?: () => void } = $props()

  let canvas: HTMLCanvasElement
  let renderer: WebGLRenderer | undefined
  let stereo: StereoScene | undefined
  let swapped = $state(false)
  let xrSupported = $state<boolean | undefined>(undefined)
  let error = $state('')
  let loadError = $state('')
  let loadId = 0

  function resize() {
    if (!renderer || renderer.xr.isPresenting) return
    renderer.setSize(window.innerWidth, window.innerHeight)
  }

  async function enterVR() {
    if (!renderer || !navigator.xr) return
    let session: XRSession | undefined
    try {
      session = await navigator.xr.requestSession('immersive-vr')
      await renderer.xr.setSession(session)
    } catch (e) {
      session?.end().catch(() => {})
      error = `VR を開始できませんでした: ${e instanceof Error ? e.message : String(e)}`
    }
  }

  function toggleSwap() {
    swapped = !swapped
    stereo?.setSwapped(swapped)
  }

  function handleController(action: ControllerAction) {
    ;({ previous: onprevious, next: onnext, back: onback })[action]?.()
  }

  function startRendering(r: WebGLRenderer, texture: Texture) {
    const s = createStereoScene(texture, window.innerWidth / window.innerHeight)
    s.setSwapped(swapped)
    stereo = s
    const readController = createControllerReader()
    r.setAnimationLoop(() => {
      if (r.xr.isPresenting) {
        const session = r.xr.getSession()
        if (session) for (const action of readController(session.inputSources)) handleController(action)
      } else {
        s.camera.aspect = window.innerWidth / window.innerHeight
        s.camera.updateProjectionMatrix()
      }
      r.render(s.scene, s.camera)
    })
  }

  function load(url: string) {
    const id = ++loadId
    loadTexture(url).then(
      (texture) => {
        if (id !== loadId || !renderer) {
          texture.dispose()
          return
        }
        loadError = ''
        if (stereo) stereo.setTexture(texture)
        else startRendering(renderer, texture)
      },
      () => {
        if (id === loadId) loadError = `写真を読み込めませんでした: ${url}`
      },
    )
  }

  onMount(() => {
    const r = createRenderer(canvas)
    renderer = r
    // 'local-floor' would offset the eye height from the hemisphere center and break the infinite-distance look.
    r.xr.setReferenceSpaceType('local')
    r.setPixelRatio(window.devicePixelRatio)
    resize()
    window.addEventListener('resize', resize)
    const resetPreviewCamera = () => {
      if (!stereo) return
      stereo.camera.position.set(0, 0, 0)
      stereo.camera.quaternion.identity()
      stereo.camera.aspect = window.innerWidth / window.innerHeight
      stereo.camera.updateProjectionMatrix()
    }
    r.xr.addEventListener('sessionend', resetPreviewCamera)

    if (navigator.xr) {
      navigator.xr.isSessionSupported('immersive-vr').then(
        (supported) => (xrSupported = supported),
        () => (xrSupported = false),
      )
    } else {
      xrSupported = false
    }

    return () => {
      renderer = undefined
      window.removeEventListener('resize', resize)
      r.xr.removeEventListener('sessionend', resetPreviewCamera)
      r.setAnimationLoop(null)
      void r.xr.getSession()?.end()
      stereo?.dispose()
      r.dispose()
    }
  })

  $effect(() => load(src))
</script>

<canvas bind:this={canvas}></canvas>
<div class="overlay">
  {#if xrSupported === true}
    <button type="button" onclick={enterVR}>VR で見る</button>
  {:else if xrSupported === false}
    <p>このブラウザは WebXR（immersive-vr）に対応していません。</p>
  {/if}
  <button type="button" aria-pressed={swapped} onclick={toggleSwap}>左右を入れ替える</button>
  {#if error}
    <p role="alert">{error}</p>
  {/if}
  {#if loadError}
    <p role="alert">{loadError}</p>
  {/if}
</div>

<style>
  canvas {
    position: fixed;
    inset: 0;
    display: block;
  }
  .overlay {
    position: fixed;
    bottom: 1rem;
    left: 0;
    right: 0;
    text-align: center;
  }
</style>
