package io.github.rachitkj.shape

import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.pm.LauncherActivityInfo
import android.content.pm.LauncherApps
import android.content.pm.PackageManager
import android.content.pm.ShortcutInfo
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.ColorMatrix
import android.graphics.ColorMatrixColorFilter
import android.graphics.Rect
import android.graphics.drawable.AdaptiveIconDrawable
import android.graphics.drawable.Drawable
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Process
import android.os.UserHandle
import android.provider.MediaStore
import android.util.LruCache
import io.github.rachitkj.shape.config.IconStyle

class AppEntry(val info: LauncherActivityInfo, val isWork: Boolean) {
    val pkg: String get() = info.componentName.packageName
    val component: ComponentName get() = info.componentName
    val user: UserHandle get() = info.user
    val label: String = info.label?.toString()?.ifBlank { null } ?: info.componentName.packageName
}

class AppRepository(private val context: Context) {
    private val launcherApps = context.getSystemService(LauncherApps::class.java)
    private val user: UserHandle = Process.myUserHandle()

    /** Apps from every profile on the phone: personal first, then work-profile copies (badged). */
    fun load(): List<AppEntry> {
        val profiles = try {
            launcherApps.profiles.sortedBy { if (it == user) 0 else 1 }
        } catch (_: Exception) {
            listOf(user)
        }
        return profiles.flatMap { profile ->
            try {
                launcherApps.getActivityList(null, profile)
            } catch (_: Exception) {
                emptyList() // e.g. a work profile that is paused
            }.filter { it.componentName.packageName != context.packageName }.map { AppEntry(it, profile != user) }
        }.sortedWith(compareBy<AppEntry, String>(String.CASE_INSENSITIVE_ORDER) { it.label }.thenBy { it.isWork })
    }

    /** Resolve an app reference: package, package/.Activity, or @dialer/@sms/@browser/@camera/@settings. */
    fun resolve(ref: String, all: List<AppEntry>): AppEntry? {
        if (ref.startsWith("@")) {
            val pkg = resolveToken(ref) ?: return null
            return all.firstOrNull { it.pkg == pkg && !it.isWork } ?: all.firstOrNull { it.pkg == pkg }
        }
        val slash = ref.indexOf('/')
        if (slash > 0) {
            val pkg = ref.substring(0, slash)
            var cls = ref.substring(slash + 1)
            if (cls.startsWith(".")) cls = pkg + cls
            return all.firstOrNull { it.pkg == pkg && it.component.className == cls && !it.isWork }
                ?: all.firstOrNull { it.pkg == pkg && !it.isWork } ?: all.firstOrNull { it.pkg == pkg }
        }
        return all.firstOrNull { it.pkg == ref && !it.isWork } ?: all.firstOrNull { it.pkg == ref }
    }

    @Suppress("DEPRECATION")
    fun resolveToken(token: String): String? {
        val intent = when (token) {
            "@dialer" -> Intent(Intent.ACTION_DIAL)
            "@sms" -> Intent(Intent.ACTION_SENDTO, Uri.parse("smsto:"))
            "@browser" -> Intent(Intent.ACTION_VIEW, Uri.parse("https://example.com")).addCategory(Intent.CATEGORY_BROWSABLE)
            "@camera" -> Intent(MediaStore.INTENT_ACTION_STILL_IMAGE_CAMERA)
            "@settings" -> return "com.android.settings"
            else -> return null
        }
        val pm = context.packageManager
        val default = pm.resolveActivity(intent, PackageManager.MATCH_DEFAULT_ONLY)?.activityInfo?.packageName
        if (default != null && default != "android") return default
        // No default chosen yet (the system would show a chooser): use the first handler.
        return pm.queryIntentActivities(intent, 0).firstOrNull()?.activityInfo?.packageName
    }

    fun launch(e: AppEntry, bounds: Rect?, opts: Bundle?) =
        launcherApps.startMainActivity(e.component, e.user, bounds, opts)

    fun openAppInfo(e: AppEntry) =
        launcherApps.startAppDetailsActivity(e.component, e.user, null, null)

