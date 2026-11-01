package io.github.rachitkj.shape

import android.content.Context
import android.graphics.Typeface
import android.text.TextUtils
import android.util.TypedValue
import android.view.Gravity
import android.view.View
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.TextView
import io.github.rachitkj.shape.config.Align
import io.github.rachitkj.shape.config.IconStyle
import io.github.rachitkj.shape.config.TextColor
import io.github.rachitkj.shape.config.Theme
import kotlin.math.roundToInt

fun Context.dp(v: Number): Int = (v.toFloat() * resources.displayMetrics.density).roundToInt()

fun fontFor(font: String): Typeface = when (font) {
    "light" -> Typeface.create("sans-serif-light", Typeface.NORMAL)
    "thin" -> Typeface.create("sans-serif-thin", Typeface.NORMAL)
    "medium" -> Typeface.create("sans-serif-medium", Typeface.NORMAL)
    "condensed" -> Typeface.create("sans-serif-condensed", Typeface.NORMAL)
    "serif" -> Typeface.SERIF
    "mono" -> Typeface.MONOSPACE
    else -> Typeface.SANS_SERIF
}

fun gravityOf(a: Align): Int = when (a) {
    Align.START -> Gravity.START
    Align.CENTER -> Gravity.CENTER_HORIZONTAL
    Align.END -> Gravity.END
}

fun Theme.color(c: TextColor): Int = when (c) {
    TextColor.Foreground -> foreground
    TextColor.Secondary -> secondary
    TextColor.Accent -> accent
    is TextColor.Literal -> c.argb
}

fun Context.styledText(theme: Theme, sizeSp: Float, color: Int = theme.foreground): TextView =
    TextView(this).apply {
        setTextColor(color)
        setTextSize(TypedValue.COMPLEX_UNIT_SP, sizeSp)
        typeface = fontFor(theme.font)
        includeFontPadding = true
    }

/** Holds the views of one app row/cell so ListView/GridView can recycle them. */
class AppViewHolder(val root: LinearLayout, val icon: ImageView, val label: TextView, val cell: Boolean)

/** A horizontal row: [icon] label — used by list-style app widgets and the drawer list. */
fun Context.appRow(theme: Theme, textSize: Float, align: Align): AppViewHolder {
    val row = LinearLayout(this).apply {
        orientation = LinearLayout.HORIZONTAL
        gravity = Gravity.CENTER_VERTICAL or gravityOf(align)
        setPadding(0, dp(7), 0, dp(7))
        isClickable = true
        isFocusable = true
        background = selectableBackground()
    }
    val icon = ImageView(this)
    val showIcon = theme.iconStyle != IconStyle.NONE
    if (showIcon) {
        val s = dp(theme.iconSize * 0.8f)
        row.addView(icon, LinearLayout.LayoutParams(s, s).apply { marginEnd = dp(14) })
    }
    val label = styledText(theme, textSize).apply {
        maxLines = 1
        ellipsize = TextUtils.TruncateAt.END
    }
    row.addView(label, LinearLayout.LayoutParams(LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT))
    return AppViewHolder(row, icon, label, cell = false)
}

/** A vertical cell: icon over an optional label — used by grids, rows and the dock. */
fun Context.appCell(theme: Theme, showLabel: Boolean): AppViewHolder {
    val cell = LinearLayout(this).apply {
        orientation = LinearLayout.VERTICAL
        gravity = Gravity.CENTER_HORIZONTAL
        setPadding(dp(4), dp(8), dp(4), dp(8))
        isClickable = true
        isFocusable = true
        background = selectableBackground()
    }
    val icon = ImageView(this)
    val noIcons = theme.iconStyle == IconStyle.NONE
    if (!noIcons) {
        val s = dp(theme.iconSize)
        cell.addView(icon, LinearLayout.LayoutParams(s, s))
    }
    val label = styledText(theme, if (noIcons) theme.textSize * 0.85f else 12f).apply {
        maxLines = 1
        ellipsize = TextUtils.TruncateAt.END
        gravity = Gravity.CENTER_HORIZONTAL
        setPadding(0, dp(4), 0, 0)
    }
    // With icons off, the label is the only thing to tap, so it's always shown.
    if (showLabel || noIcons) {
        cell.addView(label, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT))
    }
    return AppViewHolder(cell, icon, label, cell = true)
}

private fun Context.selectableBackground() = obtainStyledAttributes(intArrayOf(android.R.attr.selectableItemBackground)).let {
    val d = it.getDrawable(0)
    it.recycle()
    d
}

fun View.tagHolder(): AppViewHolder? = tag as? AppViewHolder
