package io.github.haruto17.pivr180.protocol

import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.io.EOFException
import java.io.File

class FrameExamplesTest {
    private val examplesDir = File(System.getProperty("pivr180.repoRoot"), "schema/examples/aoa")
    private val sentinelJpeg = hex("ffd9")
    private val sentinel = encodeFrame(Frame(FRAME_TYPE_PREVIEW, sentinelJpeg))

    @Test
    fun `encodes every frame example from its type and body`() {
        for ((name, example) in examples("frames")) {
            val frame = Frame(example.int("frame_type"), example.bytes("body"))

            assertArrayEquals(name, example.bytes("frame"), encodeFrame(frame))
        }
    }

    @Test
    fun `decodes the type and body of every frame example`() {
        for ((name, example) in examples("frames")) {
            val frame = FrameReader(ByteArrayInputStream(example.bytes("frame"))).read()

            assertEquals(name, example.int("frame_type"), frame.type)
            assertArrayEquals(name, example.bytes("body"), frame.body)
        }
    }

    @Test
    fun `receives every device-to-app frame example as its message, JPEG or thumbnail, skipping unknown types`() {
        for ((name, example) in examples("frames").filter { it.second.string("direction") == "device_to_app" }) {
            val channel = AccessoryChannel(ByteArrayInputStream(example.bytes("frame") + sentinel), ByteArrayOutputStream())

            val incoming = channel.receive()

            when (example.int("frame_type")) {
                FRAME_TYPE_JSON -> {
                    val message = protocolJson.decodeFromJsonElement(DeviceMessage.serializer(), example.getValue("message"))
                    assertEquals(name, Incoming.Message(message), incoming)
                }

                FRAME_TYPE_PREVIEW -> {
                    assertArrayEquals(name, example.bytes("jpeg"), (incoming as Incoming.Preview).jpeg)
                }

                FRAME_TYPE_THUMBNAIL -> {
                    assertEquals(name, example.int("thumbnail_id"), (incoming as Incoming.Thumbnail).id)
                    assertArrayEquals(name, example.bytes("jpeg"), incoming.jpeg)
                }

                else -> {
                    assertArrayEquals(name, sentinelJpeg, (incoming as Incoming.Preview).jpeg)
                }
            }
        }
    }

    @Test
    fun `the body of every app-to-device JSON frame example is its message`() {
        for ((name, example) in examples("frames").filter { it.second.string("direction") == "app_to_device" }) {
            val body = example.bytes("body").decodeToString()

            assertEquals(
                name,
                protocolJson.decodeFromJsonElement(AppMessage.serializer(), example.getValue("message")),
                protocolJson.decodeFromString(AppMessage.serializer(), body),
            )
        }
    }

    @Test
    fun `rejects every frame header example over the length limit`() {
        val headers = examples("frame_headers")
        for ((name, example) in headers) {
            val reader = FrameReader(ByteArrayInputStream(example.bytes("header")))
            val expected = if (example.boolean("within_limit")) EOFException::class.java else FrameTooLargeException::class.java

            assertThrows(name, expected) { reader.read() }
        }
        assertTrue(headers.any { !it.second.boolean("within_limit") })
    }

    private fun examples(kind: String): List<Pair<String, JsonObject>> {
        val files = File(examplesDir, kind).listFiles { file -> file.extension == "json" }.orEmpty()
        assertTrue("no examples in $examplesDir/$kind", files.isNotEmpty())
        return files.sortedBy { it.name }.map { it.name to protocolJson.parseToJsonElement(it.readText()).jsonObject }
    }

    private fun JsonObject.string(key: String) = getValue(key).jsonPrimitive.content

    private fun JsonObject.int(key: String) = getValue(key).jsonPrimitive.int

    private fun JsonObject.boolean(key: String) = getValue(key).jsonPrimitive.boolean

    private fun JsonObject.bytes(key: String) = hex(string(key))
}
