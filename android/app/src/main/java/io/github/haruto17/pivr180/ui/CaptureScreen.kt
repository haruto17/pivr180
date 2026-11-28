package io.github.haruto17.pivr180.ui

import android.text.format.Formatter
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import io.github.haruto17.pivr180.R
import io.github.haruto17.pivr180.capture.CaptureState
import io.github.haruto17.pivr180.capture.LastCaptureThumbnails
import io.github.haruto17.pivr180.capture.ModeState
import io.github.haruto17.pivr180.capture.Notice
import io.github.haruto17.pivr180.capture.NoticeKind
import io.github.haruto17.pivr180.capture.ShutdownState
import io.github.haruto17.pivr180.capture.Thumbnail
import io.github.haruto17.pivr180.protocol.CaptureMode
import io.github.haruto17.pivr180.protocol.DeviceState
import io.github.haruto17.pivr180.protocol.LastCapture
import io.github.haruto17.pivr180.protocol.Status

private const val PREVIEW_ASPECT_RATIO = 1280f / 480f
private const val THUMBNAIL_ASPECT_RATIO = 4f / 3f

@Composable
fun CaptureScreen(
    state: CaptureState<ImageBitmap>,
    preview: ImageBitmap?,
    onShutter: () -> Unit,
    onShutdown: () -> Unit,
    onDismissNotice: () -> Unit,
) {
    var confirmingShutdown by rememberSaveable { mutableStateOf(false) }
    Column(
        modifier =
            Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        LivePreview(preview)
        Button(
            onClick = onShutter,
            enabled = state.canShutter,
            modifier =
                Modifier
                    .fillMaxWidth()
                    .height(64.dp),
        ) {
            Text(stringResource(R.string.shutter), style = MaterialTheme.typography.titleLarge)
        }
        state.notice?.let { NoticeRow(it, onDismissNotice) }
        StatusSection(state.status, state.mode)
        LastCaptureSection(state.lastCapture)
        if (state.shutdown == ShutdownState.NONE) {
            OutlinedButton(onClick = { confirmingShutdown = true }, enabled = state.canShutdown, modifier = Modifier.fillMaxWidth()) {
                Text(stringResource(R.string.shutdown))
            }
        } else {
            Text(stringResource(R.string.shutdown_requested), style = MaterialTheme.typography.titleMedium)
        }
    }
    if (confirmingShutdown) {
        AlertDialog(
            onDismissRequest = { confirmingShutdown = false },
            title = { Text(stringResource(R.string.shutdown_confirm_title)) },
            text = { Text(stringResource(R.string.shutdown_confirm_text)) },
            confirmButton = {
                TextButton(onClick = {
                    confirmingShutdown = false
                    onShutdown()
                }) {
                    Text(stringResource(R.string.shutdown_confirm))
                }
            },
            dismissButton = {
                TextButton(onClick = { confirmingShutdown = false }) {
                    Text(stringResource(R.string.cancel))
                }
            },
        )
    }
}

@Composable
private fun LivePreview(preview: ImageBitmap?) {
    Box(
        modifier =
            Modifier
                .fillMaxWidth()
                .aspectRatio(PREVIEW_ASPECT_RATIO)
                .background(MaterialTheme.colorScheme.surfaceVariant),
        contentAlignment = Alignment.Center,
    ) {
        if (preview == null) {
            Text(stringResource(R.string.preview_waiting))
        } else {
            Image(
                bitmap = preview,
                contentDescription = stringResource(R.string.preview_description),
                contentScale = ContentScale.Fit,
                modifier = Modifier.fillMaxSize(),
            )
        }
    }
}

@Composable
private fun NoticeRow(
    notice: Notice,
    onDismiss: () -> Unit,
) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Text(
            text = stringResource(noticeText(notice.kind), notice.detail),
            color = MaterialTheme.colorScheme.error,
            modifier = Modifier.weight(1f),
        )
        TextButton(onClick = onDismiss) {
            Text(stringResource(R.string.dismiss))
        }
    }
}

private fun noticeText(kind: NoticeKind): Int =
    when (kind) {
        NoticeKind.SHUTTER_FAILED -> R.string.notice_shutter_failed
        NoticeKind.SHUTDOWN_FAILED -> R.string.notice_shutdown_failed
        NoticeKind.MODE_FAILED -> R.string.notice_mode_failed
        NoticeKind.PREVIEW_FAILED -> R.string.notice_preview_failed
        NoticeKind.MESSAGE_REJECTED -> R.string.notice_message_rejected
    }

