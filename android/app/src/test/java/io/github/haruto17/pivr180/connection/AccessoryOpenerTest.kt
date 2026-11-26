package io.github.haruto17.pivr180.connection

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class AccessoryOpenerTest {
    @Test
    fun `opens an attached accessory`() {
        val opener = AccessoryOpener(attachedAccessories = { listOf("pi") }, open = { "handle of $it" })

        assertEquals(OpenResult.Opened("handle of pi"), opener.openIfAttached("pi"))
    }

    @Test
    fun `does not open an accessory from an intent that is no longer attached`() {
        val opened = mutableListOf<String>()
        val opener =
            AccessoryOpener<String, String>(
                attachedAccessories = { emptyList() },
                open = {
                    opened += it
                    "handle of $it"
                },
            )

        assertEquals(OpenResult.NotAttached, opener.openIfAttached("pi"))
        assertTrue(opened.isEmpty())
    }

    @Test
    fun `treats an accessory detached while opening as not attached`() {
        val opener =
            AccessoryOpener<String, String>(
                attachedAccessories = { listOf("pi") },
                open = { throw IllegalArgumentException("no accessory attached") },
            )

        assertEquals(OpenResult.NotAttached, opener.openIfAttached("pi"))
    }

    @Test
    fun `fails without permission`() {
        val opener =
            AccessoryOpener<String, String>(
                attachedAccessories = { listOf("pi") },
                open = { throw SecurityException("denied") },
            )

        assertEquals(OpenResult.Failed("no permission to open the accessory: denied"), opener.openIfAttached("pi"))
    }

    @Test
    fun `fails when opening returns nothing`() {
        val opener = AccessoryOpener<String, String>(attachedAccessories = { listOf("pi") }, open = { null })

        assertEquals(OpenResult.Failed("cannot open the accessory"), opener.openIfAttached("pi"))
    }
}
