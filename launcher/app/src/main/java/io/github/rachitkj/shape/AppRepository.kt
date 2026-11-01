package io.github.rachitkj.shape

import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.pm.LauncherActivityInfo
import android.content.pm.LauncherApps
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.ColorMatrix
import android.graphics.ColorMatrixColorFilter
import android.graphics.Rect
import android.graphics.drawable.AdaptiveIconDrawable
import android.graphics.drawable.ColorDrawable
import android.graphics.drawable.Drawable
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Process
import android.os.UserHandle
import android.provider.MediaStore
import android.util.LruCache
import io.github.rachitkj.shape.config.IconStyle

class AppEntry(val info: LauncherActivityInfo) {
    val pkg: String get() = info.componentName.packageName
    val component: ComponentName get() = info.componentName
    val label: String = info.label?.toString()?.ifBlank { null } ?: info.componentName.packageName
}

class AppRepository(private val context: Context) {
    private val launcherApps = context.getSystemService(LauncherApps::class.java)
    private val user: UserHandle = Process.myUserHandle()

    fun load(): List<AppEntry> =
        launcherApps.getActivityList(null, user)
            .filter { it.componentName.packageName != context.packageName }
            .map { AppEntry(it) }
            .sortedWith(compareBy(String.CASE_INSENSITIVE_ORDER) { it.label })

    /** Resolve an app reference: package, package/.Activity, or @dialer/@sms/@browser/@camera/@settings. */
    fun resolve(ref: String, all: List<AppEntry>): AppEntry? {
        if (ref.startsWith("@")) {
            val pkg = resolveToken(ref) ?: return null
            return all.firstOrNull { it.pkg == pkg }
        }
        val slash = ref.indexOf('/')
        if (slash > 0) {
            val pkg = ref.substring(0, slash)
            var cls = ref.substring(slash + 1)
            if (cls.startsWith(".")) cls = pkg + cls
            return all.firstOrNull { it.pkg == pkg && it.component.className == cls } ?: all.firstOrNull { it.pkg == pkg }
        }
        return all.firstOrNull { it.pkg == ref }
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
        launcherApps.startMainActivity(e.component, user, bounds, opts)

    fun openAppInfo(e: AppEntry) =
        launcherApps.startAppDetailsActivity(e.component, user, null, null)

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
        val key = "${e.component.flattenToShortString()}|$style|$tint|$sizePx"
        icons.get(key)?.let { return it }
        val base = try {
            e.info.getIcon(0)
        } catch (_: Exception) {
            return null
        }
        val d: Drawable = when (style) {
            IconStyle.MONO -> monochrome(base, tint) ?: grayscale(base)
            IconStyle.GRAYSCALE -> grayscale(base)
            else -> base
        }
        val bmp = Bitmap.createBitmap(sizePx, sizePx, Bitmap.Config.ARGB_8888)
        d.setBounds(0, 0, sizePx, sizePx)
        d.draw(Canvas(bmp))
        icons.put(key, bmp)
        return bmp
    }

    private fun grayscale(d: Drawable): Drawable =
        d.mutate().apply { colorFilter = ColorMatrixColorFilter(ColorMatrix().apply { setSaturation(0f) }) }

    private fun monochrome(d: Drawable, tint: Int): Drawable? {
        if (Build.VERSION.SDK_INT < 33) return null
        if (d !is AdaptiveIconDrawable) return null
        val mono = d.monochrome ?: return null
        mono.mutate().setTint(tint)
        return AdaptiveIconDrawable(ColorDrawable(Color.TRANSPARENT), mono)
    }
}
