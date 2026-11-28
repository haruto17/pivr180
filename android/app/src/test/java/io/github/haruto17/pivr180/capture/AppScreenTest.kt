package io.github.haruto17.pivr180.capture

import io.github.haruto17.pivr180.connection.ConnectionState
import org.junit.Assert.assertEquals
import org.junit.Test

class AppScreenTest {
    private val capture = CaptureState<String>()

    @Test
    fun `shows the connection until the handshake is done`() {
        assertEquals(AppScreen.Connection(ConnectionState.Connecting), appScreen(ConnectionState.Connecting, capture))
        assertEquals(AppScreen.Connection(ConnectionState.Disconnected), appScreen<String>(ConnectionState.Disconnected, null))
    }

    @Test
    fun `shows the capture screen while connected`() {
        assertEquals(AppScreen.Capture(capture), appScreen(ConnectionState.Connected("0.2.0"), capture))
    }

    @Test
    fun `shows the connection when connected before the capture state exists`() {
        val connected = ConnectionState.Connected("0.2.0")

        assertEquals(AppScreen.Connection(connected), appScreen<String>(connected, null))
    }

    @Test
    fun `shows the shutdown as done instead of a lost connection`() {
        val shutDown = capture.copy(shutdown = ShutdownState.DONE)

        assertEquals(AppScreen.ShutDown, appScreen(ConnectionState.Disconnected, shutDown))
        assertEquals(AppScreen.ShutDown, appScreen(ConnectionState.Failed("frame body too large"), shutDown))
    }

    @Test
    fun `shows a lost connection while a shutdown is not done`() {
        val requested = capture.copy(shutdown = ShutdownState.REQUESTED)

        assertEquals(AppScreen.Connection(ConnectionState.Disconnected), appScreen(ConnectionState.Disconnected, requested))
    }
}
