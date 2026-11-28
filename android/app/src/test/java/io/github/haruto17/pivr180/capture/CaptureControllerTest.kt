package io.github.haruto17.pivr180.capture

import io.github.haruto17.pivr180.protocol.AppMessage
import io.github.haruto17.pivr180.protocol.CameraSettings
import io.github.haruto17.pivr180.protocol.CaptureMode
import io.github.haruto17.pivr180.protocol.DeviceState
import io.github.haruto17.pivr180.protocol.ErrorCode
import io.github.haruto17.pivr180.protocol.ErrorMessage
import io.github.haruto17.pivr180.protocol.GetMode
import io.github.haruto17.pivr180.protocol.GetThumbnail
import io.github.haruto17.pivr180.protocol.LastCapture
import io.github.haruto17.pivr180.protocol.Mode
import io.github.haruto17.pivr180.protocol.Ok
import io.github.haruto17.pivr180.protocol.Settings
import io.github.haruto17.pivr180.protocol.Shutdown
import io.github.haruto17.pivr180.protocol.Shutter
import io.github.haruto17.pivr180.protocol.Side
import io.github.haruto17.pivr180.protocol.StartPreview
import io.github.haruto17.pivr180.protocol.Status
import io.github.haruto17.pivr180.protocol.StopPreview
import io.github.haruto17.pivr180.protocol.WhiteBalance
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

private const val CAPTURE_A = "20261128-010203-001"
private const val CAPTURE_B = "20261128-010210-002"

class CaptureControllerTest {
    private val deadlines = ManualDeadlineScheduler()
    private val sent = mutableListOf<AppMessage>()
    private val states = mutableListOf<CaptureState<String>>()
    private val state: CaptureState<String> get() = states.last()

    private fun controller(previewWanted: Boolean = true) =
        CaptureController<String>(send = { sent += it }, deadlines = deadlines, previewWanted = previewWanted) { states += it }

    private fun started(previewWanted: Boolean = true) =
        controller(previewWanted).also {
            it.start()
            sent.clear()
        }

    private fun idle(lastCapture: LastCapture? = null) =
        Status(DeviceState.IDLE, captureCount = 3, freeBytes = 1_000, lastCapture = lastCapture)

    private inline fun <reified M : AppMessage> sentOnly(): M = sent.filterIsInstance<M>().single()

    @Test
    fun `asks for the capture mode when connected`() {
        controller().start()

        assertEquals(listOf<AppMessage>(GetMode(1)), sent)
        assertEquals(ModeState.Loading, state.mode)
    }

    @Test
    fun `shows the capture mode the device answers with`() {
        val controller = controller()
        controller.start()

        controller.receive(Mode(1, CaptureMode.PHOTO))

        assertEquals(ModeState.Known(CaptureMode.PHOTO), state.mode)
    }

    @Test
    fun `shows the mode as unknown when the device does not answer`() {
        controller().start()

        deadlines.fireAll()

        assertEquals(ModeState.Unknown, state.mode)
        assertEquals(Notice(NoticeKind.MODE_FAILED, "no answer within $REQUEST_TIMEOUT"), state.notice)
    }

    @Test
    fun `shows the status the device sends`() {
        val controller = started()
        val status = Status(DeviceState.ERROR, "left camera failed", 3, 1_000, LastCapture(CAPTURE_A, syncWarning = true))

        controller.receive(status)

        assertEquals(status, state.status)
    }

    @Test
    fun `asks for both thumbnails of a new last capture`() {
        val controller = started()

        controller.receive(idle(LastCapture(CAPTURE_A, syncWarning = false)))

        assertEquals(
            listOf<AppMessage>(GetThumbnail(2, CAPTURE_A, Side.LEFT), GetThumbnail(3, CAPTURE_A, Side.RIGHT)),
            sent,
        )
        assertEquals(LastCaptureThumbnails<String>(CAPTURE_A, Thumbnail.Loading, Thumbnail.Loading), state.lastCapture)
    }

    @Test
    fun `does not ask again when the status repeats the same last capture`() {
        val controller = started()
        controller.receive(idle(LastCapture(CAPTURE_A, syncWarning = false)))
        sent.clear()

        controller.receive(idle(LastCapture(CAPTURE_A, syncWarning = true)))

        assertEquals(emptyList<AppMessage>(), sent)
    }

    @Test
    fun `puts each thumbnail on the side its request id asked for`() {
        val controller = started()
        controller.receive(idle(LastCapture(CAPTURE_A, syncWarning = false)))

        controller.receiveThumbnail(3, "right image")
        controller.receiveThumbnail(2, "left image")

        assertEquals(
            LastCaptureThumbnails(CAPTURE_A, Thumbnail.Loaded("left image"), Thumbnail.Loaded("right image")),
            state.lastCapture,
        )
    }

