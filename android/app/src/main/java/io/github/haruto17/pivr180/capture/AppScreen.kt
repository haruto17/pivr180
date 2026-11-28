package io.github.haruto17.pivr180.capture

import io.github.haruto17.pivr180.connection.ConnectionState

sealed interface AppScreen<out I> {
    data class Connection(
        val state: ConnectionState,
    ) : AppScreen<Nothing>

    data class Capture<I>(
        val state: CaptureState<I>,
    ) : AppScreen<I>

    data object ShutDown : AppScreen<Nothing>
}

fun <I> appScreen(
    connection: ConnectionState,
    capture: CaptureState<I>?,
): AppScreen<I> =
    when {
        capture?.shutdown == ShutdownState.DONE -> AppScreen.ShutDown
        connection is ConnectionState.Connected && capture != null -> AppScreen.Capture(capture)
        else -> AppScreen.Connection(connection)
    }
