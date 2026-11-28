package io.github.haruto17.pivr180.capture

import io.github.haruto17.pivr180.connection.DeadlineScheduler
import io.github.haruto17.pivr180.protocol.AppMessage
import io.github.haruto17.pivr180.protocol.Captures
import io.github.haruto17.pivr180.protocol.DeviceMessage
import io.github.haruto17.pivr180.protocol.ErrorMessage
import io.github.haruto17.pivr180.protocol.GetMode
import io.github.haruto17.pivr180.protocol.GetThumbnail
import io.github.haruto17.pivr180.protocol.Mode
import io.github.haruto17.pivr180.protocol.Ok
import io.github.haruto17.pivr180.protocol.Settings
import io.github.haruto17.pivr180.protocol.Shutdown
import io.github.haruto17.pivr180.protocol.Shutter
import io.github.haruto17.pivr180.protocol.Side
import io.github.haruto17.pivr180.protocol.StartPreview
import io.github.haruto17.pivr180.protocol.Status
import io.github.haruto17.pivr180.protocol.StopPreview
import io.github.haruto17.pivr180.protocol.Welcome
import kotlin.time.Duration

private sealed interface Request {
    data object Shutter : Request

    data object GetMode : Request

    data class Thumbnail(
        val captureId: String,
        val side: Side,
    ) : Request

    data object Shutdown : Request

    data class Preview(
        val send: Boolean,
    ) : Request
}

