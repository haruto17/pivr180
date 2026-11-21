// @vitest-environment jsdom
import { invoke } from "@tauri-apps/api/core";
import { flushSync, mount, tick, unmount } from "svelte";
import { SvelteMap } from "svelte/reactivity";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import CaptureList from "./CaptureList.svelte";

vi.mock("@tauri-apps/api/core", () => ({ invoke: vi.fn() }));

const OLD_ID = "20260101-090000-000";
const NEW_ID = "20260102-090000-000";
const circle = {
  center_x_px: 2028,
  center_y_px: 1520,
  radius_px: 1469.5,
  rotation_deg: 0,
};

let list: ReturnType<typeof mount>;
let props: SvelteMap<string, string | number>;

function settle() {
  return new Promise((resolve) => setTimeout(resolve)).then(tick);
}

function buttons(text: string) {
  return [...document.querySelectorAll("button")].filter(
    (b) => b.textContent?.trim() === text,
  );
}

async function click(button: HTMLButtonElement) {
  button.click();
  flushSync();
  await settle();
}

function heading() {
  return [...document.querySelectorAll("h3")]
    .map((h) => h.textContent)
    .find((text) => text?.startsWith("補正"));
}

beforeEach(async () => {
  vi.mocked(invoke).mockReset();
  vi.mocked(invoke).mockImplementation(async (cmd: string) => {
    switch (cmd) {
      case "list_captures":
        return [NEW_ID, OLD_ID];
      case "capture_thumbnail":
        return "data:image/jpeg;base64,";
      case "get_capture_correction":
        return {
          left: circle,
          right: circle,
          overridden: { left: false, right: false },
        };
      case "capture_preview":
        return { dataUrl: "data:image/jpeg;base64,", width: 4056, height: 3040 };
    }
  });
  props = new SvelteMap<string, string | number>([
    ["capturesDir", "/old/captures"],
    ["reloadKey", 0],
  ]);
  list = mount(CaptureList, {
    target: document.body,
    props: {
      get capturesDir() {
        return props.get("capturesDir") as string;
      },
      get reloadKey() {
        return props.get("reloadKey") as number;
      },
    },
  });
  await settle();
});

afterEach(() => {
  unmount(list);
});

describe("CaptureList.svelte correction", () => {
  it("opens the correction editor for the capture whose button was pressed", async () => {
    expect(heading()).toBeUndefined();

    await click(buttons("補正")[1]);

    expect(heading()).toBe(`補正: ${OLD_ID}`);
    expect(invoke).toHaveBeenCalledWith("get_capture_correction", {
      id: OLD_ID,
    });
    expect(
      document.body.textContent?.match(
        /WebGL を使えないため、変換プレビューを表示できません/g,
      ),
    ).toHaveLength(2);
  });

  it("switches the editor to another capture and closes it", async () => {
    await click(buttons("補正")[1]);
    await click(buttons("補正")[0]);
    expect(heading()).toBe(`補正: ${NEW_ID}`);

    await click(buttons("閉じる")[0]);

    expect(heading()).toBeUndefined();
  });

  it("keeps the editor open when the list reloads after an import", async () => {
    await click(buttons("補正")[1]);

    props.set("reloadKey", 1);
    flushSync();
    await settle();

    expect(heading()).toBe(`補正: ${OLD_ID}`);
  });

  it("closes the editor when the storage root changes", async () => {
    await click(buttons("補正")[1]);

    props.set("capturesDir", "/new/captures");
    flushSync();
    await settle();

    expect(heading()).toBeUndefined();
  });
});
