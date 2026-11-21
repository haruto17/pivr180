<script lang="ts">
  import { exportCapture } from "$lib/export";

  let { id }: { id: string } = $props();

  let exporting = $state(false);
  let output = $state("");
  let error = $state("");

  async function run() {
    output = "";
    error = "";
    exporting = true;
    try {
      output = await exportCapture(id);
    } catch (e) {
      error = String(e);
    } finally {
      exporting = false;
    }
  }
</script>

<div>
  <button type="button" onclick={run} disabled={exporting}>書き出し</button>
  {#if exporting}
    <p>書き出し中…</p>
  {/if}
  {#if output}
    <p>{output} に書き出しました</p>
  {/if}
  {#if error}
    <p role="alert">{error}</p>
  {/if}
</div>
