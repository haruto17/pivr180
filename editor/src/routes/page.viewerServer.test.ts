// @vitest-environment jsdom
import { invoke } from "@tauri-apps/api/core";
import { mount, tick, unmount } from "svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import Page from "./+page.svelte";
import type { ViewerServerStatus } from "$lib/viewerServer";

vi.mock("@tauri-apps/api/core", () => ({ invoke: vi.fn() }));

let status: () => Promise<ViewerServerStatus>;
let page: ReturnType<typeof mount> | undefined;

function settle() {
  return new Promise((resolve) => setTimeout(resolve)).then(tick);
}

function viewerSection() {
  return [...document.querySelectorAll("section")].find(
    (s) => s.querySelector("h2")?.textContent === "viewer 配信",
  )!;
}

async function mountPage() {
  page = mount(Page, { target: document.body });
  await settle();
}

beforeEach(() => {
  vi.mocked(invoke).mockReset();
  vi.mocked(invoke).mockImplementation(async (cmd: string) => {
    switch (cmd) {
      case "get_storage_settings":
        return { root: "/r", captures: "/r/captures", exports: "/r/exports" };
      case "get_import_host":
        return "pivr180.local";
      case "get_delete_after_import":
        return false;
      case "get_export_eye_size":
        return 2880;
      case "list_captures":
        return [];
      case "get_viewer_server_status":
        return status();
    }
  });
});

afterEach(() => {
  if (page) unmount(page);
  page = undefined;
});

describe("+page.svelte viewer server", () => {
  it("shows the viewer URLs when the server is running", async () => {
    status = async () => ({
      running: true,
      urls: ["https://localhost:8443/", "https://mac.local:8443/"],
      error: null,
    });

    await mountPage();

    expect(
      [...viewerSection().querySelectorAll("li")].map((li) => li.textContent),
    ).toEqual(["https://localhost:8443/", "https://mac.local:8443/"]);
    expect(viewerSection().querySelector('[role="alert"]')).toBeNull();
  });

  it("shows why the server could not start", async () => {
    status = async () => ({
      running: false,
      urls: [],
      error: "証明書を読み込めません: No such file or directory (os error 2)",
    });

    await mountPage();

    expect(viewerSection().querySelector("li")).toBeNull();
    expect(
      viewerSection().querySelector('[role="alert"]')!.textContent,
    ).toBe(
      "viewer を配信できません: 証明書を読み込めません: No such file or directory (os error 2)",
    );
  });

  it("shows the error when the status cannot be read", async () => {
    status = () => Promise.reject("command not found");

    await mountPage();

    expect(
      viewerSection().querySelector('[role="alert"]')!.textContent,
    ).toBe("command not found");
  });
});
