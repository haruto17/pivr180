<script lang="ts">
  import { onMount } from 'svelte'
  import type { WebGLRenderer } from 'three'
  import { createRenderer, createStereoScene, loadTexture, type StereoScene } from './stereo'

  let { src }: { src: string } = $props()

  let canvas: HTMLCanvasElement
  let renderer: WebGLRenderer | undefined
  let xrSupported = $state<boolean | undefined>(undefined)
  let error = $state('')

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

  onMount(() => {
    let stereo: StereoScene | undefined
    let destroyed = false
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

    loadTexture(src).then(
      (texture) => {
        if (destroyed) {
          texture.dispose()
          return
        }
        const s = createStereoScene(texture, window.innerWidth / window.innerHeight)
        stereo = s
        r.setAnimationLoop(() => {
          if (!r.xr.isPresenting) {
            s.camera.aspect = window.innerWidth / window.innerHeight
            s.camera.updateProjectionMatrix()
          }
          r.render(s.scene, s.camera)
        })
      },
      () => {
        error = `写真を読み込めませんでした: ${src}`
      },
    )

    if (navigator.xr) {
      navigator.xr.isSessionSupported('immersive-vr').then(
        (supported) => (xrSupported = supported),
        () => (xrSupported = false),
      )
    } else {
      xrSupported = false
    }

    return () => {
      destroyed = true
      window.removeEventListener('resize', resize)
      r.xr.removeEventListener('sessionend', resetPreviewCamera)
      r.setAnimationLoop(null)
      void r.xr.getSession()?.end()
      stereo?.dispose()
      r.dispose()
      renderer = undefined
    }
  })
</script>

<canvas bind:this={canvas}></canvas>
<div class="overlay">
  {#if xrSupported === true}
    <button type="button" onclick={enterVR}>VR で見る</button>
  {:else if xrSupported === false}
    <p>このブラウザは WebXR（immersive-vr）に対応していません。</p>
  {/if}
  {#if error}
    <p role="alert">{error}</p>
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
