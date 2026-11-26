package io.github.haruto17.pivr180.protocol

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json

const val PROTOCOL_VERSION = 1

val protocolJson = Json

@Serializable
sealed interface AppMessage {
    val id: Int
}

@Serializable
@SerialName("hello")
data class Hello(
    override val id: Int,
    @SerialName("protocol_version") val protocolVersion: Int,
    @SerialName("app_version") val appVersion: String,
) : AppMessage

@Serializable
@SerialName("shutter")
data class Shutter(
    override val id: Int,
) : AppMessage

@Serializable
@SerialName("get_settings")
data class GetSettings(
    override val id: Int,
) : AppMessage

@Serializable
@SerialName("set_settings")
data class SetSettings(
    override val id: Int,
    val settings: CameraSettings,
) : AppMessage

@Serializable
@SerialName("get_mode")
data class GetMode(
    override val id: Int,
) : AppMessage

@Serializable
@SerialName("set_mode")
data class SetMode(
    override val id: Int,
    val mode: CaptureMode,
) : AppMessage

@Serializable
@SerialName("list_captures")
data class ListCaptures(
    override val id: Int,
) : AppMessage

@Serializable
@SerialName("get_thumbnail")
data class GetThumbnail(
    override val id: Int,
    @SerialName("capture_id") val captureId: String,
    val side: Side,
) : AppMessage

@Serializable
@SerialName("delete_capture")
data class DeleteCapture(
    override val id: Int,
    @SerialName("capture_id") val captureId: String,
) : AppMessage

@Serializable
@SerialName("shutdown")
data class Shutdown(
    override val id: Int,
) : AppMessage

@Serializable
sealed interface DeviceMessage

@Serializable
@SerialName("welcome")
data class Welcome(
    val id: Int,
    @SerialName("protocol_version") val protocolVersion: Int,
    @SerialName("software_version") val softwareVersion: String,
) : DeviceMessage

@Serializable
@SerialName("ok")
data class Ok(
    val id: Int,
) : DeviceMessage

@Serializable
@SerialName("settings")
data class Settings(
    val id: Int,
    val settings: CameraSettings,
) : DeviceMessage

@Serializable
@SerialName("mode")
data class Mode(
    val id: Int,
    val mode: CaptureMode,
) : DeviceMessage

@Serializable
@SerialName("captures")
data class Captures(
    val id: Int,
    val captures: List<CaptureSummary>,
) : DeviceMessage

@Serializable
@SerialName("status")
data class Status(
    val state: DeviceState,
    @SerialName("error_message") val errorMessage: String? = null,
    @SerialName("capture_count") val captureCount: Int,
    @SerialName("free_bytes") val freeBytes: Long,
    @SerialName("last_capture") val lastCapture: LastCapture?,
) : DeviceMessage

@Serializable
@SerialName("error")
data class ErrorMessage(
    val id: Int? = null,
    val code: ErrorCode,
    val message: String,
) : DeviceMessage

@Serializable
data class CameraSettings(
    @SerialName("exposure_value") val exposureValue: Double,
    @SerialName("white_balance") val whiteBalance: WhiteBalance,
    val contrast: Double,
)

@Serializable
data class CaptureSummary(
    val id: String,
    val complete: Boolean,
    @SerialName("sync_warning") val syncWarning: Boolean?,
)

@Serializable
data class LastCapture(
    val id: String,
    @SerialName("sync_warning") val syncWarning: Boolean,
)

@Serializable
enum class CaptureMode {
    @SerialName("photo")
    PHOTO,
}

@Serializable
enum class Side {
    @SerialName("left")
    LEFT,

    @SerialName("right")
    RIGHT,
}

@Serializable
enum class WhiteBalance {
    @SerialName("auto")
    AUTO,

    @SerialName("incandescent")
    INCANDESCENT,

    @SerialName("tungsten")
    TUNGSTEN,

    @SerialName("fluorescent")
    FLUORESCENT,

    @SerialName("indoor")
    INDOOR,

    @SerialName("daylight")
    DAYLIGHT,

    @SerialName("cloudy")
    CLOUDY,
}

@Serializable
enum class DeviceState {
    @SerialName("idle")
    IDLE,

    @SerialName("capturing")
    CAPTURING,

    @SerialName("error")
    ERROR,
}

@Serializable
enum class ErrorCode {
    @SerialName("unsupported_protocol_version")
    UNSUPPORTED_PROTOCOL_VERSION,

    @SerialName("handshake_required")
    HANDSHAKE_REQUIRED,

    @SerialName("invalid_message")
    INVALID_MESSAGE,

    @SerialName("cameras_not_ready")
    CAMERAS_NOT_READY,

    @SerialName("capture_not_found")
    CAPTURE_NOT_FOUND,

    @SerialName("internal_error")
    INTERNAL_ERROR,
}
