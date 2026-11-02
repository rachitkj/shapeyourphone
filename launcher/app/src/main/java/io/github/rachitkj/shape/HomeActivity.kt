package io.github.rachitkj.shape

import android.Manifest
import android.annotation.SuppressLint
import android.app.Activity
import android.app.ActivityOptions
import android.content.BroadcastReceiver
import android.content.ContentUris
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.LauncherApps
import android.content.pm.PackageManager
import android.graphics.Rect
import android.graphics.drawable.ColorDrawable
import android.graphics.drawable.GradientDrawable
import android.os.Build
import android.os.Bundle
import android.provider.CalendarContract
import android.provider.Settings
import android.text.format.DateFormat
import android.util.TypedValue
import android.view.GestureDetector
import android.view.Gravity
import android.view.KeyEvent
import android.view.MotionEvent
import android.view.View
import android.view.WindowInsets
import android.view.WindowInsetsController
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.PopupMenu
import android.widget.TextClock
import android.widget.Toast
import android.window.OnBackInvokedCallback
import android.window.OnBackInvokedDispatcher
import io.github.rachitkj.shape.config.Align
import io.github.rachitkj.shape.config.AppsStyle
import io.github.rachitkj.shape.config.Colors
import io.github.rachitkj.shape.config.Config
import io.github.rachitkj.shape.config.ConfigException
import io.github.rachitkj.shape.config.ConfigParser
import io.github.rachitkj.shape.config.Rules
import io.github.rachitkj.shape.config.Theme
import io.github.rachitkj.shape.config.Widget
import kotlin.math.abs

private const val MENU_APP_INFO = 1000

class HomeActivity : Activity() {

    private lateinit var apps: AppRepository
    private lateinit var root: FrameLayout
    private lateinit var home: LinearLayout
    private lateinit var widgets: LinearLayout
    private lateinit var dock: LinearLayout
    private lateinit var drawer: DrawerView
    private lateinit var pause: PauseView
    private var pausePkgs: Set<String> = emptySet()
    private lateinit var flings: GestureDetector
    private lateinit var taps: GestureDetector

    private var config: Config? = null
    private var allApps: List<AppEntry> = emptyList()
    private var activeKey = ""
    private var insets = intArrayOf(0, 0, 0, 0)
    private var appsCallback: LauncherApps.Callback? = null
    private var backCallback: Any? = null // OnBackInvokedCallback on API 33+
    private var tickRegistered = false

    private val configListener: () -> Unit = { reload() }

    private val tick = object : BroadcastReceiver() {
        override fun onReceive(context: Context?, intent: Intent?) = checkRules()
    }

    @SuppressLint("ClickableViewAccessibility")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        apps = AppRepository(this)
        drawEdgeToEdge()

