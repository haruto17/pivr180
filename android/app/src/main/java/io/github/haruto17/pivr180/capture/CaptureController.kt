package io.github.haruto17.pivr180.capture

import io.github.haruto17.pivr180.connection.DeadlineScheduler
import io.github.haruto17.pivr180.protocol.AppMessage
import io.github.haruto17.pivr180.protocol.CaptureSummary
import io.github.haruto17.pivr180.protocol.Captures
import io.github.haruto17.pivr180.protocol.DeleteCapture
import io.github.haruto17.pivr180.protocol.DeviceMessage
import io.github.haruto17.pivr180.protocol.ErrorCode
import io.github.haruto17.pivr180.protocol.ErrorMessage
import io.github.haruto17.pivr180.protocol.GetMode
import io.github.haruto17.pivr180.protocol.GetThumbnail
import io.github.haruto17.pivr180.protocol.ListCaptures
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

// Not all sent at once: the device makes thumbnails one at a time, so requests queued behind many others would time out.
const val MAX_LIST_THUMBNAILS_IN_FLIGHT = 4

// Not kept for every capture: a 480x360 thumbnail decodes to about 0.7 MB.
const val MAX_CACHED_LIST_THUMBNAILS = 40

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

    data object ListCaptures : Request

    data class ListThumbnail(
        val key: ThumbnailKey,
    ) : Request

    data class Delete(
        val captureId: String,
    ) : Request
}

private data class ThumbnailKey(
    val captureId: String,
    val side: Side,
)

