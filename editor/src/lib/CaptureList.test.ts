import { render } from "svelte/server";
import { describe, expect, it, vi } from "vitest";
import CaptureList from "./CaptureList.svelte";

vi.mock("@tauri-apps/api/core", () => ({ invoke: vi.fn() }));

describe("CaptureList.svelte", () => {
  it("renders the section heading and a reload button", () => {
    const { body } = render(CaptureList, { props: {} });
    expect(body).toContain("<h2>撮影一覧</h2>");
    expect(body).toMatch(
      /<button[^>]*type="button"[^>]*>\s*再読み込み\s*<\/button>/,
    );
  });
});
