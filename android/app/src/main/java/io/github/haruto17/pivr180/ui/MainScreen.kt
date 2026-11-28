package io.github.haruto17.pivr180.ui

import androidx.annotation.StringRes
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.material3.PrimaryTabRow
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Tab
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import io.github.haruto17.pivr180.R

enum class Destination(
    @param:StringRes val label: Int,
) {
    CAPTURE(R.string.destination_capture),
    CAPTURES(R.string.destination_captures),
}

@Composable
fun MainScreen(content: @Composable (Destination) -> Unit) {
    var destination by rememberSaveable { mutableStateOf(Destination.CAPTURE) }
    Scaffold(
        topBar = {
            PrimaryTabRow(selectedTabIndex = destination.ordinal, modifier = Modifier.statusBarsPadding()) {
                Destination.entries.forEach {
                    Tab(
                        selected = it == destination,
                        onClick = { destination = it },
                        text = { Text(stringResource(it.label)) },
                    )
                }
            }
        },
    ) { padding ->
        Box(
            modifier =
                Modifier
                    .fillMaxSize()
                    .padding(padding),
        ) {
            content(destination)
        }
    }
}
