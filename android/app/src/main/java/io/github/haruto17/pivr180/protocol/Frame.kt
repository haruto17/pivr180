package io.github.haruto17.pivr180.protocol

import java.io.DataInputStream
import java.io.IOException
import java.io.InputStream
import java.io.OutputStream
import java.nio.ByteBuffer

const val FRAME_TYPE_JSON = 0x01
const val FRAME_TYPE_PREVIEW = 0x02
const val FRAME_TYPE_THUMBNAIL = 0x03

const val FRAME_HEADER_SIZE = 5
const val MAX_FRAME_BODY_SIZE = 4 * 1024 * 1024

class Frame(
    val type: Int,
    val body: ByteArray,
)

open class MalformedFrameException(
    message: String,
    cause: Throwable? = null,
) : IOException(message, cause)

class FrameTooLargeException(
    length: Long,
) : MalformedFrameException("frame body of $length bytes exceeds $MAX_FRAME_BODY_SIZE")

fun encodeFrame(frame: Frame): ByteArray {
    require(frame.body.size <= MAX_FRAME_BODY_SIZE) { "frame body of ${frame.body.size} bytes is too large" }
    return ByteBuffer
        .allocate(FRAME_HEADER_SIZE + frame.body.size)
        .putInt(frame.body.size)
        .put(frame.type.toByte())
        .put(frame.body)
        .array()
}

class FrameReader(
    input: InputStream,
) {
    private val input = DataInputStream(input)

    fun read(): Frame {
        val length = input.readInt().toUInt().toLong()
        if (length > MAX_FRAME_BODY_SIZE) throw FrameTooLargeException(length)
        val type = input.readUnsignedByte()
        val body = ByteArray(length.toInt())
        input.readFully(body)
        return Frame(type, body)
    }
}

class FrameWriter(
    private val output: OutputStream,
) {
    @Synchronized
    fun write(frame: Frame) {
        output.write(encodeFrame(frame))
        output.flush()
    }
}
