import { invoke } from "@tauri-apps/api/core";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  clearCaptureCorrection,
  getCaptureCorrection,
  getDeviceCorrection,
  setCaptureCorrection,
  setDeviceCorrection,
} from "./correction";

vi.mock("@tauri-apps/api/core", () => ({ invoke: vi.fn() }));

const left = {
  center_x_px: 2028,
  center_y_px: 1520,
  radius_px: 1469.5,
  rotation_deg: 0,
};
const right = {
  center_x_px: 2019,
  center_y_px: 1527.75,
  radius_px: 1466.5,
  rotation_deg: 1.2,
};
const id = "20260101-090000-000";

describe("correction", () => {
  beforeEach(() => {
    vi.mocked(invoke).mockReset();
  });

  it("gets the device default correction from the backend", async () => {
    vi.mocked(invoke).mockResolvedValue({ left, right });
    await expect(getDeviceCorrection()).resolves.toEqual({ left, right });
    expect(invoke).toHaveBeenCalledWith("get_device_correction");
  });

  it("sends both cameras of the device default to the backend", async () => {
    vi.mocked(invoke).mockResolvedValue({ left, right });
    await expect(setDeviceCorrection({ left, right })).resolves.toEqual({
      left,
      right,
    });
    expect(invoke).toHaveBeenCalledWith("set_device_correction", {
      left,
      right,
    });
  });

  it("gets the resolved correction of a capture with its overridden cameras", async () => {
    const result = {
      left,
      right,
      overridden: { left: false, right: true },
    };
    vi.mocked(invoke).mockResolvedValue(result);
    await expect(getCaptureCorrection(id)).resolves.toEqual(result);
    expect(invoke).toHaveBeenCalledWith("get_capture_correction", { id });
  });

  it("sends only the overridden camera and leaves the other unset", async () => {
    const result = {
      left,
      right,
      overridden: { left: false, right: true },
    };
    vi.mocked(invoke).mockResolvedValue(result);
    await expect(setCaptureCorrection(id, { right })).resolves.toEqual(result);
    expect(invoke).toHaveBeenCalledWith("set_capture_correction", {
      id,
      left: null,
      right,
    });
  });

  it("clears the override of a capture and returns the device default", async () => {
    const result = {
      left,
      right: left,
      overridden: { left: false, right: false },
    };
    vi.mocked(invoke).mockResolvedValue(result);
    await expect(clearCaptureCorrection(id)).resolves.toEqual(result);
    expect(invoke).toHaveBeenCalledWith("clear_capture_correction", { id });
  });
});
