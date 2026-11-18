import { invoke } from "@tauri-apps/api/core";

export type StoragePaths = {
  root: string;
  captures: string;
  exports: string;
};

export function getStorageSettings(): Promise<StoragePaths> {
  return invoke<StoragePaths>("get_storage_settings");
}

export function setStorageSettings(root: string): Promise<StoragePaths> {
  return invoke<StoragePaths>("set_storage_settings", { root });
}
