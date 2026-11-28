package io.github.haruto17.pivr180.capture

import io.github.haruto17.pivr180.protocol.AppMessage
import io.github.haruto17.pivr180.protocol.CameraSettings
import io.github.haruto17.pivr180.protocol.CaptureMode
import io.github.haruto17.pivr180.protocol.ErrorCode
import io.github.haruto17.pivr180.protocol.ErrorMessage
import io.github.haruto17.pivr180.protocol.GetSettings
import io.github.haruto17.pivr180.protocol.Mode
import io.github.haruto17.pivr180.protocol.Ok
import io.github.haruto17.pivr180.protocol.SetSettings
import io.github.haruto17.pivr180.protocol.Settings
import io.github.haruto17.pivr180.protocol.WhiteBalance
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

private val DEFAULTS = CameraSettings(0.0, WhiteBalance.AUTO, 1.0)
private val BRIGHTER = CameraSettings(0.5, WhiteBalance.AUTO, 1.0)
private val BRIGHTEST = CameraSettings(1.5, WhiteBalance.AUTO, 1.0)
private val CLOUDY = CameraSettings(0.0, WhiteBalance.CLOUDY, 1.2)

class CaptureControllerSettingsTest {
    private val deadlines = ManualDeadlineScheduler()
    private val sent = mutableListOf<AppMessage>()
    private val states = mutableListOf<CaptureState<String>>()
    private val settings: SettingsState get() = states.last().settings

    private val controller =
        CaptureController<String>(send = { sent += it }, deadlines = deadlines, previewWanted = true) { states += it }

    private fun started() =
        controller.also {
            it.start()
            it.receive(Mode(1, CaptureMode.PHOTO))
            sent.clear()
        }

    private fun loaded(current: CameraSettings = DEFAULTS) =
        started().also {
            it.loadSettings()
            it.receive(Settings(sentOnly<GetSettings>().id, current))
            sent.clear()
        }

    private inline fun <reified M : AppMessage> sentOnly(): M = sent.filterIsInstance<M>().single()

    @Test
    fun `does not load the settings until asked`() {
        started()

        assertEquals(SettingsState.NotLoaded, states.last().settings)
        assertTrue(sent.isEmpty())
    }

    @Test
    fun `loads the settings and shows what the device answers with`() {
        val controller = started()

        controller.loadSettings()
        assertEquals(SettingsState.Loading, settings)

        controller.receive(Settings(sentOnly<GetSettings>().id, CLOUDY))

        assertEquals(SettingsState.Loaded(CLOUDY), settings)
    }

    @Test
    fun `does not load the settings again while loading or once loaded`() {
        val controller = started()

        controller.loadSettings()
        controller.loadSettings()
        controller.receive(Settings(sentOnly<GetSettings>().id, DEFAULTS))
        controller.loadSettings()

        assertEquals(1, sent.size)
    }

    @Test
    fun `shows why the settings could not be loaded and loads them again when asked`() {
        val controller = started()
        controller.loadSettings()

        controller.receive(ErrorMessage(sentOnly<GetSettings>().id, ErrorCode.INTERNAL_ERROR, "boom"))
        assertEquals(SettingsState.Unavailable(UnavailableReason.LOAD_FAILED, "internal_error: boom"), settings)

        sent.clear()
        controller.loadSettings()
        controller.receive(Settings(sentOnly<GetSettings>().id, DEFAULTS))

        assertEquals(SettingsState.Loaded(DEFAULTS), settings)
    }

    @Test
    fun `shows the settings as not loaded when the device does not answer`() {
        val controller = started()
        controller.loadSettings()

        deadlines.fireAll()

        assertEquals(SettingsState.Unavailable(UnavailableReason.LOAD_FAILED, "no answer within $REQUEST_TIMEOUT"), settings)
    }

    @Test
    fun `does not send settings before they are loaded`() {
        val controller = started()

        controller.changeSettings(BRIGHTER)

        assertTrue(sent.isEmpty())
        assertEquals(SettingsState.NotLoaded, settings)
    }

    @Test
    fun `sends changed settings and shows them as saved once the device answers`() {
        val controller = loaded()

        controller.changeSettings(BRIGHTER)
        val set = sentOnly<SetSettings>()
        assertEquals(BRIGHTER, set.settings)
        assertEquals(SettingsState.Loaded(BRIGHTER, saving = true), settings)

        controller.receive(Settings(set.id, BRIGHTER))

        assertEquals(SettingsState.Loaded(BRIGHTER, result = SaveResult.Saved), settings)
    }

    @Test
    fun `does not send settings that are the same as the device's`() {
        val controller = loaded()

        controller.changeSettings(DEFAULTS)

        assertTrue(sent.isEmpty())
        assertEquals(SettingsState.Loaded(DEFAULTS), settings)
    }

