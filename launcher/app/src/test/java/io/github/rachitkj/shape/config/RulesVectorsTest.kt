package io.github.rachitkj.shape.config

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Test
import java.io.File

/** Runs tests/vectors/rules.json — the same vectors the Python toolkit's tests use. */
class RulesVectorsTest {
    private val vectors: JSONObject by lazy {
        val path = System.getProperty("shape.vectors") ?: "../../tests/vectors/rules.json"
        JSONObject(File(path).readText())
    }

    @Test
    fun activeMatchesPython() {
        val arr = vectors.getJSONArray("active")
        for (i in 0 until arr.length()) {
            val v = arr.getJSONObject(i)
            val minute = Rules.minutes(v.getString("time"))!!
            val got = Rules.isActive(v.getJSONObject("rule"), v.getInt("day"), minute)
            assertEquals("vector $i: $v", v.getBoolean("active"), got)
        }
    }

    @Test
    fun mergeMatchesPython() {
        val arr = vectors.getJSONArray("merge")
        for (i in 0 until arr.length()) {
            val v = arr.getJSONObject(i)
            val name = v.getString("name")
            val eff = Rules.effective(v.getJSONObject("config"), v.getInt("day"), Rules.minutes(v.getString("time"))!!)
            val exp = v.getJSONObject("expect")
            assertEquals(name, exp.getJSONArray("active").toStrings(), eff.active)
            assertEquals(name, exp.getJSONArray("hidden").toStrings(), eff.hidden)
            val theme = exp.getJSONObject("theme")
            for (k in theme.keys()) assertEquals("$name theme.$k", theme.getString(k), eff.config.getJSONObject("theme").getString(k))
            assertEquals(name, exp.getJSONArray("dock_apps").toStrings(), eff.config.getJSONObject("dock").getJSONArray("apps").toStrings())
            assertEquals(name, false, eff.config.has("rules"))
        }
    }

    private fun org.json.JSONArray.toStrings() = (0 until length()).map { getString(it) }
}
