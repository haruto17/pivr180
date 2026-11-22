<script lang="ts">
  import type { Photo } from './photos'

  let { photos, onselect }: { photos: Photo[]; onselect: (index: number) => void } = $props()
</script>

{#if photos.length === 0}
  <p>書き出した写真がありません。</p>
{:else}
  <ul>
    {#each photos as photo, index (photo.url)}
      <li>
        <button type="button" onclick={() => onselect(index)}>
          <span class="thumbnail">
            <img src={photo.url} alt="" loading="lazy" decoding="async" />
          </span>
          <span class="name">{photo.name}</span>
        </button>
      </li>
    {/each}
  </ul>
{/if}

<style>
  ul {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(16rem, 1fr));
    gap: 1rem;
    padding: 0;
    list-style: none;
  }
  button {
    display: block;
    width: 100%;
    padding: 0;
    border: none;
    background: none;
    color: inherit;
    font: inherit;
    text-align: left;
    cursor: pointer;
  }
  .thumbnail {
    display: block;
    aspect-ratio: 1;
    overflow: hidden;
    background: #222;
  }
  .thumbnail img {
    display: block;
    width: 200%;
    height: 100%;
  }
  .name {
    display: block;
    margin-top: 0.25rem;
    overflow-wrap: anywhere;
  }
</style>
