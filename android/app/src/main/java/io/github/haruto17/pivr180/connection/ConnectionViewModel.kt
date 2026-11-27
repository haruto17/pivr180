package io.github.haruto17.pivr180.connection

import android.app.Application
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.hardware.usb.UsbAccessory
import android.hardware.usb.UsbManager
import android.os.ParcelFileDescriptor
import android.util.Log
import androidx.core.content.ContextCompat
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import io.github.haruto17.pivr180.BuildConfig
import io.github.haruto17.pivr180.protocol.AccessoryChannel
import kotlinx.coroutines.Dispatchers
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
private const val ACCESSORY_READ_BUFFER_SIZE = 16384

class ConnectionViewModel(
    application: Application,
) : AndroidViewModel(application) {
    private val usbManager = application.getSystemService(UsbManager::class.java)
    private val mutableState = MutableStateFlow<ConnectionState>(ConnectionState.Disconnected)
    val state: StateFlow<ConnectionState> = mutableState.asStateFlow()

    private val opener =
        AccessoryOpener<UsbAccessory, ParcelFileDescriptor>(
            attachedAccessories = { usbManager.accessoryList?.toList().orEmpty() },
            open = usbManager::openAccessory,
        )

    private var openAccessory: ParcelFileDescriptor? = null

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
        viewModelScope.launch(Dispatchers.IO) {
            val channel =
                AccessoryChannel(
                    BufferedInputStream(FileInputStream(descriptor.fileDescriptor), ACCESSORY_READ_BUFFER_SIZE),
                    FileOutputStream(descriptor.fileDescriptor),
                )
            runSession(channel, BuildConfig.VERSION_NAME, close = { closeDescriptor(descriptor) }) { state ->
                viewModelScope.launch(Dispatchers.Main) {
                    if (openAccessory !== descriptor) return@launch
                    mutableState.value = state
                    if (state is ConnectionState.Disconnected || state is ConnectionState.Failed) close()
                }
            }
        }
    }

    private fun close() {
        val descriptor = openAccessory ?: return
        openAccessory = null
        closeDescriptor(descriptor)
    }

    override fun onCleared() {
        getApplication<Application>().unregisterReceiver(detachReceiver)
        close()
    }
}

private fun closeDescriptor(descriptor: ParcelFileDescriptor) {
    try {
        descriptor.close()
    } catch (e: IOException) {
        Log.w(TAG, "failed to close the accessory file descriptor; dropping it", e)
    }
}
