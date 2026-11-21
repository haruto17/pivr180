import { invoke } from "@tauri-apps/api/core";

export function getExportEyeSize(): Promise<number> {
  return invoke<number>("get_export_eye_size");
}

export function setExportEyeSize(size: number): Promise<number> {
  return invoke<number>("set_export_eye_size", { size });
}

export function exportCapture(id: string): Promise<string> {
  return invoke<string>("export_capture", { id });
}