    @Test
    fun `sends one change at a time and only the latest one after the device answers`() {
        val controller = loaded()

        controller.changeSettings(BRIGHTER)
        controller.changeSettings(CLOUDY)
        controller.changeSettings(BRIGHTEST)
        val first = sentOnly<SetSettings>()
        assertEquals(BRIGHTER, first.settings)
        assertEquals(SettingsState.Loaded(BRIGHTEST, saving = true), settings)

        sent.clear()
        controller.receive(Settings(first.id, BRIGHTER))
        val second = sentOnly<SetSettings>()
        assertEquals(BRIGHTEST, second.settings)
        assertEquals(SettingsState.Loaded(BRIGHTEST, saving = true), settings)

        controller.receive(Settings(second.id, BRIGHTEST))

        assertEquals(1, sent.size)
        assertEquals(SettingsState.Loaded(BRIGHTEST, result = SaveResult.Saved), settings)
    }

    @Test
    fun `sends the settings again when changed back while the device applies another change`() {
        val controller = loaded()

        controller.changeSettings(BRIGHTER)
        controller.changeSettings(DEFAULTS)
        val first = sentOnly<SetSettings>()
        sent.clear()
        controller.receive(Settings(first.id, BRIGHTER))

        assertEquals(DEFAULTS, sentOnly<SetSettings>().settings)
    }

    @Test
    fun `shows why the device refused the settings and goes back to the device's`() {
        val controller = loaded()
        controller.changeSettings(BRIGHTER)
        controller.changeSettings(BRIGHTEST)

        controller.receive(ErrorMessage(sentOnly<SetSettings>().id, ErrorCode.CAMERAS_NOT_READY, "cameras are not ready"))

        assertEquals(
            SettingsState.Loaded(DEFAULTS, result = SaveResult.Failed("cameras_not_ready: cameras are not ready")),
            settings,
        )
        assertEquals(1, sent.size)
    }

    @Test
    fun `sends a change made after a refused one`() {
        val controller = loaded()
        controller.changeSettings(BRIGHTER)
        controller.receive(ErrorMessage(sentOnly<SetSettings>().id, ErrorCode.CAMERAS_NOT_READY, "cameras are not ready"))
        sent.clear()

        controller.changeSettings(CLOUDY)

        assertEquals(CLOUDY, sentOnly<SetSettings>().settings)
        assertEquals(SettingsState.Loaded(CLOUDY, saving = true), settings)
    }

    @Test
    fun `treats the settings as unknown when the device does not answer a change`() {
        val controller = loaded()
        controller.changeSettings(BRIGHTER)
        val set = sentOnly<SetSettings>()

        deadlines.fireAll()
        assertEquals(SettingsState.Unavailable(UnavailableReason.SAVE_UNCONFIRMED, "no answer within $REQUEST_TIMEOUT"), settings)

        controller.receive(Settings(set.id, BRIGHTER))
        assertEquals(SettingsState.Unavailable(UnavailableReason.SAVE_UNCONFIRMED, "no answer within $REQUEST_TIMEOUT"), settings)

        sent.clear()
        controller.loadSettings()
        controller.receive(Settings(sentOnly<GetSettings>().id, BRIGHTER))

        assertEquals(SettingsState.Loaded(BRIGHTER), settings)
    }

    @Test
    fun `fails a settings request answered with the wrong kind of message`() {
        val controller = loaded()
        controller.changeSettings(BRIGHTER)

        controller.receive(Ok(sentOnly<SetSettings>().id))

        assertEquals(SettingsState.Loaded(DEFAULTS, result = SaveResult.Failed("unexpected ok")), settings)
    }

    @Test
    fun `keeps the capture notice for settings failures`() {
        val controller = loaded()
        controller.changeSettings(BRIGHTER)

        controller.receive(ErrorMessage(sentOnly<SetSettings>().id, ErrorCode.INTERNAL_ERROR, "boom"))

        assertNull(states.last().notice)
    }

    @Test
    fun `stops sending settings after the connection ends`() {
        val controller = loaded()
        controller.changeSettings(BRIGHTER)
        val set = sentOnly<SetSettings>()
        controller.changeSettings(BRIGHTEST)

        controller.onDisconnected()
        val count = states.size
        controller.receive(Settings(set.id, BRIGHTER))
        controller.changeSettings(CLOUDY)
        controller.loadSettings()
        deadlines.fireAll()

        assertEquals(listOf<AppMessage>(set), sent)
        assertEquals(count, states.size)
        assertEquals(0, deadlines.pendingCount)
    }
}
