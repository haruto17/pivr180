import { invoke } from "@tauri-apps/api/core";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  getCapturePreview,
  getCaptureThumbnail,
  listCaptures,
} from "./captures";

vi.mock("@tauri-apps/api/core", () => ({ invoke: vi.fn() }));

describe("captures", () => {
  beforeEach(() => {
    vi.mocked(invoke).mockReset();
  });

  it("lists the capture ids from the backend", async () => {
    const ids = ["20260301-120000-500", "20260101-090000-000"];
    vi.mocked(invoke).mockResolvedValue(ids);
    await expect(listCaptures()).resolves.toEqual(ids);
    expect(invoke).toHaveBeenCalledWith("list_captures");
  });

  it("requests the thumbnail of one side of a capture", async () => {
    const dataUrl = "data:image/jpeg;base64,AAAA";
    vi.mocked(invoke).mockResolvedValue(dataUrl);
    await expect(
      getCaptureThumbnail("20260101-090000-000", "right"),
    ).resolves.toBe(dataUrl);
    expect(invoke).toHaveBeenCalledWith("capture_thumbnail", {
      id: "20260101-090000-000",
      side: "right",
    });
  });

  it("requests the preview of one side of a capture with its original size", async () => {
    const preview = {
      dataUrl: "data:image/jpeg;base64,AAAA",
      width: 4056,
      height: 3040,
    };
    vi.mocked(invoke).mockResolvedValue(preview);
    await expect(
      getCapturePreview("20260101-090000-000", "left"),
    ).resolves.toEqual(preview);
    expect(invoke).toHaveBeenCalledWith("capture_preview", {
      id: "20260101-090000-000",
      side: "left",
    });
  });
});
