<script lang="ts">
  import { untrack } from "svelte";
  import { listCaptures } from "$lib/captures";
  import CaptureItem from "$lib/CaptureItem.svelte";
  import CorrectionEditor from "$lib/CorrectionEditor.svelte";

  let { capturesDir, reloadKey }: { capturesDir?: string; reloadKey?: number } =
    $props();

  let ids = $state<string[]>();
  let error = $state("");
  let loading = $state(false);
  let generation = $state(0);
  let editing = $state<string>();
  let latestRequest = 0;
  let editingDir: string | undefined;

  async function load() {
    const request = ++latestRequest;
    error = "";
    loading = true;
    try {
      const result = await listCaptures();
      if (request === latestRequest) {
        ids = result;
        generation++;
      }
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
    void reloadKey;
    untrack(load);
  });

  $effect(() => {
    if (capturesDir !== editingDir) {
      editingDir = capturesDir;
      editing = undefined;
    }
  });
</script>

<section>
  <h2>撮影一覧</h2>
  <button type="button" onclick={() => load()} disabled={loading}>
    再読み込み
  </button>
  {#if editing}
    {#key editing}
      <CorrectionEditor id={editing} onclose={() => (editing = undefined)} />
    {/key}
  {/if}
  {#if error}
    <p role="alert">{error}</p>
  {:else if ids?.length === 0}
    <p>撮影がありません</p>
  {:else if ids}
    <ul>
      {#key generation}
        {#each ids as id (id)}
          <CaptureItem {id} oncorrect={() => (editing = id)} />
        {/each}
      {/key}
    </ul>
  {/if}
</section>

<style>
  ul {
    list-style: none;
    padding: 0;
  }
</style>
