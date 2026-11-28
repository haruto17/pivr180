package io.github.haruto17.pivr180.protocol

import java.io.FilterInputStream
import java.io.InputStream

class BoundedReadInputStream(
    input: InputStream,
    private val maxReadSize: Int,
) : FilterInputStream(input) {
    init {
        require(maxReadSize > 0) { "maxReadSize must be positive, was $maxReadSize" }
    }

    override fun read(): Int = `in`.read()

    override fun read(
        b: ByteArray,
        off: Int,
        len: Int,
    ): Int = `in`.read(b, off, minOf(len, maxReadSize))
}
