// @vitest-environment jsdom
import { invoke } from "@tauri-apps/api/core";
import { flushSync, mount, tick, unmount } from "svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import CorrectionEditor from "./CorrectionEditor.svelte";
import type { EquirectRenderer } from "./equirectPreview";

vi.mock("@tauri-apps/api/core", () => ({ invoke: vi.fn() }));

const renderer = vi.hoisted(() => ({
  available: true,
  draw: vi.fn(),
  setImage: vi.fn(),
}));

vi.mock("$lib/equirectPreview", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./equirectPreview")>()),
  createEquirectRenderer: (): EquirectRenderer | null =>
    renderer.available
      ? { draw: renderer.draw, setImage: renderer.setImage, dispose() {} }
      : null,
  loadImage: async (url: string) => ({ url }),
}));

const ID = "20260101-090000-000";
const IMAGE = "data:image/jpeg;base64,AAAA";
const left = {
  center_x_px: 2028,
  center_y_px: 1520,
  radius_px: 1469.5,
  rotation_deg: 0,
};
const right = {
  center_x_px: 2019,
  center_y_px: 1527.75,
  radius_px: 1466.5,
  rotation_deg: 1.2,
};

let responses: Record<string, (args?: unknown) => Promise<unknown>>;
let editor: ReturnType<typeof mount>;
let closed: boolean;

function settle() {
  return new Promise((resolve) => setTimeout(resolve)).then(tick);
}

function input(label: string) {
  return document.querySelector<HTMLInputElement>(
    `input[aria-label="${label}"]`,
  )!;
}

function button(text: string) {
  return [...document.querySelectorAll("button")].find(
    (b) => b.textContent?.trim() === text,
  )!;
}

async function click(text: string) {
  button(text).click();
  flushSync();
  await settle();
}

function edit(label: string, value: string) {
  const target = input(label);
  target.value = value;
  target.dispatchEvent(new Event("input", { bubbles: true }));
  flushSync();
}

function alerts() {
  return [...document.querySelectorAll('[role="alert"]')].map(
    (e) => e.textContent,
  );
}

async function open() {
  editor = mount(CorrectionEditor, {
    target: document.body,
    props: { id: ID, onclose: () => (closed = true) },
  });
  await settle();
}

beforeEach(() => {
  renderer.available = true;
  renderer.draw.mockReset();
  renderer.setImage.mockReset();
  closed = false;
  responses = {
    get_capture_correction: async () => ({
      left,
      right,
      overridden: { left: false, right: true },
    }),
    capture_preview: async () => ({ dataUrl: IMAGE, width: 4056, height: 3040 }),
  };
  vi.mocked(invoke).mockReset();
  vi.mocked(invoke).mockImplementation(async (cmd: string, args?: unknown) =>
    responses[cmd](args),
  );
});

afterEach(() => {
  unmount(editor);
});

