package io.github.haruto17.pivr180.capture

import io.github.haruto17.pivr180.protocol.CaptureMode
import io.github.haruto17.pivr180.protocol.DeviceState
import io.github.haruto17.pivr180.protocol.Status

data class CaptureState<out I>(
    val status: Status? = null,
    val mode: ModeState = ModeState.Loading,
    val lastCapture: LastCaptureThumbnails<I>? = null,
    val shutterPending: Boolean = false,
    val shutdown: ShutdownState = ShutdownState.NONE,
    val notice: Notice? = null,
    val settings: SettingsState = SettingsState.NotLoaded,
) {
    val canShutter: Boolean
        get() = status != null && status.state != DeviceState.CAPTURING && !shutterPending && shutdown == ShutdownState.NONE

    val canShutdown: Boolean get() = shutdown == ShutdownState.NONE
}

sealed interface ModeState {
    data object Loading : ModeState

    data class Known(
        val mode: CaptureMode,
    ) : ModeState

    data object Unknown : ModeState
}

data class LastCaptureThumbnails<out I>(
    val captureId: String,
    val left: Thumbnail<I> = Thumbnail.Loading,
    val right: Thumbnail<I> = Thumbnail.Loading,
)

sealed interface Thumbnail<out I> {
    data object Loading : Thumbnail<Nothing>

    data class Loaded<I>(
        val image: I,
    ) : Thumbnail<I>

    data class Unavailable(
        val detail: String,
    ) : Thumbnail<Nothing>
}

enum class ShutdownState {
    NONE,
    REQUESTED,
    ACCEPTED,
    DONE,
}

data class Notice(
    val kind: NoticeKind,
    val detail: String,
)

enum class NoticeKind {
    SHUTTER_FAILED,
    SHUTDOWN_FAILED,
    MODE_FAILED,
    PREVIEW_FAILED,
    MESSAGE_REJECTED,
}
