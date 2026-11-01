package io.github.rachitkj.shape.config

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test
import java.io.File

class ConfigParserTest {
    private val configDir: File by lazy {
        File(System.getProperty("shape.vectors") ?: "../../tests/vectors/rules.json").parentFile.parentFile.parentFile.resolve("config")
    }

    @Test
    fun shippedConfigsParse() {
        val files = listOf(configDir.resolve("default.json")) + (configDir.resolve("examples").listFiles()?.sorted() ?: emptyList())
        assertTrue("found ${files.size} configs", files.size >= 3)
        for (f in files) {
            val c = ConfigParser.parse(f.readText(), 2, 12 * 60)
            assertTrue("${f.name} has home widgets", c.home.isNotEmpty())
        }
    }

    @Test
    fun defaultConfigValues() {
        val c = ConfigParser.parse(configDir.resolve("default.json").readText(), 1, 0)
        assertEquals(0xFF0B0B0C.toInt(), c.theme.background)
        assertEquals(IconStyle.COLOR, c.theme.iconStyle)
        assertEquals(listOf("@dialer", "@sms", "@browser", "@camera"), c.dock.apps)
        assertEquals("drawer", c.gestures.swipeUp)
        assertTrue(c.home.first() is Widget.Clock)
    }

    @Test
    fun wallpaperAndRules() {
        val text = configDir.resolve("examples/focus-workday.json").readText()
        val workday = ConfigParser.parse(text, 2, 10 * 60) // Tue 10:00
        assertNull(workday.theme.background)
        assertEquals(listOf("Work hours"), workday.activeRules)
        assertTrue("com.instagram.android" in workday.hidden)
        val evening = ConfigParser.parse(text, 2, 19 * 60) // Tue 19:00
        assertEquals(listOf("Evening"), evening.activeRules)
        assertTrue("com.instagram.android" !in evening.hidden)
        val apps = evening.home.filterIsInstance<Widget.Apps>().single()
        assertTrue("com.spotify.music" in apps.apps)
    }

    @Test
    fun pauseSection() {
        val c = ConfigParser.parse(configDir.resolve("examples/focus-workday.json").readText(), 2, 12 * 60)
        assertEquals(listOf("com.instagram.android", "com.zhiliaoapp.musically"), c.pause.apps)
        assertEquals(8, c.pause.seconds)
        assertEquals("Is this what you came for?", c.pause.message)
        val d = ConfigParser.parse("""{"version":1,"pause":{"apps":["a.b"],"seconds":999}}""", 1, 0)
        assertEquals(60, d.pause.seconds) // clamped
        assertEquals("Take a breath.", d.pause.message)
        assertEquals(emptyList<String>(), ConfigParser.parse("""{"version":1}""", 1, 0).pause.apps)
    }

    @Test
    fun lenientParsing() {
        val c = ConfigParser.parse(
            """{"version":1,"theme":{"background":"nope","iconStyle":"neon","textSize":500},
               "home":[{"type":"weather"},{"type":"text","text":"hi","color":"accent"}]}""",
            1, 0,
        )
        assertEquals(0xFF0B0B0C.toInt(), c.theme.background) // bad colour -> default
        assertEquals(IconStyle.COLOR, c.theme.iconStyle)
        assertEquals(40f, c.theme.textSize) // clamped
        assertEquals(1, c.home.size) // unknown widget skipped
        assertEquals(TextColor.Accent, (c.home[0] as Widget.Text).color)
    }

    @Test
    fun rejectsWrongVersionAndBadJson() {
        for (bad in listOf("""{"version":2}""", "not json", "[]")) {
            try {
                ConfigParser.parse(bad, 1, 0)
                fail("accepted $bad")
            } catch (_: ConfigException) {
            }
        }
    }

    @Test
    fun colors() {
        assertEquals(0xFFFFFFFF.toInt(), Colors.tryParse("#fff"))
        assertEquals(0xFF102030.toInt(), Colors.tryParse("#102030"))
        assertEquals(0x80102030.toInt(), Colors.tryParse("#80102030"))
        assertNull(Colors.tryParse("102030"))
        assertNull(Colors.tryParse("#12345"))
        assertNull(Colors.tryParse("#ggg"))
    }
}
