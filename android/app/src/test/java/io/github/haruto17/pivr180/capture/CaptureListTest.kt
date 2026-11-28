package io.github.haruto17.pivr180.capture

import io.github.haruto17.pivr180.protocol.AppMessage
import io.github.haruto17.pivr180.protocol.CaptureMode
import io.github.haruto17.pivr180.protocol.CaptureSummary
import io.github.haruto17.pivr180.protocol.Captures
import io.github.haruto17.pivr180.protocol.DeleteCapture
import io.github.haruto17.pivr180.protocol.ErrorCode
import io.github.haruto17.pivr180.protocol.ErrorMessage
import io.github.haruto17.pivr180.protocol.GetThumbnail
import io.github.haruto17.pivr180.protocol.ListCaptures
import io.github.haruto17.pivr180.protocol.Mode
import io.github.haruto17.pivr180.protocol.Ok
import io.github.haruto17.pivr180.protocol.Side
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

private fun captureId(n: Int) = "20261128-0102%02d-%03d".format(n % 60, n)

private fun summary(n: Int) = CaptureSummary(captureId(n), complete = true, syncWarning = false)

class CaptureListTest {
    private val deadlines = ManualDeadlineScheduler()
    private val sent = mutableListOf<AppMessage>()
    private val states = mutableListOf<CaptureState<String>>()
    private val list: CaptureListState<String> get() = states.last().captureList

    private fun started(
        maxInFlight: Int = MAX_LIST_THUMBNAILS_IN_FLIGHT,
        maxCached: Int = MAX_CACHED_LIST_THUMBNAILS,
    ) = CaptureController<String>(
        send = { sent += it },
        deadlines = deadlines,
        previewWanted = true,
        maxListThumbnailsInFlight = maxInFlight,
        maxCachedListThumbnails = maxCached,
    ) { states += it }.also {
        it.start()
        it.receive(Mode(1, CaptureMode.PHOTO))
        sent.clear()
    }

    private fun CaptureController<String>.loaded(vararg captures: Int) {
        refreshCaptures()
        receive(Captures(sent.filterIsInstance<ListCaptures>().last().id, captures.map(::summary)))
        sent.clear()
    }

    private fun thumbnailRequests() = sent.filterIsInstance<GetThumbnail>()

    private fun CaptureController<String>.answerThumbnails() {
        val requests = thumbnailRequests()
        sent.clear()
        requests.forEach { receiveThumbnail(it.id, "${it.captureId} ${it.side}") }
    }

    private fun item(n: Int) = list.items!!.single { it.summary.id == captureId(n) }

    @Test
    fun `asks for the captures and shows them in the order the device sends`() {
        val controller = started()

        controller.refreshCaptures()
        val request = sent.filterIsInstance<ListCaptures>().single()
        assertTrue(list.loading)
        controller.receive(Captures(request.id, listOf(summary(2), summary(1))))

        assertFalse(list.loading)
        assertEquals(listOf(CaptureListItem<String>(summary(2)), CaptureListItem(summary(1))), list.items)
    }

    @Test
    fun `does not ask for the captures again while they are loading`() {
        val controller = started()

        controller.refreshCaptures()
        controller.refreshCaptures()

        assertEquals(1, sent.size)
    }

    @Test
    fun `shows an empty list when there are no captures`() {
        val controller = started()

        controller.loaded()

        assertEquals(emptyList<CaptureListItem<String>>(), list.items)
    }

    @Test
    fun `keeps the old list and shows why when the captures cannot be loaded`() {
        val controller = started()
        controller.loaded(1)

        controller.refreshCaptures()
        controller.receive(ErrorMessage(sent.single().id, ErrorCode.INTERNAL_ERROR, "disk failed"))

        assertFalse(list.loading)
        assertEquals(listOf(CaptureListItem<String>(summary(1))), list.items)
        assertEquals(CaptureListNotice(CaptureListNoticeKind.LOAD_FAILED, null, "internal_error: disk failed"), list.notice)
    }

    @Test
    fun `allows loading again when the captures do not arrive in time`() {
        val controller = started()
        controller.refreshCaptures()

        deadlines.fireAll()
        assertEquals(CaptureListNotice(CaptureListNoticeKind.LOAD_FAILED, null, "no answer within $REQUEST_TIMEOUT"), list.notice)
        assertFalse(list.loading)
        controller.refreshCaptures()

        assertEquals(2, sent.filterIsInstance<ListCaptures>().size)
    }

    @Test
    fun `dismisses a list notice`() {
        val controller = started()
        controller.refreshCaptures()
        deadlines.fireAll()

        controller.dismissCaptureListNotice()

        assertNull(list.notice)
    }

    @Test
    fun `asks for both thumbnails of the visible captures only`() {
        val controller = started()
        controller.loaded(1, 2, 3)

        controller.showCaptures(listOf(captureId(2)))

        assertEquals(
            listOf(
                GetThumbnail(thumbnailRequests()[0].id, captureId(2), Side.LEFT),
                GetThumbnail(thumbnailRequests()[1].id, captureId(2), Side.RIGHT),
            ),
            thumbnailRequests(),
        )
    }

