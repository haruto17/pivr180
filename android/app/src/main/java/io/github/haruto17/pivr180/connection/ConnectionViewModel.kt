package io.github.haruto17.pivr180.connection

import android.app.Application
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.graphics.BitmapFactory
import android.hardware.usb.UsbAccessory
import android.hardware.usb.UsbManager
import android.os.ParcelFileDescriptor
import android.util.Log
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.core.content.ContextCompat
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import io.github.haruto17.pivr180.BuildConfig
import io.github.haruto17.pivr180.capture.CaptureController
import io.github.haruto17.pivr180.capture.CaptureState
import io.github.haruto17.pivr180.protocol.AccessoryChannel
import io.github.haruto17.pivr180.protocol.AppMessage
import io.github.haruto17.pivr180.protocol.BoundedReadInputStream
import io.github.haruto17.pivr180.protocol.CameraSettings
import io.github.haruto17.pivr180.protocol.Incoming
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.channels.onClosed
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import java.io.BufferedInputStream
import java.io.FileInputStream
import java.io.FileOutputStream
import java.io.IOException

private const val TAG = "ConnectionViewModel"

// f_accessory fails a bulk read whose buffer is smaller than the USB transfer, so reads go through a buffer of its size.
// Each read is capped too, as a precaution: BufferedInputStream would pass a longer read straight through to the accessory.
private const val ACCESSORY_READ_BUFFER_SIZE = 16384

