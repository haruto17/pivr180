package io.github.haruto17.pivr180.connection

sealed interface OpenResult<out H> {
    data class Opened<H>(
        val handle: H,
    ) : OpenResult<H>

    data object NotAttached : OpenResult<Nothing>

    data class Failed(
        val detail: String,
    ) : OpenResult<Nothing>
}

class AccessoryOpener<A, H>(
    private val attachedAccessories: () -> List<A>,
    private val open: (A) -> H?,
) {
    fun openIfAttached(accessory: A): OpenResult<H> {
        if (accessory !in attachedAccessories()) return OpenResult.NotAttached
        val handle =
            try {
                open(accessory)
            } catch (_: IllegalArgumentException) {
                // UsbManager.openAccessory throws this when the accessory was detached after the check above.
                return OpenResult.NotAttached
            } catch (e: SecurityException) {
                return OpenResult.Failed("no permission to open the accessory: ${e.message}")
            }
        return if (handle == null) OpenResult.Failed("cannot open the accessory") else OpenResult.Opened(handle)
    }
}
