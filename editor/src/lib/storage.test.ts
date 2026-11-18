import { invoke } from "@tauri-apps/api/core";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { getStorageSettings, setStorageSettings } from "./storage";

vi.mock("@tauri-apps/api/core", () => ({ invoke: vi.fn() }));

const paths = {
  root: "/Users/me/Pictures/pivr180",
  captures: "/Users/me/Pictures/pivr180/captures",
  exports: "/Users/me/Pictures/pivr180/exports",
};

describe("storage", () => {
  beforeEach(() => {
    vi.mocked(invoke).mockReset();
  });

  it("gets the storage settings from the backend", async () => {
    vi.mocked(invoke).mockResolvedValue(paths);
    await expect(getStorageSettings()).resolves.toEqual(paths);
    expect(invoke).toHaveBeenCalledWith("get_storage_settings");
  });

  it("sends the new root to the backend", async () => {
    vi.mocked(invoke).mockResolvedValue(paths);
    await expect(setStorageSettings(paths.root)).resolves.toEqual(paths);
    expect(invoke).toHaveBeenCalledWith("set_storage_settings", {
      root: paths.root,
    });
  });
});
