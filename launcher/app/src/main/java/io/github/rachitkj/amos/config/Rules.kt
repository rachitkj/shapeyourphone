package io.github.rachitkj.amos.config

import org.json.JSONArray
import org.json.JSONObject

/**
 * Time rules. Must match amos/launcher_config.py exactly — both run
 * tests/vectors/rules.json.
 *
 * A rule is active on its `days` (default: every day) between `from` and `to`
 * (default: all day). Windows that cross midnight belong to the day they start.
 * Active rules apply in order: `set` is deep-merged onto the config (objects
 * merge, everything else replaces) and `hide` adds packages hidden everywhere.
 */
object Rules {
    val DAYS = listOf("mon", "tue", "wed", "thu", "fri", "sat", "sun")
    private val TIME = Regex("^([01]\\d|2[0-3]):([0-5]\\d)$")

    class Effective(val config: JSONObject, val hidden: List<String>, val active: List<String>)

    fun minutes(hhmm: String?): Int? {
        val m = TIME.matchEntire(hhmm ?: return null) ?: return null
        return m.groupValues[1].toInt() * 60 + m.groupValues[2].toInt()
    }

    /** [day]: 1=Mon..7=Sun, [minute]: 0..1439 */
    fun isActive(rule: JSONObject, day: Int, minute: Int): Boolean {
        val arr = rule.optJSONArray("days")
        val days: Set<Int> = if (arr == null) (1..7).toSet() else
            (0 until arr.length()).mapNotNull { i -> DAYS.indexOf(arr.optString(i)).takeIf { it >= 0 }?.plus(1) }.toSet()
        val from = if (rule.has("from")) minutes(rule.optString("from")) else null
        val to = if (rule.has("to")) minutes(rule.optString("to")) else null
        if (from == null || to == null || from == to) return day in days
        if (from < to) return day in days && minute >= from && minute < to
        val prev = if (day == 1) 7 else day - 1
        return (minute >= from && day in days) || (minute < to && prev in days)
    }

    fun deepMerge(base: JSONObject, overlay: JSONObject): JSONObject {
        val out = JSONObject(base.toString())
        for (k in overlay.keys()) {
            val v = overlay.get(k)
            val cur = out.opt(k)
            if (v is JSONObject && cur is JSONObject) out.put(k, deepMerge(cur, v)) else out.put(k, copy(v))
        }
        return out
    }

    private fun copy(v: Any): Any = when (v) {
        is JSONObject -> JSONObject(v.toString())
        is JSONArray -> JSONArray(v.toString())
        else -> v
    }

    fun effective(root: JSONObject, day: Int, minute: Int): Effective {
        var merged = JSONObject(root.toString())
        merged.remove("rules")
        val hidden = mutableListOf<String>()
        val active = mutableListOf<String>()
        val rules = root.optJSONArray("rules") ?: JSONArray()
        for (i in 0 until rules.length()) {
            val r = rules.optJSONObject(i) ?: continue
            if (!isActive(r, day, minute)) continue
            active += r.optString("name").ifEmpty { "rule ${i + 1}" }
            r.optJSONObject("set")?.let { merged = deepMerge(merged, it) }
            r.optJSONArray("hide")?.let { arr ->
                for (j in 0 until arr.length()) {
                    val p = arr.optString(j)
                    if (p.isNotEmpty() && p !in hidden) hidden += p
                }
            }
        }
        return Effective(merged, hidden, active)
    }
}
