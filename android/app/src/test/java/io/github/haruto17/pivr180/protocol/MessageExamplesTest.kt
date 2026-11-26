package io.github.haruto17.pivr180.protocol

import kotlinx.serialization.KSerializer
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.doubleOrNull
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

class MessageExamplesTest {
    private val examplesDir = File(System.getProperty("pivr180.repoRoot"), "schema/examples/aoa")

    @Test
    fun `every app-to-device example round-trips as an app message`() {
        assertRoundTrips("app_to_device", AppMessage.serializer())
    }

    @Test
    fun `every device-to-app example round-trips as a device message`() {
        assertRoundTrips("device_to_app", DeviceMessage.serializer())
    }

    private fun <T> assertRoundTrips(
        direction: String,
        serializer: KSerializer<T>,
    ) {
        val examples = File(examplesDir, direction).listFiles { file -> file.extension == "json" }.orEmpty()
        assertTrue("no examples in $examplesDir/$direction", examples.isNotEmpty())
        for (example in examples.sortedBy { it.name }) {
            val original = protocolJson.parseToJsonElement(example.readText())

            val encoded = protocolJson.encodeToJsonElement(serializer, protocolJson.decodeFromJsonElement(serializer, original))

            assertEquals(example.name, normalize(original), normalize(encoded))
        }
    }

    private fun normalize(element: JsonElement): Any? =
        when (element) {
            is JsonObject -> element.mapValues { normalize(it.value) }
            is JsonArray -> element.map(::normalize)
            is JsonPrimitive -> if (element.isString) element.content else element.booleanOrNull ?: element.doubleOrNull
        }
}
