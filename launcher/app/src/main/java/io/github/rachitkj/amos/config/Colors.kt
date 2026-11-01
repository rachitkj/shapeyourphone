package io.github.rachitkj.amos.config

/** Colour parsing without android.graphics, so it runs in plain JVM unit tests. */
object Colors {
    fun parse(s: String?, fallback: Int): Int = tryParse(s) ?: fallback

    fun tryParse(s: String?): Int? {
        if (s == null || !s.startsWith("#")) return null
        val hex = s.substring(1)
        if (hex.isEmpty() || !hex.all { it in '0'..'9' || it.lowercaseChar() in 'a'..'f' }) return null
        return when (hex.length) {
            3 -> {
                val (r, g, b) = Triple(hex[0], hex[1], hex[2])
                "FF$r$r$g$g$b$b".toLong(16).toInt()
            }
            6 -> "FF$hex".toLong(16).toInt()
            8 -> hex.toLong(16).toInt()
            else -> null
        }
    }

    fun withAlpha(argb: Int, alpha: Float): Int {
        val a = (alpha.coerceIn(0f, 1f) * 255).toInt()
        return (a shl 24) or (argb and 0x00FFFFFF)
    }

    /** Approximate relative luminance, 0 (black) .. 1 (white). */
    fun luminance(argb: Int): Double {
        val r = (argb shr 16 and 0xFF) / 255.0
        val g = (argb shr 8 and 0xFF) / 255.0
        val b = (argb and 0xFF) / 255.0
        return 0.2126 * r + 0.7152 * g + 0.0722 * b
    }
}
