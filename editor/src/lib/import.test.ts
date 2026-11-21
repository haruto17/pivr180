import { invoke } from "@tauri-apps/api/core";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  getDeleteAfterImport,
  getImportHost,
  importCaptures,
  setDeleteAfterImport,
  setImportHost,
} from "./import";

vi.mock("@tauri-apps/api/core", () => ({ invoke: vi.fn() }));

describe("import", () => {
  beforeEach(() => {
    vi.mocked(invoke).mockReset();
  });

  it("gets the import host from the backend", async () => {
    vi.mocked(invoke).mockResolvedValue("pivr180.local");
    await expect(getImportHost()).resolves.toBe("pivr180.local");
    expect(invoke).toHaveBeenCalledWith("get_import_host");
  });

  it("sends the new import host to the backend", async () => {
    vi.mocked(invoke).mockResolvedValue("pi@pivr180.local");
    await expect(setImportHost("pi@pivr180.local")).resolves.toBe(
      "pi@pivr180.local",
    );
    expect(invoke).toHaveBeenCalledWith("set_import_host", {
      host: "pi@pivr180.local",
    });
  });

  it("gets the delete-after-import option from the backend", async () => {
    vi.mocked(invoke).mockResolvedValue(false);
    await expect(getDeleteAfterImport()).resolves.toBe(false);
    expect(invoke).toHaveBeenCalledWith("get_delete_after_import");
  });

  it("sends the delete-after-import option to the backend", async () => {
    vi.mocked(invoke).mockResolvedValue(true);
    await expect(setDeleteAfterImport(true)).resolves.toBe(true);
    expect(invoke).toHaveBeenCalledWith("set_delete_after_import", {
      enabled: true,
    });
  });

  it("imports captures and returns the imported and removed capture folders", async () => {
    const result = {
      imported: ["20260101-000000-001", "20260101-000000-002"],
      removed: ["20260101-000000-001"],
      removeError: null,
    };
    vi.mocked(invoke).mockResolvedValue(result);
    await expect(importCaptures()).resolves.toEqual(result);
    expect(invoke).toHaveBeenCalledWith("import_captures");
  });
});
