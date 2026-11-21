<script lang="ts">
  import StereoView from './StereoView.svelte'

  const photo = typeof location === 'undefined' ? null : new URLSearchParams(location.search).get('photo')
</script>

<main>
  <h1>pivr180 viewer</h1>
  {#if photo}
    <StereoView src={photo} />
  {:else}
    <p>表示する写真の URL を <code>?photo=</code> で指定してください。</p>
  {/if}
</main>
