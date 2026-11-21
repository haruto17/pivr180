<script lang="ts">
  import { getCaptureThumbnail, type Side } from "$lib/captures";
  import ExportButton from "$lib/ExportButton.svelte";

  let { id, oncorrect }: { id: string; oncorrect?: () => void } = $props();

  const sides: { side: Side; label: string }[] = [
    { side: "left", label: "左" },
    { side: "right", label: "右" },
  ];
  let thumbnails = $state<Partial<Record<Side, string>>>({});
  let errors = $state<Partial<Record<Side, string>>>({});

  function load() {
    for (const { side } of sides) {
      getCaptureThumbnail(id, side).then(
        (url) => (thumbnails[side] = url),
        (e) => (errors[side] = String(e)),
      );
    }
  }

  function loadWhenVisible(node: HTMLElement) {
    if (typeof IntersectionObserver === "undefined") {
      load();
      return;
    }
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting)) {
        observer.disconnect();
        load();
      }
    });
    observer.observe(node);
    return () => observer.disconnect();
  }
</script>

<li {@attach loadWhenVisible}>
  <h3>{id}</h3>
  <div class="pair">
    {#each sides as { side, label } (side)}
      <figure>
        {#if thumbnails[side]}
          <img src={thumbnails[side]} alt="{id} {label}" />
        {:else if errors[side]}
          <p role="alert">{errors[side]}</p>
        {:else}
          <p>読み込み中…</p>
        {/if}
        <figcaption>{label}</figcaption>
      </figure>
    {/each}
  </div>
  <button type="button" onclick={() => oncorrect?.()}>補正</button>
  <ExportButton {id} />
</li>

<style>
  .pair {
    display: flex;
    gap: 8px;
  }

  figure {
    margin: 0;
    width: 240px;
  }

  img {
    width: 100%;
  }
</style>