// Not synchronized: the caller confines it to one thread, which also runs the deadlines.
class CaptureController<I>(
    private val send: (AppMessage) -> Unit,
    deadlines: DeadlineScheduler,
    private var previewWanted: Boolean,
    requestTimeout: Duration = REQUEST_TIMEOUT,
    private val maxListThumbnailsInFlight: Int = MAX_LIST_THUMBNAILS_IN_FLIGHT,
    private val maxCachedListThumbnails: Int = MAX_CACHED_LIST_THUMBNAILS,
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
    private var listedCaptures: List<CaptureSummary>? = null
    private var visibleCaptures: List<String> = emptyList()
    private val deleting = mutableSetOf<String>()

    // Not access-ordered: reading a thumbnail to build the state is not a sign that it is still on screen.
    private val listThumbnails = LinkedHashMap<ThumbnailKey, Thumbnail<I>>()
    private val listThumbnailsInFlight = mutableSetOf<ThumbnailKey>()

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
            is Captures -> receiveCaptures(message)
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
                setThumbnail(request, thumbnailOf(image))
            }

            is Request.ListThumbnail -> {
                setListThumbnail(request.key, thumbnailOf(image))
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

    fun refreshCaptures() {
        if (!started || ended || state.captureList.loading) return
        send(ListCaptures(requests.issue(Request.ListCaptures)))
        state = state.copy(captureList = state.captureList.copy(loading = true))
        publish()
    }

    fun showCaptures(captureIds: List<String>) {
        if (!started || ended) return
        visibleCaptures = captureIds
        for (key in visibleKeys()) listThumbnails.remove(key)?.let { listThumbnails[key] = it }
        requestVisibleThumbnails()
    }

    fun deleteCapture(captureId: String) {
        if (!started || ended || captureId in deleting || listedCaptures?.any { it.id == captureId } != true) return
        send(DeleteCapture(requests.issue(Request.Delete(captureId)), captureId))
        deleting += captureId
        publishList()
    }

    fun dismissCaptureListNotice() {
        if (ended) return
        state = state.copy(captureList = state.captureList.copy(notice = null))
        publish()
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

    private fun receiveCaptures(message: Captures) {
        when (val request = requests.complete(message.id)) {
            null -> {
                Unit
            }

            Request.ListCaptures -> {
                listedCaptures = message.captures
                val listed = message.captures.mapTo(mutableSetOf()) { it.id }
                // Not kept: refreshing is how the user retries a thumbnail that could not be loaded.
                listThumbnails.entries.removeAll { (key, thumbnail) -> key.captureId !in listed || thumbnail is Thumbnail.Unavailable }
                state = state.copy(captureList = state.captureList.copy(loading = false))
                updateList()
                requestVisibleThumbnails()
            }

            else -> {
                fail(request, "unexpected captures")
            }
        }
    }

    private fun visibleKeys(): List<ThumbnailKey> {
        val listed = listedCaptures?.mapTo(mutableSetOf()) { it.id } ?: return emptyList()
        return visibleCaptures
            .filter { it in listed && it !in deleting }
            .flatMap { captureId -> Side.entries.map { ThumbnailKey(captureId, it) } }
    }

    private fun requestVisibleThumbnails() {
        for (key in visibleKeys()) {
            if (listThumbnailsInFlight.size >= maxListThumbnailsInFlight) return
            if (key in listThumbnails || key in listThumbnailsInFlight) continue
            listThumbnailsInFlight += key
            send(GetThumbnail(requests.issue(Request.ListThumbnail(key)), key.captureId, key.side))
        }
    }

    private fun setListThumbnail(
        key: ThumbnailKey,
        thumbnail: Thumbnail<I>,
    ) {
        listThumbnailsInFlight -= key
        if (listedCaptures?.any { it.id == key.captureId } == true) {
            listThumbnails[key] = thumbnail
            dropHiddenThumbnails()
            updateList()
        }
        requestVisibleThumbnails()
    }

    private fun dropHiddenThumbnails() {
        val visible = visibleCaptures.toSet()
        val excess = listThumbnails.size - maxCachedListThumbnails
        if (excess <= 0) return
        listThumbnails.keys
            .filter { it.captureId !in visible }
            .take(excess)
            .forEach { listThumbnails.remove(it) }
    }

    private fun removeFromList(captureId: String) {
        deleting -= captureId
        listedCaptures = listedCaptures?.filterNot { it.id == captureId }
        listThumbnails.keys.removeAll { it.captureId == captureId }
        updateList()
    }

    private fun updateList() {
        val items =
            listedCaptures?.map { summary ->
                CaptureListItem(
                    summary = summary,
                    left = listThumbnails[ThumbnailKey(summary.id, Side.LEFT)] ?: Thumbnail.Loading,
                    right = listThumbnails[ThumbnailKey(summary.id, Side.RIGHT)] ?: Thumbnail.Loading,
                    deleting = summary.id in deleting,
                )
            }
        state = state.copy(captureList = state.captureList.copy(items = items))
    }

    private fun publishList() {
        updateList()
        publish()
    }

    private fun setListNotice(notice: CaptureListNotice) {
        state = state.copy(captureList = state.captureList.copy(notice = notice))
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
        val request = requests.complete(id) ?: return
        if (request is Request.Delete && message.code == ErrorCode.CAPTURE_NOT_FOUND) {
            removeFromList(request.captureId)
            setListNotice(CaptureListNotice(CaptureListNoticeKind.ALREADY_DELETED, request.captureId, detail))
        } else {
            fail(request, detail)
        }
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

            is Request.Delete -> {
                removeFromList(request.captureId)
            }

            Request.GetMode, is Request.Thumbnail, Request.ListCaptures, is Request.ListThumbnail -> {
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

                Request.ListCaptures -> {
                    state.copy(
                        captureList =
                            state.captureList.copy(
                                loading = false,
                                notice = CaptureListNotice(CaptureListNoticeKind.LOAD_FAILED, null, detail),
                            ),
                    )
                }

                is Request.ListThumbnail -> {
                    setListThumbnail(request.key, Thumbnail.Unavailable(detail))
                    state
                }

                is Request.Delete -> {
                    deleting -= request.captureId
                    updateList()
                    state.copy(
                        captureList =
                            state.captureList.copy(
                                notice = CaptureListNotice(CaptureListNoticeKind.DELETE_FAILED, request.captureId, detail),
                            ),
                    )
                }
            }
    }

    private fun reconcilePreview() {
        if (previewRequestPending || previewWanted == deviceSendsPreview) return
        previewRequestPending = true
        val id = requests.issue(Request.Preview(previewWanted))
        send(if (previewWanted) StartPreview(id) else StopPreview(id))
    }

    private fun thumbnailOf(image: I?): Thumbnail<I> = if (image == null) Thumbnail.Unavailable("not a JPEG") else Thumbnail.Loaded(image)

    private fun publish() {
        onState(state)
    }
}
