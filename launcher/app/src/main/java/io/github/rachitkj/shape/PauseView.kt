package io.github.rachitkj.shape

import android.content.Context
import android.graphics.drawable.GradientDrawable
import android.view.Gravity
import android.view.View
import android.widget.FrameLayout
import android.widget.LinearLayout
import io.github.rachitkj.shape.config.Colors
import io.github.rachitkj.shape.config.Theme

/**
 * "Still want this?" — shown before opening apps listed in config.pause.
 * After the countdown the owner has to tap Open; it never launches by itself.
 */
class PauseView(context: Context) : FrameLayout(context) {
    private val column = LinearLayout(context).apply {
        orientation = LinearLayout.VERTICAL
        gravity = Gravity.CENTER
    }
    private var remaining = 0
    private var onOpen: (() -> Unit)? = null
    private var onDismiss: (() -> Unit)? = null
    private val tick = object : Runnable {
        override fun run() {
            remaining -= 1
            update()
            if (remaining > 0) postDelayed(this, 1000)
        }
    }
    private var theme: Theme? = null
    private var appLabel = ""
    private lateinit var count: android.widget.TextView
    private lateinit var open: android.widget.TextView

    val isOpen: Boolean get() = visibility == View.VISIBLE

    init {
        visibility = View.GONE
        isClickable = true
        addView(column, LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.MATCH_PARENT))
    }

    fun show(t: Theme, label: String, seconds: Int, message: String, open: () -> Unit, dismiss: () -> Unit) {
        theme = t
        appLabel = label
        onOpen = open
        onDismiss = dismiss
        remaining = seconds
        setBackgroundColor(t.background ?: 0xFA0A0A0C.toInt())
        column.removeAllViews()
        val pad = context.dp(32)
        column.setPadding(pad, pad, pad, pad)
        column.addView(context.styledText(t, 30f).apply {
            text = message
            gravity = Gravity.CENTER
            typeface = fontFor(if (t.font == "sans") "light" else t.font)
        }, wrap())
        column.addView(context.styledText(t, 15f, t.secondary).apply {
            text = context.getString(R.string.pause_opening, label)
            gravity = Gravity.CENTER
            setPadding(0, context.dp(12), 0, context.dp(36))
        }, wrap())
        count = context.styledText(t, 48f, t.secondary).apply {
            gravity = Gravity.CENTER
            typeface = fontFor("thin")
        }
        column.addView(count, wrap())
        this.open = context.styledText(t, 17f).apply {
            gravity = Gravity.CENTER
            setPadding(context.dp(28), context.dp(14), context.dp(28), context.dp(14))
            background = GradientDrawable().apply {
                cornerRadius = context.dp(28).toFloat()
                setColor(Colors.withAlpha(t.foreground, 0.12f))
            }
            setOnClickListener { if (remaining <= 0) onOpen?.invoke() }
        }
        column.addView(this.open, LinearLayout.LayoutParams(LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT).apply {
            topMargin = context.dp(24)
        })
        column.addView(context.styledText(t, 15f, t.secondary).apply {
            text = context.getString(R.string.pause_not_now)
            gravity = Gravity.CENTER
            setPadding(context.dp(24), context.dp(20), context.dp(24), context.dp(12))
            setOnClickListener { onDismiss?.invoke() }
        }, LinearLayout.LayoutParams(LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT))
        update()
        removeCallbacks(tick)
        postDelayed(tick, 1000)
        visibility = View.VISIBLE
        alpha = 0f
        animate().alpha(1f).setDuration(200).start()
    }

    private fun update() {
        val ready = remaining <= 0
        count.text = if (ready) "" else remaining.toString()
        count.visibility = if (ready) View.INVISIBLE else View.VISIBLE
        open.text = context.getString(R.string.pause_open, appLabel)
        open.alpha = if (ready) 1f else 0.35f
        open.isEnabled = ready
    }

    fun hide() {
        removeCallbacks(tick)
        animate().cancel()
        visibility = View.GONE
        onOpen = null
        onDismiss = null
    }

    fun setInsets(l: Int, t: Int, r: Int, b: Int) {
        setPadding(l, t, r, b)
    }

    private fun wrap() = LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT)
}
