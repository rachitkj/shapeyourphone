package io.github.rachitkj.shape.config

import org.json.JSONArray
import org.json.JSONObject

/**
 * The launcher's config, v1. Reference: docs/launcher-config.md.
 * Parsing is lenient (unknown keys and widget types are ignored, bad values
 * fall back to defaults) because the Python validator already rejected
 * anything malformed before it reached the phone.
 */
class ConfigException(message: String) : Exception(message)

enum class Align { START, CENTER, END }
enum class AppsStyle { LIST, GRID, ROW }
enum class IconStyle { COLOR, MONO, GRAYSCALE, NONE }

sealed class TextColor {
    object Foreground : TextColor()
    object Secondary : TextColor()
    object Accent : TextColor()
    data class Literal(val argb: Int) : TextColor()
}

data class Theme(
    /** null means: show the system wallpaper */
    val background: Int?,
    val dim: Float,
    val foreground: Int,
    val secondary: Int,
    val accent: Int,
    val font: String,
    val textSize: Float,
    val iconStyle: IconStyle,
    val iconSize: Int,
    val padding: Int,
)

sealed class Widget {
    data class Clock(val format: String?, val size: Float, val showDate: Boolean, val dateFormat: String, val align: Align) : Widget()
    data class Text(val text: String, val size: Float?, val align: Align, val color: TextColor) : Widget()
    data class Spacer(val height: Int, val flex: Float) : Widget()
    data class Apps(val apps: List<String>, val style: AppsStyle, val columns: Int, val align: Align, val labels: Boolean, val size: Float?) : Widget()
    data class Search(val hint: String?) : Widget()
    data class Calendar(val hours: Int, val align: Align, val size: Float?) : Widget()
}

data class Dock(val apps: List<String>, val labels: Boolean)

data class Drawer(
    val style: AppsStyle,
    val columns: Int,
    val showSearch: Boolean,
    val autoLaunch: Boolean,
    val searchOnly: Set<String>,
)

data class Gestures(val swipeUp: String, val swipeDown: String, val doubleTap: String, val longPress: String)

data class Config(
    val name: String,
    val theme: Theme,
    val home: List<Widget>,
    val dock: Dock,
    val drawer: Drawer,
    val labels: Map<String, String>,
    val gestures: Gestures,
    /** Hidden everywhere right now: drawer.hidden plus every active rule's `hide`. */
    val hidden: Set<String>,
    val activeRules: List<String>,
)

object ConfigParser {
    const val VERSION = 1
    val DEFAULT_DOCK = listOf("@dialer", "@sms", "@browser", "@camera")

    fun parseRoot(text: String): JSONObject {
        val root = try {
            JSONObject(text)
        } catch (e: Exception) {
            throw ConfigException("not valid JSON: ${e.message}")
        }
        val v = root.optInt("version", -1)
        if (v != VERSION) throw ConfigException("version must be $VERSION (got $v)")
        return root
    }

    /** Parse [text] with its rules evaluated at [day] (1=Mon..7=Sun) and [minute] of the day. */
    fun parse(text: String, day: Int, minute: Int): Config {
        val eff = Rules.effective(parseRoot(text), day, minute)
        return fromJson(eff.config, eff.hidden, eff.active)
    }

