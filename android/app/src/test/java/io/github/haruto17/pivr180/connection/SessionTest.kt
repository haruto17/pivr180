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
import java.util.concurrent.TimeUnit
import kotlin.concurrent.thread
import kotlin.time.Duration
import kotlin.time.Duration.Companion.milliseconds

class SessionTest {
    private val welcome = """{"type":"welcome","id":0,"protocol_version":2,"software_version":"0.2.0"}"""
    private val status =
        """{"type":"status","state":"idle","capture_count":0,"free_bytes":1,"last_capture":null}"""

    @Test
    fun `sends hello with the protocol and app versions first`() {
        val output = ByteArrayOutputStream()

        runSession(AccessoryChannel(ByteArrayInputStream(ByteArray(0)), output), "0.1.0", close = {}, ManualDeadlineScheduler()) {}

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
        val states = statesWhileReading(jsonFrame(welcome.replace("\"protocol_version\":2", "\"protocol_version\":1")))

        assertEquals(
            listOf(
                ConnectionState.Connecting,
                ConnectionState.Failed("device speaks protocol version 1, app speaks 2"),
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
    fun `fails and closes the accessory when the deadline passes while waiting for welcome`() {
        val input = StallingInputStream(ByteArray(0))
        val deadlines = ManualDeadlineScheduler()
        val states = CopyOnWriteArrayList<ConnectionState>()

        val session = startSession(input, deadlines, 100.milliseconds) { states += it }
        try {
            assertTrue("session did not block on read", input.awaitBlocked())

            deadlines.fire()

            session.join(JOIN_TIMEOUT_MILLIS)
            assertFalse("session did not return after close", session.isAlive)
            assertEquals(
                listOf(ConnectionState.Connecting, ConnectionState.Failed("no answer to hello within 100ms")),
                states,
            )
            assertTrue(input.closed)
        } finally {
            input.close()
            session.join(JOIN_TIMEOUT_MILLIS)
        }
    }

    @Test
    fun `schedules the deadline HANDSHAKE_TIMEOUT after hello by default`() {
        val deadlines = ManualDeadlineScheduler()

        runSession(AccessoryChannel(ByteArrayInputStream(ByteArray(0)), ByteArrayOutputStream()), "0.1.0", close = {}, deadlines) {}

        assertEquals(HANDSHAKE_TIMEOUT, deadlines.delay)
    }

    @Test
    fun `stays connected when the deadline passes after welcome`() {
        val input = StallingInputStream(jsonFrame(welcome))
        val deadlines = ManualDeadlineScheduler()
        val states = CopyOnWriteArrayList<ConnectionState>()
        val connected = CountDownLatch(1)

        val session =
            startSession(input, deadlines) {
                states += it
                if (it is ConnectionState.Connected) connected.countDown()
            }
        try {
            assertTrue("session did not connect", connected.await(JOIN_TIMEOUT_MILLIS, TimeUnit.MILLISECONDS))

            deadlines.fire()

            assertEquals(listOf(ConnectionState.Connecting, ConnectionState.Connected("0.2.0")), states)
            assertTrue(deadlines.cancelled)
            assertFalse(input.closed)
        } finally {
            input.close()
            session.join(JOIN_TIMEOUT_MILLIS)
        }
        assertEquals(ConnectionState.Disconnected, states.last())
    }

    private fun startSession(
        input: InputStream,
        deadlines: DeadlineScheduler,
        handshakeTimeout: Duration = HANDSHAKE_TIMEOUT,
        onState: (ConnectionState) -> Unit,
    ): Thread =
        thread(isDaemon = true) {
            runSession(AccessoryChannel(input, ByteArrayOutputStream()), "0.1.0", input::close, deadlines, handshakeTimeout, onState)
        }

    private fun statesWhileReading(bytes: ByteArray): List<ConnectionState> {
        val states = mutableListOf<ConnectionState>()
        runSession(AccessoryChannel(ByteArrayInputStream(bytes), ByteArrayOutputStream()), "0.1.0", close = {}, ManualDeadlineScheduler()) {
            states += it
        }
        return states
    }
}

private class StallingInputStream(
    bytes: ByteArray,
) : InputStream() {
    private val available = ByteArrayInputStream(bytes)
    private val closedLatch = CountDownLatch(1)
    private val blockedLatch = CountDownLatch(1)

    val closed: Boolean get() = closedLatch.count == 0L

    fun awaitBlocked(): Boolean = blockedLatch.await(JOIN_TIMEOUT_MILLIS, TimeUnit.MILLISECONDS)

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
        blockedLatch.countDown()
        closedLatch.await()
        throw IOException("stream closed")
    }

    override fun close() {
        closedLatch.countDown()
    }
}

private class ManualDeadlineScheduler : DeadlineScheduler {
    @Volatile var delay: Duration? = null

    @Volatile var cancelled = false

    @Volatile private var action: (() -> Unit)? = null

    override fun schedule(
        delay: Duration,
        action: () -> Unit,
    ): () -> Unit {
        this.delay = delay
        this.action = action
        return { cancelled = true }
    }

    fun fire() {
        checkNotNull(action) { "no deadline scheduled" }()
    }
}

private const val JOIN_TIMEOUT_MILLIS = 5_000L
