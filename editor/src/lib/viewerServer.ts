import { invoke } from "@tauri-apps/api/core";

export type ViewerServerStatus = {
  running: boolean;
  urls: string[];
  error: string | null;
};

export function getViewerServerStatus(): Promise<ViewerServerStatus> {
  return invoke<ViewerServerStatus>("get_viewer_server_status");
}
