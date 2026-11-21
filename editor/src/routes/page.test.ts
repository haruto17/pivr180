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

  it("renders the capture list section with a reload button", () => {
    const { body } = render(Page);
    expect(body).toContain("<h2>撮影一覧</h2>");
    expect(body).toContain("再読み込み");
  });

  it("renders the import section with the host and the import button", () => {
    const { body } = render(Page);
    expect(body).toContain("<h2>取り込み</h2>");
    expect(body).toContain('aria-label="接続先"');
    expect(body).toContain("取り込む</button>");
  });

  it("renders the delete-after-import option unchecked", () => {
    const { body } = render(Page);
    expect(body).toContain('<input type="checkbox"/>');
    expect(body).toContain("取り込み後に Pi から削除する");
  });
});
