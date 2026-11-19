<script lang="ts">
  import { untrack } from "svelte";
  import { listCaptures } from "$lib/captures";
  import CaptureItem from "$lib/CaptureItem.svelte";

  let { capturesDir }: { capturesDir?: string } = $props();

  let ids = $state<string[]>();
  let error = $state("");
  let loading = $state(false);
  let latestRequest = 0;

  async function load() {
    const request = ++latestRequest;
    error = "";
    loading = true;
    try {
      const result = await listCaptures();
      if (request === latestRequest) ids = result;
    } catch (e) {
      if (request === latestRequest) {
        ids = undefined;
        error = String(e);
      }
    } finally {
      if (request === latestRequest) loading = false;
    }
  }

  $effect(() => {
    void capturesDir;
    untrack(load);
  });
</script>

<section>
  <h2>撮影一覧</h2>
  <button type="button" onclick={() => load()} disabled={loading}>
    再読み込み
  </button>
  {#if error}
    <p role="alert">{error}</p>
  {:else if ids?.length === 0}
    <p>撮影がありません</p>
  {:else if ids}
    <ul>
      {#each ids as id (id)}
        <CaptureItem {id} />
      {/each}
    </ul>
  {/if}
</section>

<style>
  ul {
    list-style: none;
    padding: 0;
  }
</style>
