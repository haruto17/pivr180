package io.github.haruto17.pivr180.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshotFlow
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import io.github.haruto17.pivr180.R
import io.github.haruto17.pivr180.capture.CaptureListItem
import io.github.haruto17.pivr180.capture.CaptureListNotice
import io.github.haruto17.pivr180.capture.CaptureListNoticeKind
import io.github.haruto17.pivr180.capture.CaptureListState
import io.github.haruto17.pivr180.capture.Thumbnail
import io.github.haruto17.pivr180.protocol.CaptureSummary
import kotlinx.coroutines.flow.distinctUntilChanged

@Composable
fun CaptureListScreen(
    state: CaptureListState<ImageBitmap>,
    onRefresh: () -> Unit,
    onVisibleCapturesChanged: (List<String>) -> Unit,
    onDelete: (String) -> Unit,
    onDismissNotice: () -> Unit,
) {
    var confirmingDelete by rememberSaveable { mutableStateOf<String?>(null) }
    val listState = rememberLazyListState()
    val currentOnVisibleCapturesChanged by rememberUpdatedState(onVisibleCapturesChanged)
    LaunchedEffect(Unit) { onRefresh() }
    LaunchedEffect(listState) {
        snapshotFlow { listState.layoutInfo.visibleItemsInfo.map { it.key as String } }
            .distinctUntilChanged()
            .collect { currentOnVisibleCapturesChanged(it) }
    }
    DisposableEffect(Unit) { onDispose { currentOnVisibleCapturesChanged(emptyList()) } }

    Column(modifier = Modifier.fillMaxSize()) {
        Row(
            modifier =
                Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 16.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                text = listSummary(state),
                style = MaterialTheme.typography.titleMedium,
                modifier = Modifier.weight(1f),
            )
            OutlinedButton(onClick = onRefresh, enabled = !state.loading) {
                Text(stringResource(R.string.captures_refresh))
            }
        }
        state.notice?.let { ListNoticeRow(it, onDismissNotice) }
        LazyColumn(
            state = listState,
            contentPadding = PaddingValues(16.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
            modifier = Modifier.weight(1f),
        ) {
            items(state.items.orEmpty(), key = { it.summary.id }) { item ->
                CaptureRow(item, onDelete = { confirmingDelete = item.summary.id })
            }
        }
    }
    confirmingDelete?.let { captureId ->
        AlertDialog(
            onDismissRequest = { confirmingDelete = null },
            title = { Text(stringResource(R.string.delete_confirm_title)) },
            text = { Text(stringResource(R.string.delete_confirm_text, captureId)) },
            confirmButton = {
                TextButton(onClick = {
                    confirmingDelete = null
                    onDelete(captureId)
                }) {
                    Text(stringResource(R.string.delete_confirm))
                }
            },
            dismissButton = {
                TextButton(onClick = { confirmingDelete = null }) {
                    Text(stringResource(R.string.cancel))
                }
            },
        )
    }
}

@Composable
private fun listSummary(state: CaptureListState<ImageBitmap>): String {
    val items = state.items
    return when {
        items == null && state.loading -> stringResource(R.string.captures_loading)
        items == null -> stringResource(R.string.captures_not_loaded)
        items.isEmpty() -> stringResource(R.string.captures_none)
        else -> stringResource(R.string.captures_count, items.size)
    }
}

@Composable
private fun ListNoticeRow(
    notice: CaptureListNotice,
    onDismiss: () -> Unit,
) {
    Row(modifier = Modifier.padding(horizontal = 16.dp), verticalAlignment = Alignment.CenterVertically) {
        Text(
            text =
                when (notice.kind) {
                    CaptureListNoticeKind.LOAD_FAILED -> {
                        stringResource(R.string.notice_captures_load_failed, notice.detail)
                    }

                    CaptureListNoticeKind.DELETE_FAILED -> {
                        stringResource(R.string.notice_delete_failed, notice.captureId.orEmpty(), notice.detail)
                    }

                    CaptureListNoticeKind.ALREADY_DELETED -> {
                        stringResource(R.string.notice_already_deleted, notice.captureId.orEmpty())
                    }
                },
            color = MaterialTheme.colorScheme.error,
            modifier = Modifier.weight(1f),
        )
        TextButton(onClick = onDismiss) {
            Text(stringResource(R.string.dismiss))
        }
    }
}

@Composable
private fun CaptureRow(
    item: CaptureListItem<ImageBitmap>,
    onDelete: () -> Unit,
) {
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text(item.summary.id, style = MaterialTheme.typography.titleSmall)
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            ThumbnailBox(stringResource(R.string.side_left), item.left, Modifier.weight(1f))
            ThumbnailBox(stringResource(R.string.side_right), item.right, Modifier.weight(1f))
        }
        if (!item.summary.complete) {
            Text(stringResource(R.string.capture_incomplete), color = MaterialTheme.colorScheme.error)
        }
        if (item.summary.syncWarning == true) {
            Text(stringResource(R.string.capture_sync_warning), color = MaterialTheme.colorScheme.error)
        }
        Box(modifier = Modifier.fillMaxWidth(), contentAlignment = Alignment.CenterEnd) {
            OutlinedButton(onClick = onDelete, enabled = !item.deleting) {
                Text(stringResource(if (item.deleting) R.string.deleting else R.string.delete))
            }
        }
        HorizontalDivider()
    }
}

@Preview(showBackground = true)
@Composable
private fun CaptureListScreenPreview() {
    MaterialTheme {
        CaptureListScreen(
            state =
                CaptureListState(
                    items =
                        listOf(
                            CaptureListItem(CaptureSummary("20261128-010210-002", complete = true, syncWarning = true)),
                            CaptureListItem(
                                CaptureSummary("20261128-010203-001", complete = false, syncWarning = null),
                                right = Thumbnail.Unavailable("capture_not_found: no right image"),
                                deleting = true,
                            ),
                        ),
                    notice = CaptureListNotice(CaptureListNoticeKind.DELETE_FAILED, "20261128-010203-001", "internal_error: busy"),
                ),
            onRefresh = {},
            onVisibleCapturesChanged = {},
            onDelete = {},
            onDismissNotice = {},
        )
    }
}
