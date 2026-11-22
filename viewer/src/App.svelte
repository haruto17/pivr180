<script lang="ts">
  import { onMount } from 'svelte'
  import Gallery from './Gallery.svelte'
  import StereoView from './StereoView.svelte'
  import { fetchPhotos, type Photo } from './photos'

  let photos = $state<Photo[] | undefined>(undefined)
  let selected = $state<number | null>(null)
  let error = $state('')

  function step(delta: number) {
    if (!photos || selected === null) return
    selected = (selected + delta + photos.length) % photos.length
  }

  onMount(() => {
    fetchPhotos().then(
      (list) => (photos = list),
      (e) => (error = e instanceof Error ? e.message : String(e)),
    )
  })
</script>

<main>
  {#if photos && selected !== null}
    <StereoView
      src={photos[selected].url}
      onprevious={() => step(-1)}
      onnext={() => step(1)}
      onback={() => (selected = null)}
    />
    <button type="button" class="back" onclick={() => (selected = null)}>一覧に戻る</button>
  {:else}
    <h1>pivr180 viewer</h1>
    {#if error}
      <p role="alert">{error}</p>
    {:else if photos}
      <Gallery {photos} onselect={(index) => (selected = index)} />
    {:else}
      <p>写真一覧を読み込んでいます…</p>
    {/if}
  {/if}
</main>

<style>
  .back {
    position: fixed;
    top: 1rem;
    left: 1rem;
    z-index: 1;
  }
</style>
