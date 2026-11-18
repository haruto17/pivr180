import { render } from "svelte/server";
import { describe, expect, it, vi } from "vitest";
import Page from "./+page.svelte";

vi.mock("@tauri-apps/api/core", () => ({ invoke: vi.fn() }));

describe("+page.svelte", () => {
  it("renders the app title", () => {
    const { body } = render(Page);
    expect(body).toContain("pivr180 editor");
  });

  it("renders the storage section with a form to change the root", () => {
    const { body } = render(Page);
    expect(body).toContain("<h2>保存先</h2>");
    expect(body).toContain('aria-label="保存先"');
    expect(body).toContain("保存</button>");
  });
});
