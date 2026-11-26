package io.github.haruto17.pivr180.connection

import io.github.haruto17.pivr180.protocol.AccessoryChannel
import io.github.haruto17.pivr180.protocol.ErrorMessage
import io.github.haruto17.pivr180.protocol.Hello
import io.github.haruto17.pivr180.protocol.Incoming
import io.github.haruto17.pivr180.protocol.MalformedFrameException
import io.github.haruto17.pivr180.protocol.PROTOCOL_VERSION
import io.github.haruto17.pivr180.protocol.Welcome
import java.io.IOException

const val HELLO_REQUEST_ID = 0

fun runSession(
    channel: AccessoryChannel,
    appVersion: String,
    onState: (ConnectionState) -> Unit,
) {
    onState(ConnectionState.Connecting)
    try {
        channel.send(Hello(HELLO_REQUEST_ID, PROTOCOL_VERSION, appVersion))
        val failure = awaitWelcome(channel, onState)
        if (failure != null) {
            onState(ConnectionState.Failed(failure))
            return
        }
        while (true) {
            channel.receive()
        }
    } catch (e: MalformedFrameException) {
        onState(ConnectionState.Failed(e.message.orEmpty()))
    } catch (_: IOException) {
        onState(ConnectionState.Disconnected)
    }
}

private fun awaitWelcome(
    channel: AccessoryChannel,
    onState: (ConnectionState) -> Unit,
): String? {
    while (true) {
        val message = (channel.receive() as? Incoming.Message)?.message
        when {
            message is Welcome && message.id == HELLO_REQUEST_ID -> {
                if (message.protocolVersion != PROTOCOL_VERSION) {
                    return "device speaks protocol version ${message.protocolVersion}, app speaks $PROTOCOL_VERSION"
                }
                onState(ConnectionState.Connected(message.softwareVersion))
                return null
            }

            message is ErrorMessage && message.id == HELLO_REQUEST_ID -> {
                return "${message.code.name.lowercase()}: ${message.message}"
            }
        }
    }
}
