import { invoke } from "@tauri-apps/api/core";

export function getImportHost(): Promise<string> {
  return invoke<string>("get_import_host");
}

export function setImportHost(host: string): Promise<string> {
  return invoke<string>("set_import_host", { host });
}

export function importCaptures(): Promise<string[]> {
  return invoke<string[]>("import_captures");
}