// Not synchronized: the caller confines it to one thread, which also runs the deadlines.
class CaptureController<I>(
    private val send: (AppMessage) -> Unit,
    deadlines: DeadlineScheduler,
    private var previewWanted: Boolean,
    requestTimeout: Duration = REQUEST_TIMEOUT,
    private val onState: (CaptureState<I>) -> Unit,
) {
    private val requests =
        RequestTracker<Request>(deadlines, requestTimeout) {
            // Not left as it was: the device may have switched and its late ok is dropped.
            if (it is Request.Preview) deviceSendsPreview = null
            fail(it, "no answer within $requestTimeout")
            publish()
        }
    private var state = CaptureState<I>()
    private var started = false
    private var ended = false
    private var deviceSendsPreview: Boolean? = true
    private var previewRequestPending = false

    fun start() {
        if (started || ended) return
        started = true
        send(GetMode(requests.issue(Request.GetMode)))
        reconcilePreview()
        publish()
    }

    fun receive(message: DeviceMessage) {
        if (!started || ended) return
        when (message) {
            is Status -> applyStatus(message)
            is Ok -> requests.complete(message.id)?.let(::succeed)
            is Mode -> receiveMode(message)
            is ErrorMessage -> rejected(message)
            is Welcome -> unexpected(message.id, "welcome")
            is Settings -> unexpected(message.id, "settings")
            is Captures -> unexpected(message.id, "captures")
        }
        publish()
    }

    fun receiveThumbnail(
        id: Int,
        image: I?,
    ) {
        if (!started || ended) return
        when (val request = requests.complete(id)) {
            null -> {
                return
            }

            is Request.Thumbnail -> {
                setThumbnail(
                    request,
                    if (image ==
                        null
                    ) {
                        Thumbnail.Unavailable("not a JPEG")
                    } else {
                        Thumbnail.Loaded(image)
                    },
                )
            }

            else -> {
                fail(request, "unexpected thumbnail")
            }
        }
        publish()
    }

    fun shutter() {
        if (!started || ended || !state.canShutter) return
        send(Shutter(requests.issue(Request.Shutter)))
        state = state.copy(shutterPending = true)
        publish()
    }

    fun shutdown() {
        if (!started || ended || !state.canShutdown) return
        send(Shutdown(requests.issue(Request.Shutdown)))
        state = state.copy(shutdown = ShutdownState.REQUESTED)
        publish()
    }

    fun setPreviewWanted(wanted: Boolean) {
        previewWanted = wanted
        if (!started || ended) return
        reconcilePreview()
    }

    fun dismissNotice() {
        if (ended) return
        state = state.copy(notice = null)
        publish()
    }

    fun onDisconnected() {
        if (ended) return
        ended = true
        requests.cancelAll()
        // Not treated as a lost connection: the device may power off before its ok reaches the app.
        if (state.shutdown == ShutdownState.REQUESTED || state.shutdown == ShutdownState.ACCEPTED) {
            state = state.copy(shutdown = ShutdownState.DONE)
        }
        publish()
    }

    private fun applyStatus(status: Status) {
        val last = status.lastCapture
        state =
            when {
                last == null -> state.copy(status = status, lastCapture = null)
                last.id == state.lastCapture?.captureId -> state.copy(status = status)
                else -> state.copy(status = status, lastCapture = LastCaptureThumbnails(last.id)).also { requestThumbnails(last.id) }
            }
    }

    private fun requestThumbnails(captureId: String) {
        for (side in Side.entries) {
            send(GetThumbnail(requests.issue(Request.Thumbnail(captureId, side)), captureId, side))
        }
    }

    private fun receiveMode(message: Mode) {
        when (val request = requests.complete(message.id)) {
            null -> Unit
            Request.GetMode -> state = state.copy(mode = ModeState.Known(message.mode))
            else -> fail(request, "unexpected mode")
        }
    }

    private fun setThumbnail(
        request: Request.Thumbnail,
        thumbnail: Thumbnail<I>,
    ) {
        val last = state.lastCapture
        if (last?.captureId != request.captureId) return
        state =
            state.copy(
                lastCapture =
                    when (request.side) {
                        Side.LEFT -> last.copy(left = thumbnail)
                        Side.RIGHT -> last.copy(right = thumbnail)
                    },
            )
    }

    private fun unexpected(
        id: Int,
        what: String,
    ) {
        requests.complete(id)?.let { fail(it, "unexpected $what") }
    }

    private fun rejected(message: ErrorMessage) {
        val detail = "${message.code.name.lowercase()}: ${message.message}"
        val id = message.id
        if (id == null) {
            state = state.copy(notice = Notice(NoticeKind.MESSAGE_REJECTED, detail))
            return
        }
        requests.complete(id)?.let { fail(it, detail) }
    }

    private fun succeed(request: Request) {
        when (request) {
            Request.Shutter -> {
                state = state.copy(shutterPending = false)
            }

            Request.Shutdown -> {
                state = state.copy(shutdown = ShutdownState.ACCEPTED)
            }

            is Request.Preview -> {
                previewRequestPending = false
                deviceSendsPreview = request.send
                reconcilePreview()
            }

            Request.GetMode -> {
                fail(request, "unexpected ok")
            }

            is Request.Thumbnail -> {
                fail(request, "unexpected ok")
            }
        }
    }

    private fun fail(
        request: Request,
        detail: String,
    ) {
        state =
            when (request) {
                Request.Shutter -> {
                    state.copy(shutterPending = false, notice = Notice(NoticeKind.SHUTTER_FAILED, detail))
                }

                Request.Shutdown -> {
                    state.copy(shutdown = ShutdownState.NONE, notice = Notice(NoticeKind.SHUTDOWN_FAILED, detail))
                }

                Request.GetMode -> {
                    state.copy(mode = ModeState.Unknown, notice = Notice(NoticeKind.MODE_FAILED, detail))
                }

                is Request.Preview -> {
                    // Not retried here: a device that refuses would be asked again forever.
                    previewRequestPending = false
                    state.copy(notice = Notice(NoticeKind.PREVIEW_FAILED, detail))
                }

                is Request.Thumbnail -> {
                    setThumbnail(request, Thumbnail.Unavailable(detail))
                    state
                }
            }
    }

    private fun reconcilePreview() {
        if (previewRequestPending || previewWanted == deviceSendsPreview) return
        previewRequestPending = true
        val id = requests.issue(Request.Preview(previewWanted))
        send(if (previewWanted) StartPreview(id) else StopPreview(id))
    }

    private fun publish() {
        onState(state)
    }
}
