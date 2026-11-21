// @vitest-environment jsdom
import { invoke } from "@tauri-apps/api/core";
import { flushSync, mount, tick, unmount } from "svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import CaptureList from "./CaptureList.svelte";

vi.mock("@tauri-apps/api/core", () => ({ invoke: vi.fn() }));

const ID = "20260101-090000-000";
const IMAGE = "data:image/jpeg;base64,AAAA";

let thumbnail: () => Promise<string>;
let list: ReturnType<typeof mount>;

function settle() {
  return new Promise((resolve) => setTimeout(resolve)).then(tick);
}

beforeEach(async () => {
  thumbnail = () => Promise.reject("thumbnail failed");
  vi.mocked(invoke).mockReset();
  vi.mocked(invoke).mockImplementation(async (cmd: string) => {
    switch (cmd) {
      case "list_captures":
        return [ID];
      case "capture_thumbnail":
        return thumbnail();
    }
  });
  list = mount(CaptureList, { target: document.body, props: {} });
  await settle();
});

afterEach(() => {
  unmount(list);
});

describe("CaptureList.svelte reload", () => {
  it("requests a failed thumbnail again and shows it after reloading", async () => {
    expect(document.body.textContent).toContain("thumbnail failed");

    thumbnail = async () => IMAGE;
    document.querySelector("button")!.click();
    flushSync();
    await settle();

    expect(document.body.textContent).not.toContain("thumbnail failed");
    const images = [...document.querySelectorAll("img")];
    expect(images.map((img) => img.getAttribute("src"))).toEqual([
      IMAGE,
      IMAGE,
    ]);
  });
});