    @Test
    fun `asks for the thumbnails of captures shown before the list arrived`() {
        val controller = started()
        controller.showCaptures(listOf(captureId(1)))
        assertEquals(emptyList<GetThumbnail>(), thumbnailRequests())

        controller.refreshCaptures()
        controller.receive(Captures(sent.single().id, listOf(summary(1))))

        assertEquals(listOf(Side.LEFT, Side.RIGHT), thumbnailRequests().map { it.side })
    }

    @Test
    fun `puts each thumbnail on the capture and side its request id asked for`() {
        val controller = started()
        controller.loaded(1, 2)
        controller.showCaptures(listOf(captureId(1), captureId(2)))

        controller.answerThumbnails()

        assertEquals(Thumbnail.Loaded("${captureId(1)} LEFT"), item(1).left)
        assertEquals(Thumbnail.Loaded("${captureId(1)} RIGHT"), item(1).right)
        assertEquals(Thumbnail.Loaded("${captureId(2)} LEFT"), item(2).left)
        assertEquals(Thumbnail.Loaded("${captureId(2)} RIGHT"), item(2).right)
    }

    @Test
    fun `limits the thumbnails in flight and asks for the next one when one arrives`() {
        val controller = started(maxInFlight = 3)
        controller.loaded(1, 2, 3)
        controller.showCaptures(listOf(captureId(1), captureId(2), captureId(3)))
        val first = thumbnailRequests()
        assertEquals(3, first.size)
        sent.clear()

        controller.receiveThumbnail(first[0].id, "image")

        assertEquals(listOf(GetThumbnail(thumbnailRequests().single().id, captureId(2), Side.RIGHT)), thumbnailRequests())
    }

    @Test
    fun `does not ask for the thumbnails of captures scrolled away before their turn`() {
        val controller = started(maxInFlight = 2)
        controller.loaded(1, 2, 3)
        controller.showCaptures(listOf(captureId(1), captureId(2)))
        controller.showCaptures(listOf(captureId(3)))
        val first = thumbnailRequests()
        sent.clear()

        first.forEach { controller.receiveThumbnail(it.id, "image") }

        assertEquals(listOf(captureId(3), captureId(3)), thumbnailRequests().map { it.captureId })
    }

    @Test
    fun `does not ask again for thumbnails it already has`() {
        val controller = started()
        controller.loaded(1)
        controller.showCaptures(listOf(captureId(1)))
        controller.answerThumbnails()

        controller.showCaptures(emptyList())
        controller.showCaptures(listOf(captureId(1)))

        assertEquals(0, sent.size)
    }

    @Test
    fun `marks a thumbnail unavailable when the device cannot find it, it is not a JPEG or it does not arrive in time`() {
        val controller = started()
        controller.loaded(1, 2)
        controller.showCaptures(listOf(captureId(1), captureId(2)))
        val (left1, right1, left2) = thumbnailRequests()

        controller.receive(ErrorMessage(left1.id, ErrorCode.CAPTURE_NOT_FOUND, "no left image"))
        controller.receiveThumbnail(right1.id, null)
        controller.receiveThumbnail(left2.id, "image")
        deadlines.fireAll()

        assertEquals(Thumbnail.Unavailable("capture_not_found: no left image"), item(1).left)
        assertEquals(Thumbnail.Unavailable("not a JPEG"), item(1).right)
        assertEquals(Thumbnail.Loaded("image"), item(2).left)
        assertEquals(Thumbnail.Unavailable("no answer within $REQUEST_TIMEOUT"), item(2).right)
    }

    @Test
    fun `does not ask again for an unavailable thumbnail until the list is refreshed`() {
        val controller = started()
        controller.loaded(1)
        controller.showCaptures(listOf(captureId(1)))
        thumbnailRequests().forEach { controller.receive(ErrorMessage(it.id, ErrorCode.CAPTURE_NOT_FOUND, "gone")) }
        sent.clear()

        controller.showCaptures(listOf(captureId(1)))
        assertEquals(0, sent.size)

        controller.refreshCaptures()
        controller.receive(Captures(sent.single().id, listOf(summary(1))))
        assertEquals(2, thumbnailRequests().size)
    }

    @Test
    fun `keeps the loaded thumbnails of captures still listed after a refresh`() {
        val controller = started()
        controller.loaded(1, 2)
        controller.showCaptures(listOf(captureId(1), captureId(2)))
        controller.answerThumbnails()

        controller.loaded(3, 1)

        assertEquals(Thumbnail.Loaded("${captureId(1)} LEFT"), item(1).left)
        assertEquals(listOf(captureId(3), captureId(1)), list.items!!.map { it.summary.id })
    }

    @Test
    fun `drops the least recently visible thumbnails beyond the limit but keeps the visible ones`() {
        val controller = started(maxCached = 4)
        controller.loaded(1, 2, 3)
        controller.showCaptures(listOf(captureId(1)))
        controller.answerThumbnails()
        controller.showCaptures(listOf(captureId(2)))
        controller.answerThumbnails()
        controller.showCaptures(listOf(captureId(1)))
        controller.showCaptures(listOf(captureId(3)))

        controller.answerThumbnails()

        assertEquals(Thumbnail.Loading, item(2).left)
        assertEquals(Thumbnail.Loading, item(2).right)
        assertEquals(Thumbnail.Loaded("${captureId(1)} LEFT"), item(1).left)
        assertEquals(Thumbnail.Loaded("${captureId(3)} RIGHT"), item(3).right)
    }

