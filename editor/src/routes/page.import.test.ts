// @vitest-environment jsdom
import { invoke } from "@tauri-apps/api/core";
import { flushSync, mount, tick, unmount } from "svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import Page from "./+page.svelte";

vi.mock("@tauri-apps/api/core", () => ({ invoke: vi.fn() }));

const OLD_ID = "20260101-090000-000";
const NEW_ID = "20260102-090000-000";

let captures: string[];
let importResult: () => Promise<string[]>;
let page: ReturnType<typeof mount>;

function settle() {
  return new Promise((resolve) => setTimeout(resolve)).then(tick);
}

function listCalls() {
  return vi.mocked(invoke).mock.calls.filter(([cmd]) => cmd === "list_captures")
    .length;
}

async function submitImport() {
  const button = [...document.querySelectorAll("button")].find(
    (b) => b.textContent === "取り込む",
  );
  button!.closest("form")!.requestSubmit();
  flushSync();
  await settle();
}

beforeEach(async () => {
  captures = [OLD_ID];
  importResult = async () => {
    captures = [NEW_ID, OLD_ID];
    return [`${NEW_ID}/left.jpg`, `${NEW_ID}/right.jpg`];
  };
  vi.mocked(invoke).mockReset();
  vi.mocked(invoke).mockImplementation(async (cmd: string) => {
    switch (cmd) {
      case "get_storage_settings":
        return { root: "/r", captures: "/r/captures", exports: "/r/exports" };
      case "get_import_host":
      case "set_import_host":
        return "pivr180.local";
      case "list_captures":
        return [...captures];
      case "capture_thumbnail":
        return "data:image/jpeg;base64,";
      case "import_captures":
        return importResult();
    }
  });
  page = mount(Page, { target: document.body });
  await settle();
});

afterEach(() => {
  unmount(page);
});

describe("+page.svelte import", () => {
  it("reloads the capture list after the import succeeds", async () => {
    const before = listCalls();

    await submitImport();

    expect(listCalls()).toBeGreaterThan(before);
    expect(document.body.textContent).toContain(NEW_ID);
  });

  it("keeps the capture list as is when the import fails", async () => {
    importResult = () => Promise.reject("rsync failed");
    const before = listCalls();

    await submitImport();

    expect(listCalls()).toBe(before);
    expect(document.body.textContent).toContain("rsync failed");
    expect(document.body.textContent).not.toContain(NEW_ID);
  });
});
