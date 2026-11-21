import { invoke } from "@tauri-apps/api/core";

export function getImportHost(): Promise<string> {
  return invoke<string>("get_import_host");
}

export function setImportHost(host: string): Promise<string> {
  return invoke<string>("set_import_host", { host });
}

export type ImportResult = {
  imported: string[];
  removed: string[];
  removeError: string | null;
};

export function getDeleteAfterImport(): Promise<boolean> {
  return invoke<boolean>("get_delete_after_import");
}

export function setDeleteAfterImport(enabled: boolean): Promise<boolean> {
  return invoke<boolean>("set_delete_after_import", { enabled });
}

export function importCaptures(): Promise<ImportResult> {
  return invoke<ImportResult>("import_captures");
}
