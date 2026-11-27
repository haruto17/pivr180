package io.github.haruto17.pivr180.protocol

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Test
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream

class AccessoryChannelTest {
    @Test
    fun `sends a request as a JSON frame`() {
        val output = ByteArrayOutputStream()

        AccessoryChannel(ByteArrayInputStream(ByteArray(0)), output).send(Shutter(7))

        assertArrayEquals(hex("00000019 01") + """{"type":"shutter","id":7}""".encodeToByteArray(), output.toByteArray())
    }

    @Test
    fun `receives a JSON frame as a device message`() {
        val incoming = channelReading(jsonFrame("""{"type":"ok","id":2}""")).receive()

        assertEquals(Incoming.Message(Ok(2)), incoming)
    }

    @Test
    fun `receives a preview frame as JPEG bytes`() {
        val incoming = channelReading(hex("00000002 02 ffd8")).receive() as Incoming.Preview

        assertArrayEquals(hex("ffd8"), incoming.jpeg)
    }

    @Test
    fun `receives a thumbnail frame as the request id and JPEG bytes`() {
        val incoming = channelReading(hex("00000006 03 00000007 ffd8")).receive() as Incoming.Thumbnail

        assertEquals(7, incoming.id)
        assertArrayEquals(hex("ffd8"), incoming.jpeg)
    }

    @Test
    fun `skips frames of unknown types`() {
        val incoming = channelReading(hex("00000003 7f 010203") + jsonFrame("""{"type":"ok","id":2}""")).receive()

        assertEquals(Incoming.Message(Ok(2)), incoming)
    }

    @Test
    fun `rejects a JSON frame that is not a device message`() {
        assertThrows(MalformedFrameException::class.java) {
            channelReading(jsonFrame("""{"type":"shutter","id":7}""")).receive()
        }
    }

    @Test
    fun `rejects a JSON frame that is not UTF-8`() {
        assertThrows(MalformedFrameException::class.java) {
            channelReading(hex("00000001 01 ff")).receive()
        }
    }

    @Test
    fun `rejects a thumbnail frame too short for the id`() {
        assertThrows(MalformedFrameException::class.java) {
            channelReading(hex("00000003 03 000000")).receive()
        }
    }

    private fun channelReading(bytes: ByteArray) = AccessoryChannel(ByteArrayInputStream(bytes), ByteArrayOutputStream())
}

fun jsonFrame(json: String): ByteArray = encodeFrame(Frame(FRAME_TYPE_JSON, json.encodeToByteArray()))
