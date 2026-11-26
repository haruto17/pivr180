package io.github.haruto17.pivr180.connection

import io.github.haruto17.pivr180.protocol.AccessoryChannel
import io.github.haruto17.pivr180.protocol.AppMessage
import io.github.haruto17.pivr180.protocol.FrameReader
import io.github.haruto17.pivr180.protocol.Hello
import io.github.haruto17.pivr180.protocol.PROTOCOL_VERSION
import io.github.haruto17.pivr180.protocol.hex
import io.github.haruto17.pivr180.protocol.jsonFrame
import io.github.haruto17.pivr180.protocol.protocolJson
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.io.IOException
import java.io.InputStream
import java.util.concurrent.CopyOnWriteArrayList
import java.util.concurrent.CountDownLatch
import kotlin.concurrent.thread
import kotlin.time.Duration.Companion.milliseconds
import kotlin.time.TimeSource

class SessionTest {
    private val welcome = """{"type":"welcome","id":0,"protocol_version":1,"software_version":"0.2.0"}"""
    private val status =
        """{"type":"status","state":"idle","capture_count":0,"free_bytes":1,"last_capture":null}"""

    @Test
    fun `sends hello with the protocol and app versions first`() {
        val output = ByteArrayOutputStream()

        runSession(AccessoryChannel(ByteArrayInputStream(ByteArray(0)), output), "0.1.0", close = {}) {}

        val frame = FrameReader(ByteArrayInputStream(output.toByteArray())).read()
        val hello = protocolJson.decodeFromString(AppMessage.serializer(), frame.body.decodeToString())
        assertEquals(Hello(HELLO_REQUEST_ID, PROTOCOL_VERSION, "0.1.0"), hello)
    }

    @Test
    fun `is connected after welcome and disconnected when the stream ends`() {
        val states = statesWhileReading(jsonFrame(welcome) + jsonFrame(status) + hex("00000002 02 ffd8"))

        assertEquals(
            listOf(ConnectionState.Connecting, ConnectionState.Connected("0.2.0"), ConnectionState.Disconnected),
            states,
        )
    }

    @Test
    fun `fails when device rejects the protocol version`() {
        val error = """{"type":"error","id":0,"code":"unsupported_protocol_version","message":"device speaks 2"}"""

        val states = statesWhileReading(jsonFrame(error))

        assertEquals(
            listOf(
                ConnectionState.Connecting,
                ConnectionState.Failed("unsupported_protocol_version: device speaks 2"),
            ),
            states,
        )
    }

    @Test
    fun `fails when welcome carries another protocol version`() {
        val states = statesWhileReading(jsonFrame(welcome.replace("\"protocol_version\":1", "\"protocol_version\":2")))

        assertEquals(
            listOf(
                ConnectionState.Connecting,
                ConnectionState.Failed("device speaks protocol version 2, app speaks 1"),
            ),
            states,
        )
    }

    @Test
    fun `fails when the stream is corrupted`() {
        val states = statesWhileReading(jsonFrame(welcome) + hex("ffffffff 01"))

        assertEquals(
            listOf(
                ConnectionState.Connecting,
                ConnectionState.Connected("0.2.0"),
                ConnectionState.Failed("frame body of 4294967295 bytes exceeds 4194304"),
            ),
            states,
        )
    }

    @Test
    fun `is disconnected when the stream ends before welcome`() {
        val states = statesWhileReading(ByteArray(0))

        assertEquals(listOf(ConnectionState.Connecting, ConnectionState.Disconnected), states)
    }

    @Test
    fun `fails and closes the accessory when device does not answer hello within the deadline`() {
        val input = StallingInputStream(ByteArray(0))
        val states = CopyOnWriteArrayList<ConnectionState>()

        runSession(AccessoryChannel(input, ByteArrayOutputStream()), "0.1.0", close = input::close, 100.milliseconds) { states += it }

        assertEquals(
            listOf(ConnectionState.Connecting, ConnectionState.Failed("no answer to hello within 100ms")),
            states,
        )
        assertTrue(input.closed)
    }

    @Test
    fun `waits HANDSHAKE_TIMEOUT for welcome by default`() {
        val input = StallingInputStream(ByteArray(0))
        val states = CopyOnWriteArrayList<ConnectionState>()
        val started = TimeSource.Monotonic.markNow()

        runSession(AccessoryChannel(input, ByteArrayOutputStream()), "0.1.0", close = input::close) { states += it }

        assertTrue(started.elapsedNow() >= HANDSHAKE_TIMEOUT)
        assertEquals(ConnectionState.Failed("no answer to hello within $HANDSHAKE_TIMEOUT"), states.last())
    }

    @Test
    fun `stays connected past the deadline once welcome arrives`() {
        val input = StallingInputStream(jsonFrame(welcome))
        val states = CopyOnWriteArrayList<ConnectionState>()
        val session =
            thread {
                runSession(AccessoryChannel(input, ByteArrayOutputStream()), "0.1.0", close = input::close, 100.milliseconds) {
                    states += it
                }
            }

        Thread.sleep(500)
        assertEquals(listOf(ConnectionState.Connecting, ConnectionState.Connected("0.2.0")), states)
        assertFalse(input.closed)

        input.close()
        session.join(5_000)
        assertEquals(ConnectionState.Disconnected, states.last())
    }

    private fun statesWhileReading(bytes: ByteArray): List<ConnectionState> {
        val states = mutableListOf<ConnectionState>()
        runSession(AccessoryChannel(ByteArrayInputStream(bytes), ByteArrayOutputStream()), "0.1.0", close = {}) { states += it }
        return states
    }
}

private class StallingInputStream(
    bytes: ByteArray,
) : InputStream() {
    private val available = ByteArrayInputStream(bytes)
    private val closedLatch = CountDownLatch(1)

    val closed: Boolean get() = closedLatch.count == 0L

    override fun read(): Int {
        val buffer = ByteArray(1)
        return if (read(buffer, 0, 1) < 0) -1 else buffer[0].toInt() and 0xff
    }

    override fun read(
        b: ByteArray,
        off: Int,
        len: Int,
    ): Int {
        if (available.available() > 0) return available.read(b, off, len)
        closedLatch.await()
        throw IOException("stream closed")
    }

    override fun close() {
        closedLatch.countDown()
    }
}
