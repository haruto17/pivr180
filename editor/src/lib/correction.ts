import { invoke } from "@tauri-apps/api/core";

export type ImageCircle = {
  center_x_px: number;
  center_y_px: number;
  radius_px: number;
  rotation_deg: number;
};

export type StereoCorrection = {
  left: ImageCircle;
  right: ImageCircle;
};

export type CorrectionOverride = {
  left?: ImageCircle;
  right?: ImageCircle;
};

export type CaptureCorrection = StereoCorrection & {
  overridden: { left: boolean; right: boolean };
};

export function getDeviceCorrection(): Promise<StereoCorrection> {
  return invoke<StereoCorrection>("get_device_correction");
}

export function setDeviceCorrection(
  correction: StereoCorrection,
): Promise<StereoCorrection> {
  return invoke<StereoCorrection>("set_device_correction", {
    left: correction.left,
    right: correction.right,
  });
}

export function getCaptureCorrection(id: string): Promise<CaptureCorrection> {
  return invoke<CaptureCorrection>("get_capture_correction", { id });
}

export function setCaptureCorrection(
  id: string,
  override: CorrectionOverride,
): Promise<CaptureCorrection> {
  return invoke<CaptureCorrection>("set_capture_correction", {
    id,
    left: override.left ?? null,
    right: override.right ?? null,
  });
}

export function clearCaptureCorrection(id: string): Promise<CaptureCorrection> {
  return invoke<CaptureCorrection>("clear_capture_correction", { id });
}
