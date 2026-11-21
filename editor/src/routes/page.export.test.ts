// @vitest-environment jsdom
import { invoke } from "@tauri-apps/api/core";
import { flushSync, mount, tick, unmount } from "svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import Page from "./+page.svelte";

vi.mock("@tauri-apps/api/core", () => ({ invoke: vi.fn() }));

const ID = "20260101-090000-000";

let eyeSize: number;
let setEyeSize: (size: number) => Promise<number>;
let page: ReturnType<typeof mount>;

function settle() {
  return new Promise((resolve) => setTimeout(resolve)).then(tick);
}

function eyeSizeInput() {
  return document.querySelector<HTMLInputElement>('input[type="number"]')!;
}

function exportSection() {
  return [...document.querySelectorAll("section")].find(
    (s) => s.querySelector("h2")?.textContent === "書き出し",
  )!;
}

async function submitEyeSize(value: string) {
  eyeSizeInput().value = value;
  eyeSizeInput().dispatchEvent(new Event("input"));
  flushSync();
  exportSection().querySelector("form")!.requestSubmit();
  flushSync();
  await settle();
}

beforeEach(async () => {
  eyeSize = 2880;
  setEyeSize = async (size) => (eyeSize = size);
  vi.mocked(invoke).mockReset();
  vi.mocked(invoke).mockImplementation(async (cmd: string, args?: unknown) => {
    switch (cmd) {
      case "get_storage_settings":
        return { root: "/r", captures: "/r/captures", exports: "/r/exports" };
      case "get_import_host":
        return "pivr180.local";
      case "get_delete_after_import":
        return false;
      case "get_export_eye_size":
        return eyeSize;
      case "set_export_eye_size":
        return setEyeSize((args as { size: number }).size);
      case "list_captures":
        return [ID];
      case "capture_thumbnail":
        return "data:image/jpeg;base64,";
      case "export_capture":
        return `/r/exports/${(args as { id: string }).id}_180_LR.jpg`;
    }
  });
  page = mount(Page, { target: document.body });
  await settle();
});

afterEach(() => {
  unmount(page);
});

describe("+page.svelte export", () => {
  it("shows the per-eye size saved in the settings", () => {
    expect(eyeSizeInput().value).toBe("2880");
  });

  it("saves the changed per-eye size", async () => {
    await submitEyeSize("2048");

    expect(invoke).toHaveBeenCalledWith("set_export_eye_size", { size: 2048 });
    expect(eyeSizeInput().value).toBe("2048");
    expect(exportSection().querySelector('[role="alert"]')).toBeNull();
  });

  it("does not send a per-eye size outside 256 to 8192", async () => {
    await submitEyeSize("255");
    await submitEyeSize("8193");
    await submitEyeSize("2880.5");

    expect(invoke).not.toHaveBeenCalledWith(
      "set_export_eye_size",
      expect.anything(),
    );
  });

  it("shows the error when saving the per-eye size fails", async () => {
    setEyeSize = () => Promise.reject("Permission denied (os error 13)");

    await submitEyeSize("4096");

    expect(
      exportSection().querySelector('[role="alert"]')!.textContent,
    ).toBe("Permission denied (os error 13)");
  });

  it("exports a capture from its button in the capture list", async () => {
    const button = [...document.querySelectorAll("li button")].find(
      (b) => b.textContent === "書き出し",
    ) as HTMLButtonElement;

    button.click();
    flushSync();
    await settle();

    expect(invoke).toHaveBeenCalledWith("export_capture", { id: ID });
    expect(document.body.textContent).toContain(
      `/r/exports/${ID}_180_LR.jpg に書き出しました`,
    );
  });
});