    /** The app's long-press shortcuts (only available to the default home app). */
    fun shortcuts(e: AppEntry): List<ShortcutInfo> {
        if (!launcherApps.hasShortcutHostPermission()) return emptyList()
        val q = LauncherApps.ShortcutQuery()
            .setPackage(e.pkg)
            .setActivity(e.component)
            .setQueryFlags(LauncherApps.ShortcutQuery.FLAG_MATCH_MANIFEST or LauncherApps.ShortcutQuery.FLAG_MATCH_DYNAMIC)
        return try {
            launcherApps.getShortcuts(q, e.user).orEmpty().filter { it.isEnabled }.sortedBy { it.rank }.take(4)
        } catch (_: Exception) {
            emptyList() // locked work profile, or the app went away
        }
    }

    fun startShortcut(s: ShortcutInfo, bounds: Rect?) = launcherApps.startShortcut(s, bounds, null)

    fun register(onChange: () -> Unit): LauncherApps.Callback {
        val cb = object : LauncherApps.Callback() {
            override fun onPackageRemoved(packageName: String?, user: UserHandle?) = onChange()
            override fun onPackageAdded(packageName: String?, user: UserHandle?) = onChange()
            override fun onPackageChanged(packageName: String?, user: UserHandle?) = onChange()
            override fun onPackagesAvailable(packageNames: Array<out String>?, user: UserHandle?, replacing: Boolean) = onChange()
            override fun onPackagesUnavailable(packageNames: Array<out String>?, user: UserHandle?, replacing: Boolean) = onChange()
        }
        launcherApps.registerCallback(cb)
        return cb
    }

    fun unregister(cb: LauncherApps.Callback) = launcherApps.unregisterCallback(cb)

    // -- icons: rendered once to bitmaps so many views can share them safely --

    private val icons = object : LruCache<String, Bitmap>((Runtime.getRuntime().maxMemory() / 16).toInt()) {
        override fun sizeOf(key: String, value: Bitmap) = value.byteCount
    }

    fun clearIcons() = icons.evictAll()

    fun icon(e: AppEntry, style: IconStyle, tint: Int, sizePx: Int): Bitmap? {
        if (style == IconStyle.NONE || sizePx <= 0) return null
        val key = "${e.component.flattenToShortString()}|${e.user.hashCode()}|$style|$tint|$sizePx"
        icons.get(key)?.let { return it }
        val base = try {
            val raw = e.info.getIcon(0)
            if (e.isWork) context.packageManager.getUserBadgedIcon(raw, e.user) else raw
        } catch (_: Exception) {
            return null
        }
        val bmp = Bitmap.createBitmap(sizePx, sizePx, Bitmap.Config.ARGB_8888)
        val canvas = Canvas(bmp)
        val mono = if (style == IconStyle.MONO) monochromeLayer(base) else null
        if (mono != null) {
            // Draw the glyph layer on its own. Wrapping it in a new AdaptiveIconDrawable would paint
            // the layers onto black first (that's how adaptive icons render), giving dark discs.
            // Adaptive layers are 108dp with the visible 72dp in the middle: scale by 1.5, offset by -0.25.
            val pad = sizePx / 4
            mono.mutate().setTint(tint)
            mono.setBounds(-pad, -pad, sizePx + pad, sizePx + pad)
            mono.draw(canvas)
        } else {
            val d = if (style == IconStyle.MONO || style == IconStyle.GRAYSCALE) grayscale(base) else base
            d.setBounds(0, 0, sizePx, sizePx)
            d.draw(canvas)
        }
        icons.put(key, bmp)
        return bmp
    }

    private fun grayscale(d: Drawable): Drawable =
        d.mutate().apply { colorFilter = ColorMatrixColorFilter(ColorMatrix().apply { setSaturation(0f) }) }

    private fun monochromeLayer(d: Drawable): Drawable? {
        if (Build.VERSION.SDK_INT < 33) return null
        if (d !is AdaptiveIconDrawable) return null
        return d.monochrome
    }
}