    @Test
    fun `drops a thumbnail of a capture that is no longer the last one`() {
        val controller = started()
        controller.receive(idle(LastCapture(CAPTURE_A, syncWarning = false)))
        controller.receive(idle(LastCapture(CAPTURE_B, syncWarning = false)))

        controller.receiveThumbnail(2, "old left image")

        assertEquals(LastCaptureThumbnails<String>(CAPTURE_B), state.lastCapture)
    }

    @Test
    fun `marks a thumbnail unavailable when the device cannot find it or it is not a JPEG`() {
        val controller = started()
        controller.receive(idle(LastCapture(CAPTURE_A, syncWarning = false)))

        controller.receive(ErrorMessage(2, ErrorCode.CAPTURE_NOT_FOUND, "no left image"))
        controller.receiveThumbnail(3, null)

        assertEquals(
            LastCaptureThumbnails<String>(
                CAPTURE_A,
                Thumbnail.Unavailable("capture_not_found: no left image"),
                Thumbnail.Unavailable("not a JPEG"),
            ),
            state.lastCapture,
        )
    }

    @Test
    fun `marks a thumbnail unavailable when it does not arrive in time`() {
        val controller = started()
        controller.receive(Mode(1, CaptureMode.PHOTO))
        controller.receive(idle(LastCapture(CAPTURE_A, syncWarning = false)))

        deadlines.fireAll()

        val noAnswer = Thumbnail.Unavailable("no answer within $REQUEST_TIMEOUT")
        assertEquals(LastCaptureThumbnails<String>(CAPTURE_A, noAnswer, noAnswer), state.lastCapture)
    }

    @Test
    fun `clears the thumbnails when the last capture is gone`() {
        val controller = started()
        controller.receive(idle(LastCapture(CAPTURE_A, syncWarning = false)))

        controller.receive(idle(lastCapture = null))

        assertNull(state.lastCapture)
    }

    @Test
    fun `waits for the status before allowing the shutter`() {
        val controller = started()

        controller.shutter()

        assertFalse(state.canShutter)
        assertEquals(emptyList<AppMessage>(), sent)
    }

    @Test
    fun `sends the shutter and allows it again once the device accepts it`() {
        val controller = started()
        controller.receive(idle())

        controller.shutter()
        val shutter = sentOnly<Shutter>()
        assertTrue(state.shutterPending)
        assertFalse(state.canShutter)

        controller.receive(Ok(shutter.id))

        assertFalse(state.shutterPending)
        assertTrue(state.canShutter)
    }

    @Test
    fun `takes the capture result from the status, not from the shutter ok`() {
        val controller = started()
        controller.receive(idle())
        controller.shutter()
        controller.receive(Ok(sentOnly<Shutter>().id))

        controller.receive(Status(DeviceState.CAPTURING, captureCount = 3, freeBytes = 1_000, lastCapture = null))
        assertFalse(state.canShutter)

        controller.receive(Status(DeviceState.IDLE, captureCount = 4, freeBytes = 900, lastCapture = LastCapture(CAPTURE_A, true)))
        assertEquals(4, state.status?.captureCount)
        assertEquals(CAPTURE_A, state.lastCapture?.captureId)
    }

    @Test
    fun `shows why the device refused the shutter`() {
        val controller = started()
        controller.receive(idle())
        controller.shutter()

        controller.receive(ErrorMessage(sentOnly<Shutter>().id, ErrorCode.CAMERAS_NOT_READY, "cameras are not ready"))

        assertEquals(Notice(NoticeKind.SHUTTER_FAILED, "cameras_not_ready: cameras are not ready"), state.notice)
        assertTrue(state.canShutter)
    }

    @Test
    fun `allows the shutter again when its ok does not arrive in time`() {
        val controller = started()
        controller.receive(Mode(1, CaptureMode.PHOTO))
        controller.receive(idle())
        controller.shutter()

        deadlines.fireAll()

        assertEquals(Notice(NoticeKind.SHUTTER_FAILED, "no answer within $REQUEST_TIMEOUT"), state.notice)
        assertTrue(state.canShutter)
    }

    @Test
    fun `dismisses a notice`() {
        val controller = started()
        controller.receive(ErrorMessage(null, ErrorCode.INVALID_MESSAGE, "not JSON"))
        assertEquals(Notice(NoticeKind.MESSAGE_REJECTED, "invalid_message: not JSON"), state.notice)

        controller.dismissNotice()

        assertNull(state.notice)
    }

