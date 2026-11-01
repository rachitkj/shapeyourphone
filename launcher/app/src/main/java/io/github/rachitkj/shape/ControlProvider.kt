package io.github.rachitkj.shape

import android.app.AppOpsManager
import android.app.usage.UsageStatsManager
import android.content.ContentProvider
import android.content.ContentValues
import android.content.Context
import android.database.Cursor
import android.net.Uri
import android.os.Binder
import android.os.Build
import android.os.Bundle
import android.os.Process
import android.util.Base64
import io.github.rachitkj.shape.config.ConfigParser
import io.github.rachitkj.shape.config.Rules
import org.json.JSONArray
import org.json.JSONObject

/**
 * Control channel for the shape CLI:
 *   adb shell content call --uri content://io.github.rachitkj.shape.control --method ping
 *
 * Only the adb shell user (uid 2000) and root may call it, so no other app on
 * the phone can read or rewrite the home screen. Free text in replies is
 * base64 (NO_WRAP) so the printed Bundle stays trivially parseable.
 */
class ControlProvider : ContentProvider() {

    override fun onCreate(): Boolean = true

    override fun call(method: String, arg: String?, extras: Bundle?): Bundle? {
        val uid = Binder.getCallingUid()
        if (uid != SHELL_UID && uid != ROOT_UID && uid != Process.myUid()) {
            throw SecurityException("Shape control is only available over adb")
        }
        val ctx = context ?: return error("launcher not ready")
        return try {
            when (method) {
                "ping" -> ok().apply {
                    putString("version", versionName(ctx))
                    putString("config_hash", ConfigStore.hash(ConfigStore.read(ctx)))
                    putString("active_rules_b64", b64(JSONArray(activeRules(ctx)).toString()))
                }
                "get_config" -> ok().apply { putString("data_b64", b64(ConfigStore.read(ctx))) }
                "effective_config" -> ok().apply {
                    val (d, m) = ConfigStore.now()
                    putString("data_b64", b64(Rules.effective(ConfigParser.parseRoot(ConfigStore.read(ctx)), d, m).config.toString(2)))
                }
                "list_apps" -> ok().apply { putString("data_b64", b64(appsJson(ctx))) }
                "usage" -> ok().apply { putString("data_b64", b64(usageJson(ctx, arg?.toIntOrNull() ?: 30))) }
                "stage_begin" -> {
                    synchronized(stage) { stage.setLength(0) }
                    ok()
                }
                "stage_append" -> {
                    synchronized(stage) { stage.append(arg ?: "") }
                    ok()
                }
                "stage_commit" -> commit(ctx, arg)
                "reload" -> {
                    ConfigStore.notifyChanged()
                    ok()
                }
                else -> error("unknown method $method")
            }
        } catch (e: Exception) {
            error(e.message ?: e.javaClass.simpleName)
        }
    }

    private fun commit(ctx: Context, expectedHash: String?): Bundle {
        val encoded = synchronized(stage) { stage.toString().also { stage.setLength(0) } }
        val text = String(Base64.decode(encoded, Base64.DEFAULT), Charsets.UTF_8)
        val h = ConfigStore.hash(text)
        if (!expectedHash.isNullOrEmpty() && expectedHash != h) {
            return error("config arrived incomplete (got $h, expected $expectedHash) — push again")
        }
        val (d, m) = ConfigStore.now()
        ConfigParser.parse(text, d, m) // throws ConfigException with a readable message if unusable
        ConfigStore.write(ctx, text)
        return ok().apply { putString("config_hash", h) }
    }

    private fun activeRules(ctx: Context): List<String> {
        val (d, m) = ConfigStore.now()
        return try {
            Rules.effective(ConfigParser.parseRoot(ConfigStore.read(ctx)), d, m).active
        } catch (_: Exception) {
            emptyList()
        }
    }

    private fun appsJson(ctx: Context): String {
        val arr = JSONArray()
        for (a in AppRepository(ctx).load()) {
            arr.put(JSONObject().put("package", a.pkg).put("activity", a.component.className).put("label", a.label))
        }
        return arr.toString()
    }

    /** Foreground time per launchable app over the last [days]. Needs usage access (an appop the owner grants). */
    private fun usageJson(ctx: Context, days: Int): String {
        if (!hasUsageAccess(ctx)) throw IllegalStateException("usage access not granted — run: shape launcher usage-access")
        val usm = ctx.getSystemService(UsageStatsManager::class.java)
        val end = System.currentTimeMillis()
        val stats = usm.queryAndAggregateUsageStats(end - days.coerceIn(1, 365) * 86_400_000L, end)
        val arr = JSONArray()
        for (a in AppRepository(ctx).load().distinctBy { it.pkg }) {
            val s = stats[a.pkg]
            arr.put(
                JSONObject().put("package", a.pkg).put("label", a.label)
                    .put("foreground_ms", s?.totalTimeInForeground ?: 0L)
                    .put("last_used", s?.lastTimeUsed ?: 0L),
            )
        }
        return arr.toString()
    }

    private fun hasUsageAccess(ctx: Context): Boolean {
        val aom = ctx.getSystemService(AppOpsManager::class.java)
        val mode = if (Build.VERSION.SDK_INT >= 29) {
            aom.unsafeCheckOpNoThrow(AppOpsManager.OPSTR_GET_USAGE_STATS, Process.myUid(), ctx.packageName)
        } else {
            @Suppress("DEPRECATION")
            aom.checkOpNoThrow(AppOpsManager.OPSTR_GET_USAGE_STATS, Process.myUid(), ctx.packageName)
        }
        return mode == AppOpsManager.MODE_ALLOWED
    }

    private fun versionName(ctx: Context): String = try {
        ctx.packageManager.getPackageInfo(ctx.packageName, 0).versionName ?: "?"
    } catch (_: Exception) {
        "?"
    }

    private fun ok() = Bundle().apply { putBoolean("ok", true) }
    private fun error(msg: String) = Bundle().apply {
        putBoolean("ok", false)
        putString("error_b64", b64(msg))
    }
    private fun b64(s: String) = Base64.encodeToString(s.toByteArray(Charsets.UTF_8), Base64.NO_WRAP)

    // Not a data provider: everything else is refused.
    override fun query(uri: Uri, projection: Array<out String>?, selection: String?, selectionArgs: Array<out String>?, sortOrder: String?): Cursor? = null
    override fun getType(uri: Uri): String? = null
    override fun insert(uri: Uri, values: ContentValues?): Uri? = null
    override fun delete(uri: Uri, selection: String?, selectionArgs: Array<out String>?): Int = 0
    override fun update(uri: Uri, values: ContentValues?, selection: String?, selectionArgs: Array<out String>?): Int = 0

    companion object {
        private const val SHELL_UID = 2000
        private const val ROOT_UID = 0
        private val stage = StringBuilder()
    }
}
