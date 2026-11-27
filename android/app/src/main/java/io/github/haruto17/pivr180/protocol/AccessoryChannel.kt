package io.github.haruto17.pivr180.protocol

import kotlinx.serialization.SerializationException
import java.io.InputStream
import java.io.OutputStream
import java.nio.ByteBuffer

sealed interface Incoming {
    data class Message(
        val message: DeviceMessage,
    ) : Incoming

    class Preview(
        val jpeg: ByteArray,
    ) : Incoming

    class Thumbnail(
        val id: Int,
        val jpeg: ByteArray,
    ) : Incoming
}

class AccessoryChannel(
    input: InputStream,
    output: OutputStream,
) {
    private val reader = FrameReader(input)
    private val writer = FrameWriter(output)

    fun send(message: AppMessage) {
        val json = protocolJson.encodeToString(AppMessage.serializer(), message)
        writer.write(Frame(FRAME_TYPE_JSON, json.encodeToByteArray()))
    }

    fun receive(): Incoming {
        while (true) {
            val frame = reader.read()
            when (frame.type) {
                FRAME_TYPE_JSON -> return Incoming.Message(decodeMessage(frame.body))
                FRAME_TYPE_PREVIEW -> return Incoming.Preview(frame.body)
                FRAME_TYPE_THUMBNAIL -> return decodeThumbnail(frame.body)
            }
        }
    }

    private fun decodeMessage(body: ByteArray): DeviceMessage =
        try {
            protocolJson.decodeFromString(DeviceMessage.serializer(), body.decodeToString(throwOnInvalidSequence = true))
        } catch (e: SerializationException) {
            throw MalformedFrameException("JSON frame is not a device message", e)
        } catch (e: CharacterCodingException) {
            throw MalformedFrameException("JSON frame is not UTF-8", e)
        }

    private fun decodeThumbnail(body: ByteArray): Incoming.Thumbnail {
        if (body.size < Int.SIZE_BYTES) throw MalformedFrameException("thumbnail frame has no id")
        val id = ByteBuffer.wrap(body).int
        return Incoming.Thumbnail(id, body.copyOfRange(Int.SIZE_BYTES, body.size))
    }
}
