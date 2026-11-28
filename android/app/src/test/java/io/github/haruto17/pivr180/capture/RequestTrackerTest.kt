package io.github.haruto17.pivr180.capture

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class RequestTrackerTest {
    private val deadlines = ManualDeadlineScheduler()
    private val timedOut = mutableListOf<String>()

    @Test
    fun `issues ids from 1 because 0 belongs to hello`() {
        val tracker = RequestTracker(deadlines) { key: String -> timedOut += key }

        assertEquals(listOf(1, 2, 3), listOf(tracker.issue("a"), tracker.issue("b"), tracker.issue("c")))
    }

    @Test
    fun `matches an answer to the request with its id once`() {
        val tracker = RequestTracker(deadlines) { key: String -> timedOut += key }
        tracker.issue("a")
        val id = tracker.issue("b")

        assertEquals("b", tracker.complete(id))
        assertNull(tracker.complete(id))
    }

    @Test
    fun `knows nothing about an id it did not issue`() {
        val tracker = RequestTracker(deadlines) { key: String -> timedOut += key }

        assertNull(tracker.complete(42))
    }

    @Test
    fun `wraps around to 1 after the largest id`() {
        val tracker = RequestTracker(deadlines, firstId = Int.MAX_VALUE) { key: String -> timedOut += key }

        assertEquals(listOf(Int.MAX_VALUE, 1), listOf(tracker.issue("a"), tracker.issue("b")))
    }

    @Test
    fun `skips an id that is still pending after wrapping around`() {
        val tracker = RequestTracker(deadlines, lastId = 3) { key: String -> timedOut += key }
        tracker.issue("a")
        tracker.complete(tracker.issue("b"))
        tracker.complete(tracker.issue("c"))

        assertEquals(2, tracker.issue("d"))
    }

    @Test
    fun `reports a request that gets no answer before the timeout`() {
        val tracker = RequestTracker(deadlines, timeout = REQUEST_TIMEOUT) { key: String -> timedOut += key }
        val id = tracker.issue("a")

        deadlines.fireAll()

        assertEquals(listOf("a"), timedOut)
        assertEquals(listOf(REQUEST_TIMEOUT), deadlines.delays)
        assertNull(tracker.complete(id))
    }

    @Test
    fun `cancels the deadline of an answered request`() {
        val tracker = RequestTracker(deadlines) { key: String -> timedOut += key }
        tracker.complete(tracker.issue("a"))

        deadlines.fireAll()

        assertEquals(emptyList<String>(), timedOut)
    }

    @Test
    fun `cancels every deadline when the connection ends`() {
        val tracker = RequestTracker(deadlines) { key: String -> timedOut += key }
        val id = tracker.issue("a")
        tracker.issue("b")

        tracker.cancelAll()

        assertEquals(0, deadlines.pendingCount)
        assertNull(tracker.complete(id))
    }
}
