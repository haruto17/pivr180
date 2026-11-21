import { invoke } from "@tauri-apps/api/core";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { exportCapture, getExportEyeSize, setExportEyeSize } from "./export";

vi.mock("@tauri-apps/api/core", () => ({ invoke: vi.fn() }));

describe("export", () => {
  beforeEach(() => {
    vi.mocked(invoke).mockReset();
  });

  it("gets the per-eye export size from the backend", async () => {
    vi.mocked(invoke).mockResolvedValue(2880);
    await expect(getExportEyeSize()).resolves.toBe(2880);
    expect(invoke).toHaveBeenCalledWith("get_export_eye_size");
  });

  it("sends the new per-eye export size to the backend", async () => {
    vi.mocked(invoke).mockResolvedValue(2048);
    await expect(setExportEyeSize(2048)).resolves.toBe(2048);
    expect(invoke).toHaveBeenCalledWith("set_export_eye_size", { size: 2048 });
  });

  it("exports a capture and returns the written path", async () => {
    const path = "/r/exports/20260101-090000-000_180_LR.jpg";
    vi.mocked(invoke).mockResolvedValue(path);
    await expect(exportCapture("20260101-090000-000")).resolves.toBe(path);
    expect(invoke).toHaveBeenCalledWith("export_capture", {
      id: "20260101-090000-000",
    });
  });
});