describe("CorrectionEditor.svelte", () => {
  it("loads the correction and previews of the capture", async () => {
    await open();
    expect(invoke).toHaveBeenCalledWith("get_capture_correction", { id: ID });
    expect(invoke).toHaveBeenCalledWith("capture_preview", {
      id: ID,
      side: "left",
    });
    expect(invoke).toHaveBeenCalledWith("capture_preview", {
      id: ID,
      side: "right",
    });
    expect(document.body.textContent).toContain(`補正: ${ID}`);
  });

  it("puts the values of each side into the number inputs and sliders", async () => {
    await open();
    expect(input("左 中心 x").valueAsNumber).toBe(2028);
    expect(input("左 中心 y").valueAsNumber).toBe(1520);
    expect(input("左 半径").valueAsNumber).toBe(1469.5);
    expect(input("左 回転").valueAsNumber).toBe(0);
    expect(input("右 中心 y").valueAsNumber).toBe(1527.75);
    expect(input("右 回転").valueAsNumber).toBe(1.2);
    expect(input("右 半径 スライダー").valueAsNumber).toBe(1466.5);
  });

  it("limits the sliders to the original image and rotation range", async () => {
    await open();
    expect(input("左 中心 x スライダー").max).toBe("4056");
    expect(input("左 中心 y スライダー").max).toBe("3040");
    expect(input("左 回転 スライダー").min).toBe("-179.9");
    expect(input("左 回転 スライダー").max).toBe("180");
  });

  it("shows whether each side uses the device default or a capture override", async () => {
    await open();
    const legends = [...document.querySelectorAll("fieldset")].map(
      (f) => f.textContent,
    );
    expect(legends[0]).toContain("既定値を使用");
    expect(legends[1]).toContain("この撮影で上書き");
  });

  it("draws the image circle and its center on the fisheye image", async () => {
    await open();
    const svg = document.querySelector('svg[aria-label="左 魚眼画像"]')!;
    expect(svg.getAttribute("viewBox")).toBe("0 0 4056 3040");
    expect(svg.querySelector("image")!.getAttribute("href")).toBe(IMAGE);
    const circle = svg.querySelector("circle")!;
    expect(circle.getAttribute("cx")).toBe("2028");
    expect(circle.getAttribute("cy")).toBe("1520");
    expect(circle.getAttribute("r")).toBe("1469.5");
  });

  it("redraws the overlay and the conversion with edited values", async () => {
    await open();
    expect(renderer.setImage).toHaveBeenCalledWith({ url: IMAGE });
    expect(renderer.draw).toHaveBeenCalledWith(left, 4056, 3040);

    edit("左 中心 x", "2040");
    expect(input("左 中心 x スライダー").valueAsNumber).toBe(2040);
    expect(
      document.querySelector('svg[aria-label="左 魚眼画像"] circle')!
        .getAttribute("cx"),
    ).toBe("2040");
    expect(renderer.draw).toHaveBeenLastCalledWith(
      { ...left, center_x_px: 2040 },
      4056,
      3040,
    );

    edit("左 回転 スライダー", "12.5");
    expect(input("左 回転").valueAsNumber).toBe(12.5);
    expect(renderer.draw).toHaveBeenLastCalledWith(
      { ...left, center_x_px: 2040, rotation_deg: 12.5 },
      4056,
      3040,
    );
  });

  it("shows a message instead of the conversion when WebGL is unavailable", async () => {
    renderer.available = false;
    await open();
    expect(document.body.textContent).toContain(
      "WebGL を使えないため、変換プレビューを表示できません",
    );
    expect(renderer.draw).not.toHaveBeenCalled();
  });

  it("saves both sides as the capture override and shows the result", async () => {
    responses.set_capture_correction = async () => ({
      left: { ...left, center_x_px: 2040 },
      right,
      overridden: { left: true, right: true },
    });
    await open();
    edit("左 中心 x", "2040");

    await click("この撮影に保存");

    expect(invoke).toHaveBeenCalledWith("set_capture_correction", {
      id: ID,
      left: { ...left, center_x_px: 2040 },
      right,
    });
    expect(document.body.textContent).toContain("この撮影に保存しました");
    expect(document.querySelector("fieldset")!.textContent).toContain(
      "この撮影で上書き",
    );
  });

  it("locks the inputs while a save is pending", async () => {
    let resolve!: (value: unknown) => void;
    responses.set_capture_correction = () =>
      new Promise((r) => (resolve = r));
    await open();

    await click("この撮影に保存");

    const inputs = [...document.querySelectorAll("input")];
    expect(inputs.every((i) => i.matches(":disabled"))).toBe(true);

    resolve({ left, right, overridden: { left: true, right: true } });
    await settle();

    expect(inputs.every((i) => i.matches(":enabled"))).toBe(true);
  });

  it("saves both sides as the device default", async () => {
    responses.set_device_correction = async (args) => args;
    await open();
    edit("右 半径", "1470");

    await click("既定値として保存");

    expect(invoke).toHaveBeenCalledWith("set_device_correction", {
      left,
      right: { ...right, radius_px: 1470 },
    });
    expect(document.body.textContent).toContain("既定値として保存しました");
  });

  it("clears the capture override and shows the device default again", async () => {
    responses.clear_capture_correction = async () => ({
      left,
      right: left,
      overridden: { left: false, right: false },
    });
    await open();
    edit("右 中心 x", "1000");

    await click("既定値に戻す");

    expect(invoke).toHaveBeenCalledWith("clear_capture_correction", { id: ID });
    expect(input("右 中心 x").valueAsNumber).toBe(2028);
    expect(document.querySelectorAll("fieldset")[1].textContent).toContain(
      "既定値を使用",
    );
    expect(document.body.textContent).toContain("既定値に戻しました");
  });

  it("shows a save error as an alert and keeps the edited values", async () => {
    responses.set_capture_correction = () =>
      Promise.reject("補正値が範囲外です");
    await open();
    edit("左 半径", "-1");

    await click("この撮影に保存");

    expect(alerts()).toEqual(["補正値が範囲外です"]);
    expect(input("左 半径").valueAsNumber).toBe(-1);
    expect(document.body.textContent).not.toContain("保存しました");
  });

  it("clears the previous message when the next action fails", async () => {
    responses.set_device_correction = async (args) => args;
    responses.clear_capture_correction = () => Promise.reject("clear failed");
    await open();
    await click("既定値として保存");

    await click("既定値に戻す");

    expect(alerts()).toEqual(["clear failed"]);
    expect(document.body.textContent).not.toContain("既定値として保存しました");
  });

  it("shows load errors as alerts", async () => {
    responses.get_capture_correction = () => Promise.reject("broken file");
    await open();
    expect(alerts()).toEqual(["broken file"]);
  });

  it("shows a preview error for the side that failed", async () => {
    responses.capture_preview = async (args) => {
      if ((args as { side: string }).side === "right") {
        throw "preview failed";
      }
      return { dataUrl: IMAGE, width: 4056, height: 3040 };
    };
    await open();
    expect(alerts()).toEqual(["preview failed"]);
    expect(document.querySelector('svg[aria-label="左 魚眼画像"]')).not.toBeNull();
  });

  it("calls onclose when closed", async () => {
    await open();
    await click("閉じる");
    expect(closed).toBe(true);
  });
});
