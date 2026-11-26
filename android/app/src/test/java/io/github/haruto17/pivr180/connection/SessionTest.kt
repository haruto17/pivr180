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
import org.junit.Test
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream

class SessionTest {
    private val welcome = """{"type":"welcome","id":0,"protocol_version":1,"software_version":"0.2.0"}"""
    private val status =
        """{"type":"status","state":"idle","capture_count":0,"free_bytes":1,"last_capture":null}"""

    @Test
    fun `sends hello with the protocol and app versions first`() {
        val output = ByteArrayOutputStream()

        runSession(AccessoryChannel(ByteArrayInputStream(ByteArray(0)), output), "0.1.0") {}

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

    private fun statesWhileReading(bytes: ByteArray): List<ConnectionState> {
        val states = mutableListOf<ConnectionState>()
        runSession(AccessoryChannel(ByteArrayInputStream(bytes), ByteArrayOutputStream()), "0.1.0") { states += it }
        return states
    }
}
