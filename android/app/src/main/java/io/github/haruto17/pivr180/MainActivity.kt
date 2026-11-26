package io.github.haruto17.pivr180

import android.content.Intent
import android.hardware.usb.UsbAccessory
import android.hardware.usb.UsbManager
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.viewModels
import androidx.compose.material3.MaterialTheme
import androidx.core.content.IntentCompat
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import io.github.haruto17.pivr180.connection.ConnectionViewModel
import io.github.haruto17.pivr180.ui.ConnectionScreen

class MainActivity : ComponentActivity() {
    private val viewModel: ConnectionViewModel by viewModels()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        connect(intent)
        setContent {
            MaterialTheme {
                val state = viewModel.state.collectAsStateWithLifecycle()
                ConnectionScreen(state.value)
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        connect(intent)
    }

    override fun onResume() {
        super.onResume()
        viewModel.connectToAttachedAccessory()
    }

    private fun connect(intent: Intent) {
        if (intent.action != UsbManager.ACTION_USB_ACCESSORY_ATTACHED) return
        IntentCompat
            .getParcelableExtra(intent, UsbManager.EXTRA_ACCESSORY, UsbAccessory::class.java)
            ?.let(viewModel::connect)
    }
}
