import { invoke } from "@tauri-apps/api/core";

export type Side = "left" | "right";

export function listCaptures(): Promise<string[]> {
  return invoke<string[]>("list_captures");
}

export function getCaptureThumbnail(id: string, side: Side): Promise<string> {
  return invoke<string>("capture_thumbnail", { id, side });
}
