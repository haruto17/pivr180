<script lang="ts">
  import { onMount } from "svelte";
  import {
    getCapturePreview,
    type CapturePreview,
    type Side,
  } from "$lib/captures";
  import {
    clearCaptureCorrection,
    getCaptureCorrection,
    setCaptureCorrection,
    setDeviceCorrection,
    type CaptureCorrection,
    type ImageCircle,
    type StereoCorrection,
  } from "$lib/correction";
  import { sourceCoord } from "$lib/equirectPreview";
  import EquirectCanvas from "$lib/EquirectCanvas.svelte";

  let { id, onclose }: { id: string; onclose?: () => void } = $props();

  type Size = { width: number; height: number };

  const DEFAULT_SIZE: Size = { width: 4056, height: 3040 };
  const sides: { side: Side; label: string }[] = [
    { side: "left", label: "左" },
    { side: "right", label: "右" },
  ];
  const fields: {
    key: keyof ImageCircle;
    label: string;
    min: (size: Size) => number;
    max: (size: Size) => number;
    step: number;
  }[] = [
    {
      key: "center_x_px",
      label: "中心 x",
      min: () => 0,
      max: (size) => size.width,
      step: 0.5,
    },
    {
      key: "center_y_px",
      label: "中心 y",
      min: () => 0,
      max: (size) => size.height,
      step: 0.5,
    },
    {
      key: "radius_px",
      label: "半径",
      min: () => 1,
      max: (size) => Math.max(size.width, size.height),
      step: 0.5,
    },
    {
      key: "rotation_deg",
      label: "回転",
      min: () => -179.9,
      max: () => 180,
      step: 0.1,
    },
  ];

  let values = $state<StereoCorrection>();
  let overridden = $state<CaptureCorrection["overridden"]>();
  let previews = $state<Partial<Record<Side, CapturePreview>>>({});
  let previewErrors = $state<Partial<Record<Side, string>>>({});
  let loadError = $state("");
  let error = $state("");
  let message = $state("");
  let busy = $state(false);

  function apply(correction: CaptureCorrection) {
    values = { left: correction.left, right: correction.right };
    overridden = correction.overridden;
  }

  onMount(() => {
    getCaptureCorrection(id).then(apply, (e) => (loadError = String(e)));
    for (const { side } of sides) {
      getCapturePreview(id, side).then(
        (preview) => (previews[side] = preview),
        (e) => (previewErrors[side] = String(e)),
      );
    }
  });

  async function run(action: () => Promise<unknown>, done: string) {
    error = "";
    message = "";
    busy = true;
    try {
      await action();
      message = done;
    } catch (e) {
      error = String(e);
    } finally {
      busy = false;
    }
  }

  function current(): StereoCorrection {
    return $state.snapshot(values!);
  }

  function saveCapture() {
    return run(
      async () => apply(await setCaptureCorrection(id, current())),
      "この撮影に保存しました",
    );
  }

  function saveDevice() {
    return run(
      () => setDeviceCorrection(current()),
      "既定値として保存しました",
    );
  }

  function reset() {
    return run(
      async () => apply(await clearCaptureCorrection(id)),
      "既定値に戻しました",
    );
  }
</script>

<section>
  <h3>補正: {id}</h3>
  <button type="button" onclick={() => onclose?.()}>閉じる</button>
  {#if loadError}
    <p role="alert">{loadError}</p>
  {:else if values && overridden}
    <div class="sides">
      {#each sides as { side, label } (side)}
        {@const preview = previews[side]}
        {@const size = preview ?? DEFAULT_SIZE}
        {@const circle = values[side]}
        <fieldset>
          <legend>{label}</legend>
          <p>{overridden[side] ? "この撮影で上書き" : "既定値を使用"}</p>
          {#each fields as field (field.key)}
            <div class="field">
              <span>{field.label}</span>
              <input
                type="number"
                step="any"
                aria-label="{label} {field.label}"
                bind:value={values[side][field.key]}
              />
              <input
                type="range"
                min={field.min(size)}
                max={field.max(size)}
                step={field.step}
                aria-label="{label} {field.label} スライダー"
                bind:value={values[side][field.key]}
              />
            </div>
          {/each}
          {#if preview}
            {@const up = sourceCoord(circle, 0, Math.PI / 2)}
            <svg
              viewBox="0 0 {preview.width} {preview.height}"
              role="img"
              aria-label="{label} 魚眼画像"
            >
              <image
                href={preview.dataUrl}
                width={preview.width}
                height={preview.height}
              />
              <circle
                cx={circle.center_x_px}
                cy={circle.center_y_px}
                r={circle.radius_px}
                vector-effect="non-scaling-stroke"
              />
              <line
                x1={circle.center_x_px}
                y1={circle.center_y_px}
                x2={up[0]}
                y2={up[1]}
                vector-effect="non-scaling-stroke"
              />
              <line
                x1={circle.center_x_px - circle.radius_px * 0.05}
                y1={circle.center_y_px}
                x2={circle.center_x_px + circle.radius_px * 0.05}
                y2={circle.center_y_px}
                vector-effect="non-scaling-stroke"
              />
              <line
                x1={circle.center_x_px}
                y1={circle.center_y_px - circle.radius_px * 0.05}
                x2={circle.center_x_px}
                y2={circle.center_y_px + circle.radius_px * 0.05}
                vector-effect="non-scaling-stroke"
              />
            </svg>
            <EquirectCanvas
              image={preview.dataUrl}
              width={preview.width}
              height={preview.height}
              {circle}
              {label}
            />
          {:else if previewErrors[side]}
            <p role="alert">{previewErrors[side]}</p>
          {:else}
            <p>読み込み中…</p>
          {/if}
        </fieldset>
      {/each}
    </div>
    <button type="button" onclick={saveCapture} disabled={busy}>
      この撮影に保存
    </button>
    <button type="button" onclick={saveDevice} disabled={busy}>
      既定値として保存
    </button>
    <button type="button" onclick={reset} disabled={busy}>
      既定値に戻す
    </button>
    {#if message}
      <p>{message}</p>
    {/if}
    {#if error}
      <p role="alert">{error}</p>
    {/if}
  {:else}
    <p>読み込み中…</p>
  {/if}
</section>

<style>
  .sides {
    display: flex;
    gap: 8px;
  }

  fieldset {
    width: 480px;
  }

  .field {
    display: flex;
    gap: 4px;
    align-items: center;
  }

  .field span {
    width: 4em;
  }

  input[type="number"] {
    width: 7em;
  }

  input[type="range"] {
    flex: 1;
  }

  svg {
    display: block;
    width: 100%;
  }

  circle,
  line {
    fill: none;
    stroke: #0f0;
    stroke-width: 2;
  }
</style>
