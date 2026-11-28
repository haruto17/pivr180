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
import androidx.compose.runtime.getValue
import androidx.core.content.IntentCompat
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import io.github.haruto17.pivr180.capture.AppScreen
import io.github.haruto17.pivr180.capture.appScreen
import io.github.haruto17.pivr180.connection.ConnectionViewModel
import io.github.haruto17.pivr180.ui.CaptureScreen
import io.github.haruto17.pivr180.ui.ConnectionScreen
import io.github.haruto17.pivr180.ui.Destination
import io.github.haruto17.pivr180.ui.MainScreen
import io.github.haruto17.pivr180.ui.SettingsScreen
import io.github.haruto17.pivr180.ui.ShutDownScreen

class MainActivity : ComponentActivity() {
    private val viewModel: ConnectionViewModel by viewModels()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        connect(intent)
        setContent {
            MaterialTheme {
                val connection by viewModel.state.collectAsStateWithLifecycle()
                val capture by viewModel.capture.collectAsStateWithLifecycle()
                when (val screen = appScreen(connection, capture)) {
                    is AppScreen.Connection -> {
                        ConnectionScreen(screen.state)
                    }

                    AppScreen.ShutDown -> {
                        ShutDownScreen()
                    }

                    is AppScreen.Capture -> {
                        MainScreen { destination ->
                            when (destination) {
                                Destination.CAPTURE -> {
                                    val preview by viewModel.preview.collectAsStateWithLifecycle()
                                    CaptureScreen(
                                        state = screen.state,
                                        preview = preview,
                                        onShutter = viewModel::shutter,
                                        onShutdown = viewModel::shutdown,
                                        onDismissNotice = viewModel::dismissNotice,
                                    )
                                }

                                Destination.SETTINGS -> {
                                    SettingsScreen(
                                        state = screen.state.settings,
                                        onLoad = viewModel::loadSettings,
                                        onChange = viewModel::changeSettings,
                                    )
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        connect(intent)
    }

    override fun onStart() {
        super.onStart()
        viewModel.setPreviewWanted(true)
    }

    override fun onStop() {
        super.onStop()
        // Not stopped across a configuration change: the new activity starts right away and would only restart it.
        if (!isChangingConfigurations) viewModel.setPreviewWanted(false)
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
