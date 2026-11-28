package io.github.haruto17.pivr180.capture

import io.github.haruto17.pivr180.connection.DeadlineScheduler
import kotlin.time.Duration

class ManualDeadlineScheduler : DeadlineScheduler {
    private class Deadline(
        val delay: Duration,
        val action: () -> Unit,
    ) {
        var cancelled = false
    }

    private val deadlines = mutableListOf<Deadline>()

    val pendingCount: Int get() = deadlines.count { !it.cancelled }

    val delays: List<Duration> get() = deadlines.map { it.delay }

    override fun schedule(
        delay: Duration,
        action: () -> Unit,
    ): () -> Unit {
        val deadline = Deadline(delay, action)
        deadlines += deadline
        return { deadline.cancelled = true }
    }

    fun fireAll() {
        deadlines.toList().filterNot { it.cancelled }.forEach {
            it.cancelled = true
            it.action()
        }
    }
}