        root = FrameLayout(this)
        home = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        widgets = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        dock = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
        }
        home.addView(widgets, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, 0, 1f))
        home.addView(dock, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT))
        drawer = DrawerView(this, apps, ::launch, ::appMenu)
        root.addView(home, FrameLayout.LayoutParams(FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.MATCH_PARENT))
        root.addView(drawer, FrameLayout.LayoutParams(FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.MATCH_PARENT))
        pause = PauseView(this)
        root.addView(pause, FrameLayout.LayoutParams(FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.MATCH_PARENT))
        setContentView(root)

        root.setOnApplyWindowInsetsListener { _, wi ->
            insets = systemInsets(wi)
            applyPadding()
            wi
        }

        val minFling = dp(48)
        flings = GestureDetector(this, object : GestureDetector.SimpleOnGestureListener() {
            override fun onFling(e1: MotionEvent?, e2: MotionEvent, velocityX: Float, velocityY: Float): Boolean {
                val start = e1 ?: return false
                val dy = e2.y - start.y
                if (abs(dy) < minFling || abs(velocityY) < abs(velocityX) || abs(velocityY) < 600) return false
                val g = config?.gestures ?: return false
                perform(if (dy < 0) g.swipeUp else g.swipeDown)
                return true
            }
        })
        taps = GestureDetector(this, object : GestureDetector.SimpleOnGestureListener() {
            override fun onDown(e: MotionEvent) = true
            override fun onDoubleTap(e: MotionEvent): Boolean {
                config?.gestures?.let { perform(it.doubleTap) }
                return true
            }
            override fun onLongPress(e: MotionEvent) {
                config?.gestures?.let { perform(it.longPress) }
            }
        })
        // Empty-area gestures only: touches on apps are consumed by the app views first.
        home.setOnTouchListener { _, ev -> taps.onTouchEvent(ev) }

        ConfigStore.addListener(configListener)
        appsCallback = apps.register {
            apps.clearIcons()
            allApps = apps.load()
            render()
        }
        allApps = apps.load()
        reload()
    }

    override fun onDestroy() {
        ConfigStore.removeListener(configListener)
        appsCallback?.let { apps.unregister(it) }
        super.onDestroy()
    }

    override fun onStart() {
        super.onStart()
        val filter = IntentFilter().apply {
            addAction(Intent.ACTION_TIME_TICK)
            addAction(Intent.ACTION_TIME_CHANGED)
            addAction(Intent.ACTION_TIMEZONE_CHANGED)
        }
        if (Build.VERSION.SDK_INT >= 33) registerReceiver(tick, filter, Context.RECEIVER_NOT_EXPORTED)
        else registerReceiver(tick, filter)
        tickRegistered = true
        reload() // refreshes rules and the calendar widget every time home comes back
    }

    override fun onStop() {
        if (tickRegistered) {
            unregisterReceiver(tick)
            tickRegistered = false
        }
        closeOverlays()
        super.onStop()
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        // Pressing Home while already home: close the drawer.
        if (intent.hasCategory(Intent.CATEGORY_HOME)) closeOverlays()
    }

    override fun dispatchTouchEvent(ev: MotionEvent): Boolean {
        if (!drawer.isOpen && !pause.isOpen) flings.onTouchEvent(ev)
        return super.dispatchTouchEvent(ev)
    }

    override fun dispatchKeyEvent(event: KeyEvent): Boolean {
        // API 33+ uses OnBackInvokedCallback (registered while the drawer is open).
        if (Build.VERSION.SDK_INT < 33 && event.keyCode == KeyEvent.KEYCODE_BACK) {
            if (event.action == KeyEvent.ACTION_UP) onBack()
            return true // the home screen never "goes back"
        }
        return super.dispatchKeyEvent(event)
    }

    // -- config ----------------------------------------------------------------

    private fun reload() {
        val (day, minute) = ConfigStore.now()
        config = try {
            ConfigParser.parse(ConfigStore.read(this), day, minute)
        } catch (e: ConfigException) {
            Toast.makeText(this, "Shape: ${e.message} — using defaults", Toast.LENGTH_LONG).show()
            ConfigParser.parse(ConfigStore.defaultText(this), day, minute)
        }
        activeKey = config?.activeRules?.joinToString("|") ?: ""
        render()
    }

    /** Called every minute while visible: re-render only if the set of active rules changed. */
    private fun checkRules() {
        val (day, minute) = ConfigStore.now()
        val key = try {
            Rules.effective(ConfigParser.parseRoot(ConfigStore.read(this)), day, minute).active.joinToString("|")
        } catch (_: Exception) {
            return
        }
        if (key != activeKey) {
            reload()
        } else if (minute % 5 == 0 && config?.home?.any { it is Widget.Calendar } == true) {
            render() // keep "next event" current while the home screen stays open
        }
    }

    // -- rendering -------------------------------------------------------------

    private fun render() {
        val c = config ?: return
        val t = c.theme
        root.background = ColorDrawable(t.background ?: Colors.withAlpha(0xFF000000.toInt(), t.dim))
        setBarIcons(lightBackground = t.background != null && Colors.luminance(t.background) > 0.6)
        widgets.removeAllViews()
        for (w in c.home) build(w, c)?.let { (v, lp) -> widgets.addView(v, lp) }
        buildDock(c)
        pausePkgs = c.pause.apps.mapNotNull { apps.resolve(it, allApps)?.pkg }.toSet()
        drawer.bind(c, allApps)
        applyPadding()
    }

    private fun applyPadding() {
        val pad = dp(config?.theme?.padding ?: 24)
        val (l, t, r, b) = insets.toList()
        home.setPadding(l + pad, t + pad, r + pad, b + dp(12))
        drawer.setInsets(l, t, r, b)
        pause.setInsets(l, t, r, b)
    }

    private fun wrap() = LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT)

    private fun build(w: Widget, c: Config): Pair<View, LinearLayout.LayoutParams>? {
        val t = c.theme
        return when (w) {
            is Widget.Clock -> {
                val box = LinearLayout(this).apply {
                    orientation = LinearLayout.VERTICAL
                    gravity = gravityOf(w.align)
                }
                val clock = TextClock(this).apply {
                    setTextColor(t.foreground)
                    setTextSize(TypedValue.COMPLEX_UNIT_SP, w.size)
                    typeface = fontFor(if (t.font == "sans") "light" else t.font)
                    format12Hour = w.format ?: "h:mm"
                    format24Hour = w.format ?: "HH:mm"
                    includeFontPadding = false
                }
                box.addView(clock, LinearLayout.LayoutParams(LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT))
                if (w.showDate) {
                    val date = TextClock(this).apply {
                        setTextColor(t.secondary)
                        setTextSize(TypedValue.COMPLEX_UNIT_SP, maxOf(13f, t.textSize * 0.8f))
                        typeface = fontFor(t.font)
                        format12Hour = w.dateFormat
                        format24Hour = w.dateFormat
                    }
                    box.addView(date, LinearLayout.LayoutParams(LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT))
                }
                // Tapping the clock opens the alarm app, like most launchers.
                box.setOnClickListener { safeStart(Intent(android.provider.AlarmClock.ACTION_SHOW_ALARMS)) }
                box to wrap()
            }
            is Widget.Text -> styledText(t, w.size ?: t.textSize, t.color(w.color)).apply {
                text = w.text
                gravity = gravityOf(w.align)
            } to wrap()
            is Widget.Spacer -> View(this) to (
                if (w.flex > 0) LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, 0, w.flex)
                else LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, dp(w.height))
            )
            is Widget.Search -> styledText(t, t.textSize * 0.9f, t.secondary).apply {
                text = w.hint ?: getString(R.string.search_hint)
                setPadding(dp(18), dp(12), dp(18), dp(12))
                background = GradientDrawable().apply {
                    cornerRadius = dp(24).toFloat()
                    setColor(Colors.withAlpha(t.foreground, 0.10f))
                }
                setOnClickListener { openDrawer(focusSearch = true) }
            } to wrap()
            is Widget.Apps -> appsWidget(w, c)?.let { it to wrap() }
            is Widget.Calendar -> calendarWidget(w, t)?.let { it to wrap() }
        }
    }

    private fun visible(refs: List<String>, c: Config): List<AppEntry> =
        refs.mapNotNull { apps.resolve(it, allApps) }.filter { it.pkg !in c.hidden }.distinctBy { it.component }

    private fun label(e: AppEntry, c: Config) = c.labels[e.pkg] ?: e.label

    private fun appsWidget(w: Widget.Apps, c: Config): View? {
        val entries = visible(w.apps, c)
        if (entries.isEmpty()) return null
        val t = c.theme
        val box = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = gravityOf(w.align)
        }
        when (w.style) {
            AppsStyle.LIST -> for (e in entries) {
                val h = appRow(t, w.size ?: t.textSize, w.align)
                bindApp(h, e, c, dp(t.iconSize * 0.8f))
                box.addView(h.root, wrap())
            }
            AppsStyle.GRID, AppsStyle.ROW -> {
                val perRow = if (w.style == AppsStyle.ROW) entries.size else w.columns
                entries.chunked(perRow).forEach { chunk ->
                    val row = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
                    for (e in chunk) {
                        val h = appCell(t, w.labels)
                        bindApp(h, e, c, dp(t.iconSize))
                        row.addView(h.root, LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
                    }
                    // keep cells the same width in a partly filled last row
                    repeat(perRow - chunk.size) { row.addView(View(this), LinearLayout.LayoutParams(0, 1, 1f)) }
                    box.addView(row, wrap())
                }
            }
        }
        return box
    }

    private fun buildDock(c: Config) {
        dock.removeAllViews()
        val entries = visible(c.dock.apps, c)
        dock.visibility = if (entries.isEmpty()) View.GONE else View.VISIBLE
        for (e in entries) {
            val h = appCell(c.theme, c.dock.labels)
            bindApp(h, e, c, dp(c.theme.iconSize))
            dock.addView(h.root, LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
        }
    }

    private fun bindApp(h: AppViewHolder, e: AppEntry, c: Config, iconPx: Int) {
        h.label.text = label(e, c)
        h.icon.setImageBitmap(apps.icon(e, c.theme.iconStyle, c.theme.foreground, iconPx))
        h.root.contentDescription = label(e, c)
        h.root.setOnClickListener { launch(e, it) }
        h.root.setOnLongClickListener {
            appMenu(e, it)
            true
        }
    }

    private fun calendarWidget(w: Widget.Calendar, t: Theme): View? {
        if (checkSelfPermission(Manifest.permission.READ_CALENDAR) != PackageManager.PERMISSION_GRANTED) return null
        val now = System.currentTimeMillis()
        val uri = CalendarContract.Instances.CONTENT_URI.buildUpon().also {
            ContentUris.appendId(it, now)
            ContentUris.appendId(it, now + w.hours * 3_600_000L)
        }.build()
        val proj = arrayOf(CalendarContract.Instances.TITLE, CalendarContract.Instances.BEGIN, CalendarContract.Instances.ALL_DAY)
        val text = try {
            contentResolver.query(uri, proj, null, null, CalendarContract.Instances.BEGIN + " ASC")?.use { cur ->
                var found: String? = null
                while (found == null && cur.moveToNext()) {
                    val title = cur.getString(0)?.takeIf { it.isNotBlank() } ?: continue
                    found = if (cur.getInt(2) == 1) title else "${DateFormat.getTimeFormat(this).format(cur.getLong(1))}  $title"
                }
                found
            }
        } catch (_: SecurityException) {
            null
        } ?: return null
        return styledText(t, w.size ?: t.textSize * 0.85f, t.secondary).apply {
            this.text = text
            gravity = gravityOf(w.align)
            maxLines = 2
            setPadding(0, dp(6), 0, 0)
            setOnClickListener {
                safeStart(Intent(Intent.ACTION_VIEW).setData(CalendarContract.CONTENT_URI.buildUpon().appendPath("time").build()))
            }
        }
    }

    // -- actions ---------------------------------------------------------------

    private fun perform(action: String) {
        when {
            action == "drawer" -> openDrawer(false)
            action == "search" -> openDrawer(true)
            action == "notifications" -> expandStatusBar("expandNotificationsPanel")
            action == "quickSettings" -> expandStatusBar("expandSettingsPanel")
            action == "homeSettings" -> safeStart(Intent(Settings.ACTION_HOME_SETTINGS))
            action.startsWith("app:") -> apps.resolve(action.removePrefix("app:"), allApps)?.let { launch(it, root) }
        }
    }

    private fun launch(e: AppEntry, from: View) = guarded(e) { start(e, from) }

    /** Run [open] for [e], but show the pause screen first if the owner asked for one for this app. */
    private fun guarded(e: AppEntry, open: () -> Unit) {
        val c = config
        if (c != null && e.pkg in pausePkgs && !pause.isOpen) {
            pause.show(c.theme, label(e, c), c.pause.seconds, c.pause.message,
                open = { closeOverlays(); open() },
                dismiss = { closeOverlays() })
            updateBackCallback()
            return
        }
        open()
    }

    /** Long-press: the app's own shortcuts (e.g. "New incognito tab"), then App info. */
    private fun appMenu(e: AppEntry, anchor: View) {
        val shortcuts = apps.shortcuts(e)
        val menu = PopupMenu(this, anchor)
        shortcuts.forEachIndexed { i, s -> menu.menu.add(0, i, i, s.shortLabel ?: s.id) }
        menu.menu.add(1, MENU_APP_INFO, 100, R.string.app_info)
        menu.setOnMenuItemClickListener { item ->
            if (item.itemId == MENU_APP_INFO) {
                appInfo(e)
            } else {
                shortcuts.getOrNull(item.itemId)?.let { s ->
                    guarded(e) {
                        try {
                            val loc = IntArray(2).also { anchor.getLocationOnScreen(it) }
                            apps.startShortcut(s, Rect(loc[0], loc[1], loc[0] + anchor.width, loc[1] + anchor.height))
                        } catch (_: Exception) {
                            Toast.makeText(this, "Can't open that shortcut", Toast.LENGTH_SHORT).show()
                        }
                    }
                }
            }
            true
        }
        menu.show()
    }

    private fun start(e: AppEntry, from: View) {
        try {
            val loc = IntArray(2).also { from.getLocationOnScreen(it) }
            val bounds = Rect(loc[0], loc[1], loc[0] + from.width, loc[1] + from.height)
            val opts = ActivityOptions.makeScaleUpAnimation(from, 0, 0, from.width, from.height).toBundle()
            apps.launch(e, bounds, opts)
        } catch (_: Exception) {
            Toast.makeText(this, "Can't open ${e.label}", Toast.LENGTH_SHORT).show()
        }
    }

    private fun appInfo(e: AppEntry) {
        try {
            apps.openAppInfo(e)
        } catch (_: Exception) {
        }
    }

    private fun safeStart(i: Intent) {
        try {
            startActivity(i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        } catch (_: Exception) {
        }
    }

    @SuppressLint("WrongConstant", "PrivateApi", "DiscouragedPrivateApi")
    private fun expandStatusBar(method: String) {
        try {
            val sb = getSystemService("statusbar") ?: return
            sb.javaClass.getMethod(method).invoke(sb)
        } catch (_: Exception) {
        }
    }

    private fun openDrawer(focusSearch: Boolean) {
        drawer.open(focusSearch)
        updateBackCallback()
    }

    /** Back closes the top overlay: the pause screen, then the drawer. The home screen itself never goes back. */
    private fun onBack() {
        when {
            pause.isOpen -> pause.hide()
            drawer.isOpen -> drawer.close()
        }
        updateBackCallback()
    }

    private fun closeOverlays() {
        if (pause.isOpen) pause.hide()
        if (drawer.isOpen) drawer.close()
        updateBackCallback()
    }

    private fun updateBackCallback() {
        if (Build.VERSION.SDK_INT < 33) return
        val want = drawer.isOpen || pause.isOpen
        if (want && backCallback == null) {
            val cb = OnBackInvokedCallback { onBack() }
            onBackInvokedDispatcher.registerOnBackInvokedCallback(OnBackInvokedDispatcher.PRIORITY_DEFAULT, cb)
            backCallback = cb
        } else if (!want && backCallback != null) {
            (backCallback as? OnBackInvokedCallback)?.let { onBackInvokedDispatcher.unregisterOnBackInvokedCallback(it) }
            backCallback = null
        }
    }

    // -- window ----------------------------------------------------------------

    @Suppress("DEPRECATION")
    private fun drawEdgeToEdge() {
        if (Build.VERSION.SDK_INT >= 30) {
            window.setDecorFitsSystemWindows(false)
        } else {
            window.decorView.systemUiVisibility = View.SYSTEM_UI_FLAG_LAYOUT_STABLE or
                View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN or View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION
        }
    }

    @Suppress("DEPRECATION")
    private fun setBarIcons(lightBackground: Boolean) {
        if (Build.VERSION.SDK_INT >= 30) {
            val flags = WindowInsetsController.APPEARANCE_LIGHT_STATUS_BARS or WindowInsetsController.APPEARANCE_LIGHT_NAVIGATION_BARS
            window.insetsController?.setSystemBarsAppearance(if (lightBackground) flags else 0, flags)
        } else {
            val light = View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR or View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR
            val v = window.decorView.systemUiVisibility
            window.decorView.systemUiVisibility = if (lightBackground) v or light else v and light.inv()
        }
    }

    @Suppress("DEPRECATION")
    private fun systemInsets(wi: WindowInsets): IntArray {
        if (Build.VERSION.SDK_INT >= 30) {
            val bars = wi.getInsets(WindowInsets.Type.systemBars() or WindowInsets.Type.displayCutout())
            val ime = wi.getInsets(WindowInsets.Type.ime())
            return intArrayOf(bars.left, bars.top, bars.right, maxOf(bars.bottom, ime.bottom))
        }
        return intArrayOf(wi.systemWindowInsetLeft, wi.systemWindowInsetTop, wi.systemWindowInsetRight, wi.systemWindowInsetBottom)
    }
}
