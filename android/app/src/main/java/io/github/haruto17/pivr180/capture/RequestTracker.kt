package io.github.haruto17.pivr180.capture

import io.github.haruto17.pivr180.connection.DeadlineScheduler
import io.github.haruto17.pivr180.connection.HELLO_REQUEST_ID
import kotlin.time.Duration
import kotlin.time.Duration.Companion.seconds

val REQUEST_TIMEOUT: Duration = 10.seconds

private const val FIRST_REQUEST_ID = HELLO_REQUEST_ID + 1

class RequestTracker<K>(
    private val deadlines: DeadlineScheduler,
    private val timeout: Duration = REQUEST_TIMEOUT,
    firstId: Int = FIRST_REQUEST_ID,
    private val lastId: Int = Int.MAX_VALUE,
    private val onTimeout: (K) -> Unit,
) {
    private class Pending<K>(
        val key: K,
        val cancelDeadline: () -> Unit,
    )

    private val pending = mutableMapOf<Int, Pending<K>>()
    private var nextId = firstId

    fun issue(key: K): Int {
        val id = allocateId()
        pending[id] = Pending(key, deadlines.schedule(timeout) { expire(id) })
        return id
    }

    fun complete(id: Int): K? {
        val request = pending.remove(id) ?: return null
        request.cancelDeadline()
        return request.key
    }

    fun cancelAll() {
        pending.values.forEach { it.cancelDeadline() }
        pending.clear()
    }

    private fun expire(id: Int) {
        val request = pending.remove(id) ?: return
        onTimeout(request.key)
    }

    private fun allocateId(): Int {
        while (true) {
            val id = nextId
            nextId = if (id == lastId) FIRST_REQUEST_ID else id + 1
            if (id !in pending) return id
        }
    }
}
