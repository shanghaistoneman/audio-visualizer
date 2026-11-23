package com.example.audiovisualizer.core

import kotlin.math.pow

/** Float 幂运算扩展（kotlin.math.pow 仅接受 Double）。 */
fun Float.powf(exponent: Float): Float = this.toDouble().pow(exponent.toDouble()).toFloat()
