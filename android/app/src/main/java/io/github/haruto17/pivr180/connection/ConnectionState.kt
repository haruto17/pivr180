package io.github.haruto17.pivr180.connection

sealed interface ConnectionState {
    data object Disconnected : ConnectionState

    data object Connecting : ConnectionState

    data class Connected(
        val softwareVersion: String,
    ) : ConnectionState

    data class Failed(
        val detail: String,
    ) : ConnectionState
}
