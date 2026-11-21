// @vitest-environment jsdom
import { invoke } from "@tauri-apps/api/core";
import { flushSync, mount, tick, unmount } from "svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import Page from "./+page.svelte";

vi.mock("@tauri-apps/api/core", () => ({ invoke: vi.fn() }));

const OLD_ID = "20260101-090000-000";
const NEW_ID = "20260102-090000-000";

type ImportResult = {
  imported: string[];
  removed: string[];
  removeError: string | null;
};

let captures: string[];
let deleteAfterImport: boolean;
let importResult: () => Promise<ImportResult>;
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
    return { imported: [NEW_ID], removed: [], removeError: null };
  };
  deleteAfterImport = false;
  vi.mocked(invoke).mockReset();
  vi.mocked(invoke).mockImplementation(async (cmd: string, args?: unknown) => {
    switch (cmd) {
      case "get_storage_settings":
        return { root: "/r", captures: "/r/captures", exports: "/r/exports" };
      case "get_import_host":
      case "set_import_host":
        return "pivr180.local";
      case "get_delete_after_import":
        return deleteAfterImport;
      case "set_delete_after_import":
        deleteAfterImport = (args as { enabled: boolean }).enabled;
        return deleteAfterImport;
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

function checkbox() {
  return document.querySelector<HTMLInputElement>('input[type="checkbox"]')!;
}

async function remount() {
  unmount(page);
  page = mount(Page, { target: document.body });
  await settle();
}

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

  it("leaves the delete-after-import option off by default", () => {
    expect(document.body.textContent).toContain("取り込み後に Pi から削除する");
    expect(checkbox().checked).toBe(false);
  });

  it("shows the delete-after-import option saved in the settings", async () => {
    deleteAfterImport = true;

    await remount();

    expect(checkbox().checked).toBe(true);
  });

  it("saves the option before importing and does not remove when it is off", async () => {
    await submitImport();

    const cmds = vi.mocked(invoke).mock.calls.map(([cmd]) => cmd);
    expect(invoke).toHaveBeenCalledWith("set_delete_after_import", {
      enabled: false,
    });
    expect(cmds.indexOf("set_delete_after_import")).toBeLessThan(
      cmds.indexOf("import_captures"),
    );
    expect(document.body.textContent).toContain("1 件の撮影データを取り込みました");
    expect(document.body.textContent).not.toContain("Pi から削除しました");
  });

  it("saves the checked option and shows how many captures were removed or kept", async () => {
    importResult = async () => ({
      imported: [NEW_ID, OLD_ID],
      removed: [NEW_ID],
      removeError: null,
    });
    checkbox().click();
    flushSync();

    await submitImport();

    expect(invoke).toHaveBeenCalledWith("set_delete_after_import", {
      enabled: true,
    });
    expect(document.body.textContent).toContain("2 件の撮影データを取り込みました");
    expect(document.body.textContent).toContain("1 件を Pi から削除しました");
    expect(document.body.textContent).toContain(
      "1 件は取り込みを確認できなかったため Pi に残しました",
    );
  });

  it("reports a removal failure with the captures removed before it and still reloads the capture list", async () => {
    importResult = async () => {
      captures = [NEW_ID, OLD_ID];
      return {
        imported: [NEW_ID, OLD_ID],
        removed: [NEW_ID],
        removeError: "Pi からの削除が途中で失敗しました: ssh failed",
      };
    };
    checkbox().click();
    flushSync();
    const before = listCalls();

    await submitImport();

    expect(document.querySelector('[role="alert"]')!.textContent).toBe(
      "Pi からの削除が途中で失敗しました: ssh failed",
    );
    expect(document.body.textContent).toContain("1 件を Pi から削除しました");
    expect(document.body.textContent).not.toContain("Pi に残しました");
    expect(listCalls()).toBeGreaterThan(before);
  });
});
