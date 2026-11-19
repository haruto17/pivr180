import { render } from "svelte/server";
import { describe, expect, it, vi } from "vitest";
import CaptureItem from "./CaptureItem.svelte";

vi.mock("@tauri-apps/api/core", () => ({ invoke: vi.fn() }));

describe("CaptureItem.svelte", () => {
  it("shows the capture id with left and right thumbnail slots side by side", () => {
    const { body } = render(CaptureItem, {
      props: { id: "20260101-090000-000" },
    });
    expect(body).toContain("<h3>20260101-090000-000</h3>");
    expect(body).toMatch(
      /<figcaption>左<\/figcaption>[\s\S]*<figcaption>右<\/figcaption>/,
    );
    expect(body.match(/読み込み中…/g)).toHaveLength(2);
  });
});
