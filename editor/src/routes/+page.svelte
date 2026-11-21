<script lang="ts">
  import { onMount } from "svelte";
  import {
    getStorageSettings,
    setStorageSettings,
    type StoragePaths,
  } from "$lib/storage";
  import CaptureList from "$lib/CaptureList.svelte";
  import {
    getDeleteAfterImport,
    getImportHost,
    importCaptures,
    setDeleteAfterImport,
    setImportHost,
    type ImportResult,
  } from "$lib/import";

  let storage = $state<StoragePaths>();
  let rootInput = $state("");
  let error = $state("");
  let saving = $state(false);
  let hostInput = $state("");
  let importing = $state(false);
  let deleteAfterImport = $state(false);
  let result = $state<ImportResult>();
  let removeRequested = $state(false);
  let importError = $state("");
  let importCount = $state(0);

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
      deleteAfterImport = await getDeleteAfterImport();
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
    result = undefined;
    importing = true;
    try {
      hostInput = await setImportHost(hostInput);
      removeRequested = await setDeleteAfterImport(deleteAfterImport);
      result = await importCaptures();
      importCount++;
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
      <label>
        <input type="checkbox" bind:checked={deleteAfterImport} />
        取り込み後に Pi から削除する
      </label>
      <button type="submit" disabled={importing}>取り込む</button>
    </form>
    {#if importing}
      <p>取り込み中…</p>
    {/if}
    {#if result}
      <p>{result.imported.length} 件の撮影データを取り込みました</p>
      {#if removeRequested && result.imported.length > 0}
        <p>{result.removed.length} 件を Pi から削除しました</p>
        {#if !result.removeError && result.removed.length < result.imported.length}
          <p>{result.imported.length - result.removed.length} 件は取り込みを確認できなかったため Pi に残しました</p>
        {/if}
      {/if}
      {#if result.removeError}
        <p role="alert">{result.removeError}</p>
      {/if}
    {/if}
    {#if importError}
      <p role="alert">{importError}</p>
    {/if}
  </section>

  <CaptureList capturesDir={storage?.captures} reloadKey={importCount} />
</main>
