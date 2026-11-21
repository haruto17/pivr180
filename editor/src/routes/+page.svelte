<script lang="ts">
  import { onMount } from "svelte";
  import {
    getStorageSettings,
    setStorageSettings,
    type StoragePaths,
  } from "$lib/storage";
  import CaptureList from "$lib/CaptureList.svelte";
  import { getImportHost, importCaptures, setImportHost } from "$lib/import";

  let storage = $state<StoragePaths>();
  let rootInput = $state("");
  let error = $state("");
  let saving = $state(false);
  let hostInput = $state("");
  let importing = $state(false);
  let imported = $state<string[]>();
  let importError = $state("");

  onMount(async () => {
    try {
      storage = await getStorageSettings();
      rootInput = storage.root;
    } catch (e) {
      error = String(e);
    }
  });

  onMount(async () => {
    try {
      hostInput = await getImportHost();
    } catch (e) {
      importError = String(e);
    }
  });

  async function saveRoot(event: SubmitEvent) {
    event.preventDefault();
    error = "";
    saving = true;
    try {
      storage = await setStorageSettings(rootInput);
      rootInput = storage.root;
    } catch (e) {
      error = String(e);
    } finally {
      saving = false;
    }
  }

  async function runImport(event: SubmitEvent) {
    event.preventDefault();
    importError = "";
    imported = undefined;
    importing = true;
    try {
      hostInput = await setImportHost(hostInput);
      imported = await importCaptures();
    } catch (e) {
      importError = String(e);
    } finally {
      importing = false;
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
      <button type="submit" disabled={saving}>保存</button>
    </form>
    {#if error}
      <p role="alert">{error}</p>
    {/if}
  </section>

  <section>
    <h2>取り込み</h2>
    <form onsubmit={runImport}>
      <input bind:value={hostInput} aria-label="接続先" />
      <button type="submit" disabled={importing}>取り込む</button>
    </form>
    {#if importing}
      <p>取り込み中…</p>
    {/if}
    {#if imported}
      <p>{imported.length} 件の撮影データを取り込みました</p>
    {/if}
    {#if importError}
      <p role="alert">{importError}</p>
    {/if}
  </section>

  <CaptureList capturesDir={storage?.captures} />
</main>