    fun fromJson(o: JSONObject, ruleHidden: List<String> = emptyList(), active: List<String> = emptyList()): Config {
        val t = o.optJSONObject("theme") ?: JSONObject()
        val bg = t.optString("background", "#0B0B0C")
        val theme = Theme(
            background = if (bg == "wallpaper") null else Colors.parse(bg, 0xFF0B0B0C.toInt()),
            dim = t.optDouble("dim", 0.25).toFloat().coerceIn(0f, 1f),
            foreground = Colors.parse(t.optString("foreground"), 0xFFF2F2F2.toInt()),
            secondary = Colors.parse(t.optString("secondary"), 0xFF8A8A8E.toInt()),
            accent = Colors.parse(t.optString("accent"), 0xFF7CC4FF.toInt()),
            font = t.optString("font", "sans"),
            textSize = t.optDouble("textSize", 18.0).toFloat().coerceIn(10f, 40f),
            iconStyle = enumOr(t.optString("iconStyle"), IconStyle.COLOR),
            iconSize = t.optInt("iconSize", 40).coerceIn(16, 96),
            padding = t.optInt("padding", 24).coerceIn(0, 64),
        )

        val home = o.optJSONArray("home")?.let { arr ->
            (0 until arr.length()).mapNotNull { i -> arr.optJSONObject(i)?.let(::widget) }
        } ?: listOf(
            Widget.Clock(null, 64f, true, "EEEE, d MMMM", Align.START),
            Widget.Spacer(0, 1f),
        )

        val d = o.optJSONObject("dock")
        val dock = Dock(
            apps = d?.optJSONArray("apps")?.strings() ?: DEFAULT_DOCK,
            labels = d?.optBoolean("labels", false) ?: false,
        )

        val dr = o.optJSONObject("drawer") ?: JSONObject()
        val drawer = Drawer(
            style = if (dr.optString("style") == "grid") AppsStyle.GRID else AppsStyle.LIST,
            columns = dr.optInt("columns", 4).coerceIn(2, 6),
            showSearch = dr.optBoolean("showSearch", true),
            autoLaunch = dr.optBoolean("autoLaunch", false),
            searchOnly = dr.optJSONArray("searchOnly")?.strings()?.toSet() ?: emptySet(),
        )
        val hidden = (dr.optJSONArray("hidden")?.strings() ?: emptyList()) + ruleHidden

        val labels = mutableMapOf<String, String>()
        o.optJSONObject("labels")?.let { l -> for (k in l.keys()) l.optString(k).takeIf { it.isNotEmpty() }?.let { labels[k] = it } }

        val g = o.optJSONObject("gestures") ?: JSONObject()
        val gestures = Gestures(
            swipeUp = g.optString("swipeUp", "drawer"),
            swipeDown = g.optString("swipeDown", "notifications"),
            doubleTap = g.optString("doubleTap", "none"),
            longPress = g.optString("longPress", "homeSettings"),
        )

        return Config(o.optString("name", ""), theme, home, dock, drawer, labels, gestures, hidden.toSet(), active)
    }

    private fun widget(w: JSONObject): Widget? {
        val align = enumOr(w.optString("align"), Align.START)
        val size = if (w.has("size")) w.optDouble("size", 0.0).toFloat().takeIf { it > 0 } else null
        return when (w.optString("type")) {
            "clock" -> Widget.Clock(
                format = w.optString("format").ifBlank { null },
                size = size ?: 64f,
                showDate = w.optBoolean("showDate", true),
                dateFormat = w.optString("dateFormat").ifBlank { "EEEE, d MMMM" },
                align = align,
            )
            "text" -> Widget.Text(w.optString("text"), size, align, textColor(w.optString("color")))
            "spacer" -> Widget.Spacer(w.optInt("height", 0).coerceIn(0, 400), w.optDouble("flex", 0.0).toFloat().coerceIn(0f, 10f))
            "apps" -> Widget.Apps(
                apps = w.optJSONArray("apps")?.strings() ?: emptyList(),
                style = enumOr(w.optString("style"), AppsStyle.LIST),
                columns = w.optInt("columns", 4).coerceIn(1, 8),
                align = align,
                labels = w.optBoolean("labels", true),
                size = size,
            )
            "search" -> Widget.Search(w.optString("hint").ifBlank { null })
            "calendar" -> Widget.Calendar(w.optInt("hours", 24).coerceIn(1, 168), align, size)
            else -> null // unknown widget types are skipped so older launchers survive newer configs
        }
    }

    private fun textColor(s: String): TextColor = when (s) {
        "", "foreground" -> TextColor.Foreground
        "secondary" -> TextColor.Secondary
        "accent" -> TextColor.Accent
        else -> Colors.tryParse(s)?.let { TextColor.Literal(it) } ?: TextColor.Foreground
    }

    private inline fun <reified E : Enum<E>> enumOr(s: String, fallback: E): E =
        enumValues<E>().firstOrNull { it.name.equals(s, ignoreCase = true) } ?: fallback

    private fun JSONArray.strings(): List<String> =
        (0 until length()).mapNotNull { i -> optString(i).takeIf { it.isNotEmpty() } }
}
