package io.github.haruto17.pivr180.protocol

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Test
import java.io.ByteArrayInputStream
import java.io.EOFException
import java.io.InputStream

class FrameTest {
    private val shutterJson = """{"type":"shutter","id":7}"""
    private val shutterFrame =
        hex("00000019 01") + shutterJson.encodeToByteArray()

    @Test
    fun `encodes the length big-endian, then the type, then the body`() {
        assertArrayEquals(shutterFrame, encodeFrame(Frame(FRAME_TYPE_JSON, shutterJson.encodeToByteArray())))
    }

    @Test
    fun `encodes an empty body with length zero`() {
        assertArrayEquals(hex("00000000 02"), encodeFrame(Frame(FRAME_TYPE_PREVIEW, ByteArray(0))))
    }

    @Test
    fun `refuses to encode a body over 4 MiB`() {
        assertThrows(IllegalArgumentException::class.java) {
            encodeFrame(Frame(FRAME_TYPE_PREVIEW, ByteArray(MAX_FRAME_BODY_SIZE + 1)))
        }
    }

    @Test
    fun `decodes a frame`() {
        val frame = FrameReader(ByteArrayInputStream(shutterFrame)).read()

        assertEquals(FRAME_TYPE_JSON, frame.type)
        assertEquals(shutterJson, frame.body.decodeToString())
    }

    @Test
    fun `decodes consecutive frames from one stream`() {
        val reader = FrameReader(ByteArrayInputStream(shutterFrame + hex("00000002 02 ffd8")))

        assertEquals(shutterJson, reader.read().body.decodeToString())
        val preview = reader.read()
        assertEquals(FRAME_TYPE_PREVIEW, preview.type)
        assertArrayEquals(hex("ffd8"), preview.body)
    }

    @Test
    fun `decodes a frame that arrives split across reads`() {
        val frame = FrameReader(OneByteAtATimeInputStream(shutterFrame)).read()

        assertEquals(shutterJson, frame.body.decodeToString())
    }

    @Test
    fun `round-trips a body of exactly 4 MiB`() {
        val body = ByteArray(MAX_FRAME_BODY_SIZE) { it.toByte() }

        val frame = FrameReader(ByteArrayInputStream(encodeFrame(Frame(FRAME_TYPE_PREVIEW, body)))).read()

        assertArrayEquals(body, frame.body)
    }

    @Test
    fun `rejects a length over 4 MiB without reading the body`() {
        assertThrows(FrameTooLargeException::class.java) {
            FrameReader(ByteArrayInputStream(hex("00400001 02"))).read()
        }
    }

    @Test
    fun `rejects a length with the top bit set as too large`() {
        assertThrows(FrameTooLargeException::class.java) {
            FrameReader(ByteArrayInputStream(hex("ffffffff 02"))).read()
        }
    }

    @Test
    fun `fails at the end of the stream`() {
        assertThrows(EOFException::class.java) {
            FrameReader(ByteArrayInputStream(ByteArray(0))).read()
        }
    }

    @Test
    fun `fails when the stream ends in the middle of a body`() {
        assertThrows(EOFException::class.java) {
            FrameReader(ByteArrayInputStream(shutterFrame.copyOf(shutterFrame.size - 1))).read()
        }
    }

    private class OneByteAtATimeInputStream(
        bytes: ByteArray,
    ) : InputStream() {
        private val input = ByteArrayInputStream(bytes)

        override fun read(): Int = input.read()

        override fun read(
            b: ByteArray,
            off: Int,
            len: Int,
        ): Int = input.read(b, off, minOf(len, 1))
    }
}

fun hex(text: String): ByteArray =
    text
        .filterNot { it.isWhitespace() }
        .chunked(2)
        .map { it.toInt(16).toByte() }
        .toByteArray()
