package io.github.haruto17.pivr180.ui

import androidx.annotation.StringRes
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.selection.selectableGroup
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Slider
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import io.github.haruto17.pivr180.R
import io.github.haruto17.pivr180.capture.SaveResult
import io.github.haruto17.pivr180.capture.SettingsState
import io.github.haruto17.pivr180.capture.UnavailableReason
import io.github.haruto17.pivr180.protocol.CameraSettings
import io.github.haruto17.pivr180.protocol.WhiteBalance
import java.util.Locale
import kotlin.math.roundToInt

private const val EXPOSURE_VALUE_MIN = -2f
private const val EXPOSURE_VALUE_MAX = 2f
private const val CONTRAST_MIN = 0f
private const val CONTRAST_MAX = 2f
private const val STEPS_PER_UNIT = 10

@Composable
fun SettingsScreen(
    state: SettingsState,
    onLoad: () -> Unit,
    onChange: (CameraSettings) -> Unit,
) {
    LaunchedEffect(Unit) { onLoad() }
    Column(
        modifier =
            Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        when (state) {
            SettingsState.NotLoaded, SettingsState.Loading -> {
                Text(stringResource(R.string.settings_loading))
            }

            is SettingsState.Unavailable -> {
                Text(stringResource(unavailableText(state.reason), state.detail), color = MaterialTheme.colorScheme.error)
                Button(onClick = onLoad) {
                    Text(stringResource(R.string.settings_reload))
                }
            }

            is SettingsState.Loaded -> {
                SettingsControls(state.settings, onChange)
                SaveStatus(state)
            }
        }
    }
}

private fun unavailableText(reason: UnavailableReason): Int =
    when (reason) {
        UnavailableReason.LOAD_FAILED -> R.string.settings_load_failed
        UnavailableReason.SAVE_UNCONFIRMED -> R.string.settings_save_unconfirmed
    }

@Composable
private fun SettingsControls(
    settings: CameraSettings,
    onChange: (CameraSettings) -> Unit,
) {
    SteppedSlider(
        label = R.string.settings_exposure_value,
        format = "%+.1f",
        value = settings.exposureValue,
        range = EXPOSURE_VALUE_MIN..EXPOSURE_VALUE_MAX,
    ) { onChange(settings.copy(exposureValue = it)) }
    WhiteBalancePicker(settings.whiteBalance) { onChange(settings.copy(whiteBalance = it)) }
    SteppedSlider(
        label = R.string.settings_contrast,
        format = "%.1f",
        value = settings.contrast,
        range = CONTRAST_MIN..CONTRAST_MAX,
    ) { onChange(settings.copy(contrast = it)) }
}

@Composable
private fun SteppedSlider(
    @StringRes label: Int,
    format: String,
    value: Double,
    range: ClosedFloatingPointRange<Float>,
    onChange: (Double) -> Unit,
) {
    // Not sent on every move: each set_settings makes the Pi apply the controls and save them to its SD card.
    var dragging by remember { mutableStateOf<Float?>(null) }
    val shown = dragging ?: value.toFloat()
    Column {
        Text(stringResource(label, String.format(Locale.ROOT, format, shown)), style = MaterialTheme.typography.titleMedium)
        Slider(
            value = shown,
            onValueChange = { dragging = it },
            onValueChangeFinished = {
                dragging?.let { onChange(toStep(it)) }
                dragging = null
            },
            valueRange = range,
            steps = ((range.endInclusive - range.start) * STEPS_PER_UNIT).roundToInt() - 1,
        )
    }
}

private fun toStep(value: Float): Double = (value * STEPS_PER_UNIT).roundToInt().toDouble() / STEPS_PER_UNIT

@Composable
private fun WhiteBalancePicker(
    selected: WhiteBalance,
    onSelect: (WhiteBalance) -> Unit,
) {
    Column(modifier = Modifier.selectableGroup()) {
        Text(stringResource(R.string.settings_white_balance), style = MaterialTheme.typography.titleMedium)
        WhiteBalance.entries.forEach { whiteBalance ->
            Row(
                verticalAlignment = Alignment.CenterVertically,
                modifier =
                    Modifier
                        .fillMaxWidth()
                        .selectable(
                            selected = whiteBalance == selected,
                            onClick = { onSelect(whiteBalance) },
                            role = Role.RadioButton,
                        ),
            ) {
                RadioButton(selected = whiteBalance == selected, onClick = null)
                Text(stringResource(whiteBalanceText(whiteBalance)), modifier = Modifier.padding(start = 8.dp))
            }
        }
    }
}

private fun whiteBalanceText(whiteBalance: WhiteBalance): Int =
    when (whiteBalance) {
        WhiteBalance.AUTO -> R.string.white_balance_auto
        WhiteBalance.INCANDESCENT -> R.string.white_balance_incandescent
        WhiteBalance.TUNGSTEN -> R.string.white_balance_tungsten
        WhiteBalance.FLUORESCENT -> R.string.white_balance_fluorescent
        WhiteBalance.INDOOR -> R.string.white_balance_indoor
        WhiteBalance.DAYLIGHT -> R.string.white_balance_daylight
        WhiteBalance.CLOUDY -> R.string.white_balance_cloudy
    }

@Composable
private fun SaveStatus(state: SettingsState.Loaded) {
    val result = state.result
    when {
        state.saving -> {
            Text(stringResource(R.string.settings_saving))
        }

        result == SaveResult.Saved -> {
            Text(stringResource(R.string.settings_saved))
        }

        result is SaveResult.Failed -> {
            Text(stringResource(R.string.settings_save_failed, result.detail), color = MaterialTheme.colorScheme.error)
        }
    }
}

@Preview(showBackground = true)
@Composable
private fun SettingsScreenPreview() {
    MaterialTheme {
        SettingsScreen(
            state =
                SettingsState.Loaded(
                    CameraSettings(0.5, WhiteBalance.DAYLIGHT, 1.2),
                    result = SaveResult.Failed("cameras_not_ready: cameras are not ready"),
                ),
            onLoad = {},
            onChange = {},
        )
    }
}
