package io.github.rachitkj.shape

import android.content.Context
import android.os.Handler
import android.os.Looper
import java.io.File
import java.security.MessageDigest
import java.util.Calendar
import java.util.concurrent.CopyOnWriteArraySet

/** The active config lives in filesDir/config.json; the built-in default is assets/default.json. */
object ConfigStore {
    private const val FILE = "config.json"
    private val listeners = CopyOnWriteArraySet<() -> Unit>()
    private val main = Handler(Looper.getMainLooper())

    fun read(context: Context): String {
        val f = File(context.filesDir, FILE)
        return if (f.exists()) f.readText() else defaultText(context)
    }

    fun defaultText(context: Context): String =
        context.assets.open("default.json").bufferedReader().use { it.readText() }

    @Synchronized
    fun write(context: Context, text: String) {
        val dir = context.filesDir
        val tmp = File(dir, "$FILE.tmp")
        tmp.writeText(text)
        val dest = File(dir, FILE)
        if (!tmp.renameTo(dest)) {
            dest.writeText(text)
            tmp.delete()
        }
        notifyChanged()
    }

    /** Same as shape/launcher.py config_hash(): first 12 hex chars of SHA-256 over UTF-8. */
    fun hash(text: String): String {
        val d = MessageDigest.getInstance("SHA-256").digest(text.toByteArray(Charsets.UTF_8))
        return d.joinToString("") { "%02x".format(it) }.substring(0, 12)
    }

    fun addListener(l: () -> Unit) = listeners.add(l)
    fun removeListener(l: () -> Unit) = listeners.remove(l)
    fun notifyChanged() = main.post { listeners.forEach { it() } }

    /** (day 1=Mon..7=Sun, minute of day) for rule evaluation. */
    fun now(): Pair<Int, Int> {
        val c = Calendar.getInstance()
        val day = (c.get(Calendar.DAY_OF_WEEK) + 5) % 7 + 1 // SUNDAY=1 -> 7, MONDAY=2 -> 1
        return day to (c.get(Calendar.HOUR_OF_DAY) * 60 + c.get(Calendar.MINUTE))
    }
}
