// @vitest-environment jsdom
import { invoke } from "@tauri-apps/api/core";
import { flushSync, mount, tick, unmount } from "svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import ExportButton from "./ExportButton.svelte";

vi.mock("@tauri-apps/api/core", () => ({ invoke: vi.fn() }));

const ID = "20260101-090000-000";
const OUTPUT = `/r/exports/${ID}_180_LR.jpg`;

let button: ReturnType<typeof mount>;

function settle() {
  return new Promise((resolve) => setTimeout(resolve)).then(tick);
}

function exportButton() {
  return document.querySelector("button")!;
}

beforeEach(() => {
  vi.mocked(invoke).mockReset();
  button = mount(ExportButton, { target: document.body, props: { id: ID } });
});

afterEach(() => {
  unmount(button);
});

describe("ExportButton.svelte", () => {
  it("exports the capture and shows the written path", async () => {
    vi.mocked(invoke).mockResolvedValue(OUTPUT);

    exportButton().click();
    flushSync();
    await settle();

    expect(invoke).toHaveBeenCalledWith("export_capture", { id: ID });
    expect(document.body.textContent).toContain(`${OUTPUT} に書き出しました`);
    expect(document.querySelector('[role="alert"]')).toBeNull();
  });

  it("shows the export in progress and disables the button until it finishes", async () => {
    let finish!: (path: string) => void;
    vi.mocked(invoke).mockReturnValue(
      new Promise((resolve) => (finish = resolve)),
    );

    exportButton().click();
    flushSync();

    expect(document.body.textContent).toContain("書き出し中…");
    expect(exportButton().disabled).toBe(true);

    finish(OUTPUT);
    await settle();

    expect(document.body.textContent).not.toContain("書き出し中…");
    expect(exportButton().disabled).toBe(false);
  });

  it("shows the error when the export fails", async () => {
    vi.mocked(invoke).mockRejectedValue("left.jpg: No such file or directory");

    exportButton().click();
    flushSync();
    await settle();

    expect(document.querySelector('[role="alert"]')!.textContent).toBe(
      "left.jpg: No such file or directory",
    );
    expect(document.body.textContent).not.toContain("に書き出しました");
  });

  it("clears the previous error when exporting again succeeds", async () => {
    vi.mocked(invoke).mockRejectedValueOnce("failed");
    exportButton().click();
    flushSync();
    await settle();

    vi.mocked(invoke).mockResolvedValue(OUTPUT);
    exportButton().click();
    flushSync();
    await settle();

    expect(document.querySelector('[role="alert"]')).toBeNull();
    expect(document.body.textContent).toContain(`${OUTPUT} に書き出しました`);
  });
});