    @Test
    fun `keeps every visible thumbnail even beyond the limit`() {
        val controller = started(maxCached = 2)
        controller.loaded(1, 2)
        controller.showCaptures(listOf(captureId(1), captureId(2)))

        controller.answerThumbnails()

        assertTrue(list.items!!.all { it.left is Thumbnail.Loaded && it.right is Thumbnail.Loaded })
    }

    @Test
    fun `asks the device to delete a capture once and marks it as being deleted`() {
        val controller = started()
        controller.loaded(1)

        controller.deleteCapture(captureId(1))
        controller.deleteCapture(captureId(1))

        assertEquals(listOf<AppMessage>(DeleteCapture(sent.single().id, captureId(1))), sent)
        assertTrue(item(1).deleting)
    }

    @Test
    fun `does not delete a capture that is not listed`() {
        val controller = started()
        controller.loaded(1)

        controller.deleteCapture(captureId(2))

        assertEquals(0, sent.size)
    }

    @Test
    fun `removes a capture from the list once the device deletes it`() {
        val controller = started()
        controller.loaded(1, 2)
        controller.showCaptures(listOf(captureId(1)))
        controller.answerThumbnails()

        controller.deleteCapture(captureId(1))
        controller.receive(Ok(sent.single().id))

        assertEquals(listOf(CaptureListItem<String>(summary(2))), list.items)
        assertNull(list.notice)
    }

    @Test
    fun `removes a capture the device no longer has and says so`() {
        val controller = started()
        controller.loaded(1, 2)

        controller.deleteCapture(captureId(1))
        controller.receive(ErrorMessage(sent.single().id, ErrorCode.CAPTURE_NOT_FOUND, "no capture"))

        assertEquals(listOf(captureId(2)), list.items!!.map { it.summary.id })
        assertEquals(
            CaptureListNotice(CaptureListNoticeKind.ALREADY_DELETED, captureId(1), "capture_not_found: no capture"),
            list.notice,
        )
    }

    @Test
    fun `keeps a capture the device failed to delete and shows why`() {
        val controller = started()
        controller.loaded(1)

        controller.deleteCapture(captureId(1))
        controller.receive(ErrorMessage(sent.single().id, ErrorCode.INTERNAL_ERROR, "read-only"))

        assertFalse(item(1).deleting)
        assertEquals(CaptureListNotice(CaptureListNoticeKind.DELETE_FAILED, captureId(1), "internal_error: read-only"), list.notice)
    }

    @Test
    fun `allows deleting again when the delete is not answered in time`() {
        val controller = started()
        controller.loaded(1)
        controller.deleteCapture(captureId(1))

        deadlines.fireAll()
        assertFalse(item(1).deleting)
        assertEquals(
            CaptureListNotice(CaptureListNoticeKind.DELETE_FAILED, captureId(1), "no answer within $REQUEST_TIMEOUT"),
            list.notice,
        )
        controller.deleteCapture(captureId(1))

        assertEquals(2, sent.filterIsInstance<DeleteCapture>().size)
    }

    @Test
    fun `does not ask for thumbnails of a capture being deleted`() {
        val controller = started()
        controller.loaded(1)
        controller.deleteCapture(captureId(1))
        sent.clear()

        controller.showCaptures(listOf(captureId(1)))

        assertEquals(0, sent.size)
    }

    @Test
    fun `frees the thumbnail slots of a deleted capture when their answers arrive`() {
        val controller = started(maxInFlight = 2)
        controller.loaded(1, 2)
        controller.showCaptures(listOf(captureId(1), captureId(2)))
        val thumbnails = thumbnailRequests()
        controller.deleteCapture(captureId(1))
        controller.receive(Ok(sent.filterIsInstance<DeleteCapture>().single().id))
        controller.showCaptures(listOf(captureId(2)))
        sent.clear()

        thumbnails.forEach { controller.receive(ErrorMessage(it.id, ErrorCode.CAPTURE_NOT_FOUND, "no capture")) }

        assertEquals(listOf(captureId(2), captureId(2)), thumbnailRequests().map { it.captureId })
        assertEquals(listOf(CaptureListItem<String>(summary(2))), list.items)
    }

    @Test
    fun `ignores the list after the connection ends`() {
        val controller = started()
        controller.loaded(1)
        controller.showCaptures(listOf(captureId(1)))
        controller.onDisconnected()
        sent.clear()
        val count = states.size

        controller.refreshCaptures()
        controller.showCaptures(listOf(captureId(1)))
        controller.deleteCapture(captureId(1))
        controller.dismissCaptureListNotice()
        deadlines.fireAll()

        assertEquals(emptyList<AppMessage>(), sent)
        assertEquals(count, states.size)
        assertEquals(0, deadlines.pendingCount)
    }
}