    @Test
    fun `fails a request answered with the wrong kind of message`() {
        val controller = started()

        controller.receive(Settings(1, CameraSettings(0.0, WhiteBalance.AUTO, 1.0)))

        assertEquals(ModeState.Unknown, state.mode)
        assertEquals(Notice(NoticeKind.MODE_FAILED, "unexpected settings"), state.notice)
    }

    @Test
    fun `ignores an answer to a request it did not send`() {
        val controller = started()
        val before = state

        controller.receive(Ok(99))
        controller.receiveThumbnail(99, "image")

        assertEquals(before, state)
    }

    @Test
    fun `stops the preview when it is not wanted at the handshake`() {
        controller(previewWanted = false).start()

        assertEquals(StopPreview(2), sent.last())
    }

    @Test
    fun `does not ask for the preview the device already sends after the handshake`() {
        controller(previewWanted = true).start()

        assertTrue(sent.none { it is StartPreview || it is StopPreview })
    }

    @Test
    fun `stops the preview in the background and starts it again in the foreground`() {
        val controller = started()

        controller.setPreviewWanted(false)
        val stop = sentOnly<StopPreview>()
        controller.receive(Ok(stop.id))
        controller.setPreviewWanted(true)

        assertEquals(StartPreview(stop.id + 1), sent.last())
    }

    @Test
    fun `sends one preview request at a time and ends in the state wanted last`() {
        val controller = started()

        controller.setPreviewWanted(false)
        controller.setPreviewWanted(true)
        controller.setPreviewWanted(false)
        assertEquals(1, sent.size)

        controller.receive(Ok(sentOnly<StopPreview>().id))

        assertEquals(1, sent.size)
    }

    @Test
    fun `asks to start the preview after a stop answered once the app came back`() {
        val controller = started()

        controller.setPreviewWanted(false)
        controller.setPreviewWanted(true)
        controller.receive(Ok(sentOnly<StopPreview>().id))

        assertEquals(sentOnly<StartPreview>(), sent.last())
    }

    @Test
    fun `shows a refused preview request and does not retry it on its own`() {
        val controller = started()
        controller.setPreviewWanted(false)

        controller.receive(ErrorMessage(sentOnly<StopPreview>().id, ErrorCode.INTERNAL_ERROR, "boom"))

        assertEquals(Notice(NoticeKind.PREVIEW_FAILED, "internal_error: boom"), state.notice)
        assertEquals(1, sent.size)
    }

    @Test
    fun `asks the device to shut down once and stops allowing the shutter`() {
        val controller = started()
        controller.receive(idle())

        controller.shutdown()
        controller.shutdown()

        sentOnly<Shutdown>()
        assertEquals(ShutdownState.REQUESTED, state.shutdown)
        assertFalse(state.canShutter)
        assertFalse(state.canShutdown)
    }

    @Test
    fun `treats a shutdown as done when the connection ends after its ok`() {
        val controller = started()
        controller.shutdown()
        controller.receive(Ok(sentOnly<Shutdown>().id))
        assertEquals(ShutdownState.ACCEPTED, state.shutdown)

        controller.onDisconnected()

        assertEquals(ShutdownState.DONE, state.shutdown)
    }

    @Test
    fun `treats a shutdown as done when the connection ends before its ok`() {
        val controller = started()
        controller.shutdown()

        controller.onDisconnected()

        assertEquals(ShutdownState.DONE, state.shutdown)
        assertEquals(0, deadlines.pendingCount)
    }

    @Test
    fun `shows a refused shutdown and allows it again`() {
        val controller = started()
        controller.shutdown()

        controller.receive(ErrorMessage(sentOnly<Shutdown>().id, ErrorCode.INTERNAL_ERROR, "busy"))

        assertEquals(ShutdownState.NONE, state.shutdown)
        assertEquals(Notice(NoticeKind.SHUTDOWN_FAILED, "internal_error: busy"), state.notice)
        assertTrue(state.canShutdown)
    }

    @Test
    fun `does not treat a lost connection as a shutdown when none was asked for`() {
        val controller = started()

        controller.onDisconnected()

        assertEquals(ShutdownState.NONE, state.shutdown)
    }

    @Test
    fun `ignores everything after the connection ends`() {
        val controller = started()
        controller.receive(idle())
        controller.onDisconnected()
        val count = states.size

        controller.receive(idle(LastCapture(CAPTURE_A, syncWarning = false)))
        controller.shutter()
        controller.shutdown()
        controller.setPreviewWanted(false)
        deadlines.fireAll()

        assertEquals(emptyList<AppMessage>(), sent)
        assertEquals(count, states.size)
    }
}
