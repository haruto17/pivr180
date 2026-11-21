import { invoke } from "@tauri-apps/api/core";

export type Side = "left" | "right";

export function listCaptures(): Promise<string[]> {
  return invoke<string[]>("list_captures");
}

export function getCaptureThumbnail(id: string, side: Side): Promise<string> {
  return invoke<string>("capture_thumbnail", { id, side });
}

export type CapturePreview = {
  dataUrl: string;
  width: number;
  height: number;
};

export function getCapturePreview(
  id: string,
  side: Side,
): Promise<CapturePreview> {
  return invoke<CapturePreview>("capture_preview", { id, side });
}
