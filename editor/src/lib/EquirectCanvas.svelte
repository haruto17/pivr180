<script lang="ts">
  import type { ImageCircle } from "$lib/correction";
  import {
    createEquirectRenderer,
    loadImage,
    type EquirectRenderer,
  } from "$lib/equirectPreview";

  let {
    image,
    width,
    height,
    circle,
    label,
  }: {
    image: string;
    width: number;
    height: number;
    circle: ImageCircle;
    label: string;
  } = $props();

  let renderer = $state.raw<EquirectRenderer | null>();
  let loaded = $state<string>();
  let error = $state("");

  function setup(canvas: HTMLCanvasElement) {
    try {
      renderer = createEquirectRenderer(canvas);
    } catch (e) {
      renderer = null;
      error = String(e);
    }
    return () => renderer?.dispose();
  }

  $effect(() => {
    const target = renderer;
    const url = image;
    if (!target) return;
    let cancelled = false;
    loadImage(url).then(
      (source) => {
        if (cancelled) return;
        target.setImage(source);
        loaded = url;
      },
      (e) => {
        if (!cancelled) error = String(e);
      },
    );
    return () => {
      cancelled = true;
    };
  });

  $effect(() => {
    const { center_x_px, center_y_px, radius_px, rotation_deg } = circle;
    if (!renderer || loaded !== image) return;
    renderer.draw(
      { center_x_px, center_y_px, radius_px, rotation_deg },
      width,
      height,
    );
  });
</script>

<canvas
  {@attach setup}
  width="512"
  height="512"
  aria-label="{label} 正距円筒 180° プレビュー"
  hidden={renderer === null}
></canvas>
{#if error}
  <p role="alert">{error}</p>
{:else if renderer === null}
  <p>WebGL を使えないため、変換プレビューを表示できません</p>
{/if}

<style>
  canvas {
    width: 100%;
    aspect-ratio: 1;
    background: #000;
  }
</style>
