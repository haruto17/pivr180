package io.github.haruto17.pivr180.protocol

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Test
import java.io.BufferedInputStream
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.io.IOException
import java.io.InputStream

private const val READ_LIMIT = 16384

class BoundedReadInputStreamTest {
    @Test
    fun `never asks the underlying stream for more than the limit`() {
        val underlying = RecordingInputStream(ByteArray(50_000))
        val buffer = ByteArray(50_000)

        val read = BoundedReadInputStream(underlying, READ_LIMIT).read(buffer, 0, buffer.size)

        assertEquals(READ_LIMIT, read)
        assertEquals(listOf(READ_LIMIT), underlying.requestedLengths)
    }

    @Test
    fun `passes smaller reads through unchanged`() {
        val underlying = RecordingInputStream(ByteArray(100))

        val read = BoundedReadInputStream(underlying, READ_LIMIT).read(ByteArray(10), 2, 8)

        assertEquals(8, read)
        assertEquals(listOf(8), underlying.requestedLengths)
    }

    @Test
    fun `reads single bytes from the underlying stream`() {
        val stream = BoundedReadInputStream(ByteArrayInputStream(byteArrayOf(7)), READ_LIMIT)

        assertEquals(7, stream.read())
        assertEquals(-1, stream.read())
    }

    @Test
    fun `reports no available bytes without asking the underlying stream`() {
        val underlying = RecordingInputStream(ByteArray(100))

        assertEquals(0, BoundedReadInputStream(underlying, READ_LIMIT).available())
        assertEquals(0, underlying.availableCalls)
    }

    @Test
    fun `rejects a non-positive limit`() {
        assertThrows(IllegalArgumentException::class.java) {
            BoundedReadInputStream(ByteArrayInputStream(ByteArray(0)), 0)
        }
    }

    @Test
    fun `lets a buffered channel read a preview larger than the limit`() {
        val jpeg = ByteArray(41_309) { it.toByte() }
        val accessory = StrictInputStream(encodeFrame(Frame(FRAME_TYPE_PREVIEW, jpeg)), READ_LIMIT)
        val input = BufferedInputStream(BoundedReadInputStream(accessory, READ_LIMIT), READ_LIMIT)

        val incoming = AccessoryChannel(input, ByteArrayOutputStream()).receive() as Incoming.Preview

        assertArrayEquals(jpeg, incoming.jpeg)
    }
}

private class RecordingInputStream(
    bytes: ByteArray,
) : InputStream() {
    private val source = ByteArrayInputStream(bytes)
    val requestedLengths = mutableListOf<Int>()
    var availableCalls = 0

    override fun available(): Int {
        availableCalls++
        return source.available()
    }

    override fun read(): Int = source.read()

    override fun read(
        b: ByteArray,
        off: Int,
        len: Int,
    ): Int {
        requestedLengths += len
        return source.read(b, off, len)
    }
}

private class StrictInputStream(
    bytes: ByteArray,
    private val maxReadSize: Int,
) : InputStream() {
    private val source = ByteArrayInputStream(bytes)

    override fun available(): Int = throw IOException("Invalid argument")

    override fun read(): Int = source.read()

    override fun read(
        b: ByteArray,
        off: Int,
        len: Int,
    ): Int {
        if (len > maxReadSize) throw IOException("read of $len bytes exceeds $maxReadSize")
        return source.read(b, off, len)
    }
}
