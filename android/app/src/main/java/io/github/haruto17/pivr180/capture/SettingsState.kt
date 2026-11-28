package io.github.haruto17.pivr180.capture

import io.github.haruto17.pivr180.protocol.CameraSettings

sealed interface SettingsState {
    data object NotLoaded : SettingsState

    data object Loading : SettingsState

    data class Loaded(
        val settings: CameraSettings,
        val saving: Boolean = false,
        val result: SaveResult? = null,
    ) : SettingsState

    data class Unavailable(
        val reason: UnavailableReason,
        val detail: String,
    ) : SettingsState
}

enum class UnavailableReason {
    LOAD_FAILED,
    SAVE_UNCONFIRMED,
}

sealed interface SaveResult {
    data object Saved : SaveResult

    data class Failed(
        val detail: String,
    ) : SaveResult
}