class ConnectionViewModel(
    application: Application,
) : AndroidViewModel(application) {
    private val usbManager = application.getSystemService(UsbManager::class.java)
    private val mutableState = MutableStateFlow<ConnectionState>(ConnectionState.Disconnected)
    val state: StateFlow<ConnectionState> = mutableState.asStateFlow()
    private val mutableCapture = MutableStateFlow<CaptureState<ImageBitmap>?>(null)
    val capture: StateFlow<CaptureState<ImageBitmap>?> = mutableCapture.asStateFlow()
    private val mutablePreview = MutableStateFlow<ImageBitmap?>(null)
    val preview: StateFlow<ImageBitmap?> = mutablePreview.asStateFlow()

    private val opener =
        AccessoryOpener<UsbAccessory, ParcelFileDescriptor>(
            attachedAccessories = { usbManager.accessoryList?.toList().orEmpty() },
            open = usbManager::openAccessory,
        )

    private var openAccessory: ParcelFileDescriptor? = null
    private var controller: CaptureController<ImageBitmap>? = null
    private var outgoing: Channel<AppMessage>? = null

    @Volatile private var previewWanted = false

    private val mainDeadlines =
        DeadlineScheduler { delay, action ->
            val job =
                viewModelScope.launch {
                    delay(delay)
                    action()
                }
            job::cancel
        }

    private val detachReceiver =
        object : BroadcastReceiver() {
            override fun onReceive(
                context: Context,
                intent: Intent,
            ) {
                close()
                mutableState.value = ConnectionState.Disconnected
            }
        }

    init {
        ContextCompat.registerReceiver(
            application,
            detachReceiver,
            IntentFilter(UsbManager.ACTION_USB_ACCESSORY_DETACHED),
            ContextCompat.RECEIVER_NOT_EXPORTED,
        )
    }

    fun connectToAttachedAccessory() {
        usbManager.accessoryList?.firstOrNull { usbManager.hasPermission(it) }?.let(::connect)
    }

    fun connect(accessory: UsbAccessory) {
        if (openAccessory != null) return
        val descriptor =
            when (val result = opener.openIfAttached(accessory)) {
                is OpenResult.Opened -> {
                    result.handle
                }

                OpenResult.NotAttached -> {
                    Log.i(TAG, "accessory ${accessory.model} is no longer attached; not opening it")
                    mutableState.value = ConnectionState.Disconnected
                    return
                }

                is OpenResult.Failed -> {
                    Log.w(TAG, "failed to open accessory ${accessory.model}: ${result.detail}")
                    mutableState.value = ConnectionState.Failed(result.detail)
                    return
                }
            }
        openAccessory = descriptor
        val messages = Channel<AppMessage>(Channel.UNLIMITED)
        lateinit var created: CaptureController<ImageBitmap>
        created =
            CaptureController(
                send = { message ->
                    messages.trySend(message).onClosed { Log.w(TAG, "dropping ${message::class.simpleName}: the accessory is closed", it) }
                },
                deadlines = mainDeadlines,
                previewWanted = previewWanted,
            ) { if (controller === created) mutableCapture.value = it }
        controller = created
        outgoing = messages
        mutableCapture.value = null
        mutablePreview.value = null
        viewModelScope.launch(Dispatchers.IO) {
            val channel =
                AccessoryChannel(
                    BufferedInputStream(
                        BoundedReadInputStream(FileInputStream(descriptor.fileDescriptor), ACCESSORY_READ_BUFFER_SIZE),
                        ACCESSORY_READ_BUFFER_SIZE,
                    ),
                    FileOutputStream(descriptor.fileDescriptor),
                )
            launch { sendAll(channel, messages, descriptor) }
            runSession(
                channel,
                BuildConfig.VERSION_NAME,
                close = { closeDescriptor(descriptor) },
                onIncoming = { receive(created, it) },
                onError = { Log.w(TAG, "accessory session ended by an I/O failure", it) },
            ) { state ->
                viewModelScope.launch(Dispatchers.Main) {
                    if (openAccessory !== descriptor) return@launch
                    mutableState.value = state
                    if (state is ConnectionState.Connected) created.start()
                    if (state is ConnectionState.Disconnected || state is ConnectionState.Failed) close()
                }
            }
        }
    }

    fun shutter() {
        controller?.shutter()
    }

    fun shutdown() {
        controller?.shutdown()
    }

    fun dismissNotice() {
        controller?.dismissNotice()
    }

    fun loadSettings() {
        controller?.loadSettings()
    }

    fun changeSettings(settings: CameraSettings) {
        controller?.changeSettings(settings)
    }

    fun setPreviewWanted(wanted: Boolean) {
        previewWanted = wanted
        if (!wanted) mutablePreview.value = null
        controller?.setPreviewWanted(wanted)
    }

    private suspend fun sendAll(
        channel: AccessoryChannel,
        messages: Channel<AppMessage>,
        descriptor: ParcelFileDescriptor,
    ) {
        try {
            for (message in messages) channel.send(message)
        } catch (e: IOException) {
            Log.w(TAG, "failed to send to the accessory; closing it", e)
            closeDescriptor(descriptor)
        }
    }

    private fun receive(
        receiver: CaptureController<ImageBitmap>,
        incoming: Incoming,
    ) {
        when (incoming) {
            is Incoming.Message -> {
                onMain(receiver) { receiver.receive(incoming.message) }
            }

            is Incoming.Preview -> {
                if (!previewWanted) return
                val image = decodeJpeg(incoming.jpeg, "preview") ?: return
                onMain(receiver) { if (previewWanted) mutablePreview.value = image }
            }

            is Incoming.Thumbnail -> {
                val image = decodeJpeg(incoming.jpeg, "thumbnail ${incoming.id}")
                onMain(receiver) { receiver.receiveThumbnail(incoming.id, image) }
            }
        }
    }

    private fun onMain(
        receiver: CaptureController<ImageBitmap>,
        action: () -> Unit,
    ) {
        viewModelScope.launch(Dispatchers.Main) { if (controller === receiver) action() }
    }

    private fun close() {
        val descriptor = openAccessory ?: return
        openAccessory = null
        controller?.onDisconnected()
        controller = null
        outgoing?.close()
        outgoing = null
        mutablePreview.value = null
        closeDescriptor(descriptor)
    }

    override fun onCleared() {
        getApplication<Application>().unregisterReceiver(detachReceiver)
        close()
    }
}

private fun decodeJpeg(
    jpeg: ByteArray,
    what: String,
): ImageBitmap? {
    val bitmap = BitmapFactory.decodeByteArray(jpeg, 0, jpeg.size)
    if (bitmap == null) Log.w(TAG, "cannot decode the $what JPEG of ${jpeg.size} bytes")
    return bitmap?.asImageBitmap()
}

private fun closeDescriptor(descriptor: ParcelFileDescriptor) {
    try {
        descriptor.close()
    } catch (e: IOException) {
        Log.w(TAG, "failed to close the accessory file descriptor; dropping it", e)
    }
}