@Composable
private fun StatusSection(
    status: Status?,
    mode: ModeState,
) {
    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
        if (status == null) {
            Text(stringResource(R.string.status_waiting))
        } else {
            Text(
                text = deviceStateText(status),
                style = MaterialTheme.typography.titleMedium,
                color = if (status.state == DeviceState.ERROR) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSurface,
            )
        }
        Text(stringResource(R.string.mode_label, modeText(mode)))
        if (status != null) {
            Text(stringResource(R.string.capture_count, status.captureCount))
            Text(stringResource(R.string.free_space, Formatter.formatFileSize(LocalContext.current, status.freeBytes)))
            if (status.lastCapture?.syncWarning == true) {
                Text(stringResource(R.string.sync_warning), color = MaterialTheme.colorScheme.error)
            }
        }
    }
}

@Composable
private fun deviceStateText(status: Status): String =
    when (status.state) {
        DeviceState.IDLE -> stringResource(R.string.device_state_idle)
        DeviceState.CAPTURING -> stringResource(R.string.device_state_capturing)
        DeviceState.ERROR -> stringResource(R.string.device_state_error, status.errorMessage.orEmpty())
    }

@Composable
private fun modeText(mode: ModeState): String =
    when (mode) {
        ModeState.Loading -> {
            stringResource(R.string.mode_loading)
        }

        ModeState.Unknown -> {
            stringResource(R.string.mode_unknown)
        }

        is ModeState.Known -> {
            when (mode.mode) {
                CaptureMode.PHOTO -> stringResource(R.string.mode_photo)
            }
        }
    }

@Composable
private fun LastCaptureSection(lastCapture: LastCaptureThumbnails<ImageBitmap>?) {
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text(stringResource(R.string.last_capture_title), style = MaterialTheme.typography.titleMedium)
        if (lastCapture == null) {
            Text(stringResource(R.string.last_capture_none))
        } else {
            Text(lastCapture.captureId, style = MaterialTheme.typography.bodySmall)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                ThumbnailBox(stringResource(R.string.side_left), lastCapture.left, Modifier.weight(1f))
                ThumbnailBox(stringResource(R.string.side_right), lastCapture.right, Modifier.weight(1f))
            }
        }
    }
}

@Composable
internal fun ThumbnailBox(
    label: String,
    thumbnail: Thumbnail<ImageBitmap>,
    modifier: Modifier,
) {
    Column(modifier = modifier, horizontalAlignment = Alignment.CenterHorizontally) {
        Box(
            modifier =
                Modifier
                    .fillMaxWidth()
                    .aspectRatio(THUMBNAIL_ASPECT_RATIO)
                    .background(MaterialTheme.colorScheme.surfaceVariant),
            contentAlignment = Alignment.Center,
        ) {
            when (thumbnail) {
                Thumbnail.Loading -> {
                    Text(stringResource(R.string.thumbnail_loading))
                }

                is Thumbnail.Unavailable -> {
                    Text(
                        text = stringResource(R.string.thumbnail_unavailable, thumbnail.detail),
                        textAlign = TextAlign.Center,
                        style = MaterialTheme.typography.bodySmall,
                        modifier = Modifier.padding(8.dp),
                    )
                }

                is Thumbnail.Loaded -> {
                    Image(
                        bitmap = thumbnail.image,
                        contentDescription = label,
                        contentScale = ContentScale.Fit,
                        modifier = Modifier.fillMaxSize(),
                    )
                }
            }
        }
        Text(label)
    }
}

@Preview(showBackground = true)
@Composable
private fun CaptureScreenPreview() {
    MaterialTheme {
        CaptureScreen(
            state =
                CaptureState(
                    status =
                        Status(
                            DeviceState.IDLE,
                            captureCount = 12,
                            freeBytes = 25_000_000_000,
                            lastCapture = LastCapture("20261128-010203-001", true),
                        ),
                    mode = ModeState.Known(CaptureMode.PHOTO),
                    lastCapture =
                        LastCaptureThumbnails(
                            "20261128-010203-001",
                            Thumbnail.Loading,
                            Thumbnail.Unavailable("capture_not_found"),
                        ),
                    notice = Notice(NoticeKind.SHUTTER_FAILED, "cameras_not_ready: cameras are not ready"),
                ),
            preview = null,
            onShutter = {},
            onShutdown = {},
            onDismissNotice = {},
        )
    }
}
