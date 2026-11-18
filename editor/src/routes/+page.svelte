<script lang="ts">
  import { onMount } from "svelte";
  import {
    getStorageSettings,
    setStorageSettings,
    type StoragePaths,
  } from "$lib/storage";

  let storage = $state<StoragePaths>();
  let rootInput = $state("");
  let error = $state("");

  onMount(async () => {
    try {
      storage = await getStorageSettings();
      rootInput = storage.root;
    } catch (e) {
      error = String(e);
    }
  });

  async function saveRoot(event: SubmitEvent) {
    event.preventDefault();
    error = "";
    try {
      storage = await setStorageSettings(rootInput);
      rootInput = storage.root;
    } catch (e) {
      error = String(e);
    }
  }
</script>

<main>
  <h1>pivr180 editor</h1>

  <section>
    <h2>保存先</h2>
    {#if storage}
      <dl>
        <dt>保存先</dt>
        <dd>{storage.root}</dd>
        <dt>captures</dt>
        <dd>{storage.captures}</dd>
        <dt>exports</dt>
        <dd>{storage.exports}</dd>
      </dl>
    {/if}
    <form onsubmit={saveRoot}>
      <input bind:value={rootInput} aria-label="保存先" />
      <button type="submit">保存</button>
    </form>
    {#if error}
      <p role="alert">{error}</p>
    {/if}
  </section>
</main>
