package io.github.rachitkj.amos

import android.content.Context
import android.graphics.drawable.GradientDrawable
import android.text.Editable
import android.text.InputType
import android.text.TextWatcher
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.view.inputmethod.EditorInfo
import android.view.inputmethod.InputMethodManager
import android.widget.AbsListView
import android.widget.BaseAdapter
import android.widget.EditText
import android.widget.FrameLayout
import android.widget.GridView
import android.widget.LinearLayout
import android.widget.ListView
import android.widget.TextView
import io.github.rachitkj.amos.config.Align
import io.github.rachitkj.amos.config.AppsStyle
import io.github.rachitkj.amos.config.Colors
import io.github.rachitkj.amos.config.Config

/** Full-screen app list with search. Hidden apps never appear; search-only apps appear only when searched. */
class DrawerView(
    context: Context,
    private val apps: AppRepository,
    private val onLaunch: (AppEntry, View) -> Unit,
    private val onInfo: (AppEntry) -> Unit,
) : FrameLayout(context) {

    private val column = LinearLayout(context).apply { orientation = LinearLayout.VERTICAL }
    private val search = EditText(context)
    private val empty = TextView(context)
    private var list: AbsListView? = null
    private val adapter = Adapter()
    private var cfg: Config? = null
    private var all: List<AppEntry> = emptyList()
    private var shown: List<AppEntry> = emptyList()
    private var launchedForQuery = ""

    val isOpen: Boolean get() = visibility == View.VISIBLE

    init {
        visibility = View.GONE
        isClickable = true // swallow touches so the home screen underneath doesn't get them
        addView(column, LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.MATCH_PARENT))
        search.apply {
            setSingleLine()
            imeOptions = EditorInfo.IME_ACTION_GO
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS
            hint = context.getString(R.string.search_hint)
            setPadding(context.dp(18), context.dp(12), context.dp(18), context.dp(12))
            addTextChangedListener(object : TextWatcher {
                override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
                override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {}
                override fun afterTextChanged(s: Editable?) = filter()
            })
            setOnEditorActionListener { v, actionId, _ ->
                if (actionId == EditorInfo.IME_ACTION_GO) {
                    shown.firstOrNull()?.let { onLaunch(it, v) }
                    true
                } else false
            }
        }
        column.addView(search, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT).apply {
            bottomMargin = context.dp(8)
        })
        empty.apply {
            text = context.getString(R.string.no_results)
            gravity = Gravity.CENTER
            visibility = View.GONE
        }
        column.addView(empty, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, context.dp(64)))
    }

    fun bind(config: Config, entries: List<AppEntry>) {
        cfg = config
        all = entries
        val t = config.theme
        setBackgroundColor(t.background ?: 0xFA0A0A0C.toInt())
        search.visibility = if (config.drawer.showSearch) View.VISIBLE else View.GONE
        search.setTextColor(t.foreground)
        search.setHintTextColor(t.secondary)
        search.typeface = fontFor(t.font)
        search.background = GradientDrawable().apply {
            cornerRadius = context.dp(24).toFloat()
            setColor(Colors.withAlpha(t.foreground, 0.08f))
        }
        empty.setTextColor(t.secondary)

        // Rebuilt on every bind so recycled rows never keep an old theme's sizes.
        val grid = config.drawer.style == AppsStyle.GRID
        list?.let { column.removeView(it) }
        run {
            val v: AbsListView = if (grid) GridView(context) else ListView(context).apply {
                divider = null
                dividerHeight = 0
            }
            v.adapter = adapter
            v.isVerticalScrollBarEnabled = false
            v.selector = android.graphics.drawable.ColorDrawable(0)
            v.setOnItemClickListener { _, view, pos, _ -> shown.getOrNull(pos)?.let { onLaunch(it, view) } }
            v.setOnItemLongClickListener { _, _, pos, _ ->
                shown.getOrNull(pos)?.let { onInfo(it) }
                true
            }
            column.addView(v, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, 0, 1f))
            list = v
        }
        (list as? GridView)?.numColumns = config.drawer.columns
        filter()
    }

    private fun label(e: AppEntry): String = cfg?.labels?.get(e.pkg) ?: e.label

    private fun filter() {
        val c = cfg ?: return
        val q = search.text.toString().trim().lowercase()
        val visible = all.filter { it.pkg !in c.hidden }
        shown = if (q.isEmpty()) {
            visible.filter { it.pkg !in c.drawer.searchOnly }
        } else {
            visible.filter { label(it).lowercase().contains(q) || it.pkg.lowercase().contains(q) }
                .sortedBy { if (label(it).lowercase().startsWith(q)) 0 else 1 }
        }
        adapter.notifyDataSetChanged()
        empty.visibility = if (shown.isEmpty() && q.isNotEmpty()) View.VISIBLE else View.GONE
        if (c.drawer.autoLaunch && q.isNotEmpty() && shown.size == 1 && launchedForQuery != q) {
            launchedForQuery = q
            onLaunch(shown[0], search)
        }
    }

    fun open(focusSearch: Boolean) {
        if (!isOpen) {
            visibility = View.VISIBLE
            alpha = 0f
            translationY = context.dp(32).toFloat()
            animate().alpha(1f).translationY(0f).setDuration(160).start()
        }
        list?.setSelection(0)
        if (focusSearch && search.visibility == View.VISIBLE) {
            search.requestFocus()
            search.postDelayed({
                (context.getSystemService(Context.INPUT_METHOD_SERVICE) as InputMethodManager)
                    .showSoftInput(search, InputMethodManager.SHOW_IMPLICIT)
            }, 120)
        }
    }

    fun close() {
        (context.getSystemService(Context.INPUT_METHOD_SERVICE) as InputMethodManager)
            .hideSoftInputFromWindow(windowToken, 0)
        search.clearFocus()
        if (search.text.isNotEmpty()) search.setText("")
        launchedForQuery = ""
        animate().cancel()
        visibility = View.GONE
    }

    fun setInsets(l: Int, t: Int, r: Int, b: Int) {
        val side = context.dp(16)
        column.setPadding(l + side, t + context.dp(12), r + side, b)
    }

    private inner class Adapter : BaseAdapter() {
        override fun getCount() = shown.size
        override fun getItem(position: Int): Any = shown[position]
        override fun getItemId(position: Int) = position.toLong()

        override fun getView(position: Int, convertView: View?, parent: ViewGroup?): View {
            val c = cfg ?: return View(context)
            val grid = c.drawer.style == AppsStyle.GRID
            val holder = convertView?.tagHolder()?.takeIf { it.cell == grid }
                ?: (if (grid) context.appCell(c.theme, true) else context.appRow(c.theme, c.theme.textSize, Align.START)).also {
                    it.root.tag = it
                    // AdapterView handles clicks; the row itself must not swallow them.
                    it.root.isClickable = false
                    it.root.isFocusable = false
                    it.root.background = null
                }
            val e = shown[position]
            holder.label.text = label(e)
            val size = context.dp(if (grid) c.theme.iconSize else c.theme.iconSize * 0.8f)
            holder.icon.setImageBitmap(apps.icon(e, c.theme.iconStyle, c.theme.foreground, size))
            return holder.root
        }
    }
}
