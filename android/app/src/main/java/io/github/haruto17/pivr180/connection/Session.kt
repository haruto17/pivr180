package io.github.haruto17.pivr180.connection

import io.github.haruto17.pivr180.protocol.AccessoryChannel
import io.github.haruto17.pivr180.protocol.ErrorMessage
import io.github.haruto17.pivr180.protocol.Hello
import io.github.haruto17.pivr180.protocol.Incoming
import io.github.haruto17.pivr180.protocol.MalformedFrameException
import io.github.haruto17.pivr180.protocol.PROTOCOL_VERSION
import io.github.haruto17.pivr180.protocol.Welcome
import java.io.IOException
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference
import kotlin.time.Duration
import kotlin.time.Duration.Companion.seconds

const val HELLO_REQUEST_ID = 0
val HANDSHAKE_TIMEOUT: Duration = 5.seconds

private enum class Phase { HANDSHAKING, CONNECTED, ENDED }

fun runSession(
    channel: AccessoryChannel,
    appVersion: String,
    close: () -> Unit,
    handshakeTimeout: Duration = HANDSHAKE_TIMEOUT,
    onState: (ConnectionState) -> Unit,
) {
    onState(ConnectionState.Connecting)
    val phase = AtomicReference(Phase.HANDSHAKING)
    val timer = Executors.newSingleThreadScheduledExecutor()
    // Cancelling the reading coroutine would not unblock the stream read; closing the accessory does.
    timer.schedule(
        {
            if (phase.compareAndSet(Phase.HANDSHAKING, Phase.ENDED)) {
                onState(ConnectionState.Failed("no answer to hello within $handshakeTimeout"))
                close()
            }
        },
        handshakeTimeout.inWholeMilliseconds,
        TimeUnit.MILLISECONDS,
    )
    try {
        channel.send(Hello(HELLO_REQUEST_ID, PROTOCOL_VERSION, appVersion))
        val result = awaitWelcome(channel)
        if (result !is ConnectionState.Connected) {
            if (phase.compareAndSet(Phase.HANDSHAKING, Phase.ENDED)) onState(result)
            return
        }
        if (!phase.compareAndSet(Phase.HANDSHAKING, Phase.CONNECTED)) return
        timer.shutdownNow()
        onState(result)
        while (true) {
            channel.receive()
        }
    } catch (e: IOException) {
        if (phase.getAndSet(Phase.ENDED) == Phase.ENDED) return
        onState(if (e is MalformedFrameException) ConnectionState.Failed(e.message.orEmpty()) else ConnectionState.Disconnected)
    } finally {
        timer.shutdownNow()
    }
}

private fun awaitWelcome(channel: AccessoryChannel): ConnectionState {
    while (true) {
        val message = (channel.receive() as? Incoming.Message)?.message
        when {
            message is Welcome && message.id == HELLO_REQUEST_ID -> {
                if (message.protocolVersion != PROTOCOL_VERSION) {
                    return ConnectionState.Failed(
                        "device speaks protocol version ${message.protocolVersion}, app speaks $PROTOCOL_VERSION",
                    )
                }
                return ConnectionState.Connected(message.softwareVersion)
            }

            message is ErrorMessage && message.id == HELLO_REQUEST_ID -> {
                return ConnectionState.Failed("${message.code.name.lowercase()}: ${message.message}")
            }
        }
    }
}
