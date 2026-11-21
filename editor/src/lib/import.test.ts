import { invoke } from "@tauri-apps/api/core";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { getImportHost, importCaptures, setImportHost } from "./import";

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

  it("imports captures and returns the imported capture folders", async () => {
    const imported = ["20260101-000000-001", "20260101-000000-002"];
    vi.mocked(invoke).mockResolvedValue(imported);
    await expect(importCaptures()).resolves.toEqual(imported);
    expect(invoke).toHaveBeenCalledWith("import_captures");
  });
});
