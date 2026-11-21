import { invoke } from "@tauri-apps/api/core";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { getViewerServerStatus } from "./viewerServer";

vi.mock("@tauri-apps/api/core", () => ({ invoke: vi.fn() }));

describe("viewerServer", () => {
  beforeEach(() => {
    vi.mocked(invoke).mockReset();
  });

  it("gets the viewer server status from the backend", async () => {
    const status = {
      running: true,
      urls: ["https://localhost:8443/"],
      error: null,
    };
    vi.mocked(invoke).mockResolvedValue(status);
    await expect(getViewerServerStatus()).resolves.toEqual(status);
    expect(invoke).toHaveBeenCalledWith("get_viewer_server_status");
  });
});
