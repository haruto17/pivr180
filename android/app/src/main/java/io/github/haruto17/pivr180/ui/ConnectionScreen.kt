package io.github.haruto17.pivr180.ui

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import io.github.haruto17.pivr180.R
import io.github.haruto17.pivr180.connection.ConnectionState

@Composable
fun ConnectionScreen(state: ConnectionState) {
    Scaffold { padding ->
        Box(
            modifier =
                Modifier
                    .fillMaxSize()
                    .padding(padding)
                    .padding(24.dp),
            contentAlignment = Alignment.Center,
        ) {
            Text(text = stateText(state), style = MaterialTheme.typography.titleMedium)
        }
    }
}

@Composable
private fun stateText(state: ConnectionState): String =
    when (state) {
        ConnectionState.Disconnected -> stringResource(R.string.state_disconnected)
        ConnectionState.Connecting -> stringResource(R.string.state_connecting)
        is ConnectionState.Connected -> stringResource(R.string.state_connected, state.softwareVersion)
        is ConnectionState.Failed -> stringResource(R.string.state_failed, state.detail)
    }

@Preview
@Composable
private fun ConnectionScreenPreview() {
    ConnectionScreen(ConnectionState.Connected("0.1.0"))
}
