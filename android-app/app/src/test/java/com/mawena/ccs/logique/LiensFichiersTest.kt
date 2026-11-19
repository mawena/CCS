package com.mawena.ccs.logique

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class LiensFichiersTest {
    private val l = LiensFichiers("/home/c/ccs", setOf("ccs_app/web/files.js", "README.md", "a/b.kt"))

    @Test
    fun referenceSeule() {
        assertEquals(LiensFichiers.Ref("README.md", null), l.ref("README.md"))
        assertEquals(LiensFichiers.Ref("a/b.kt", 12), l.ref("a/b.kt:12"))
        assertEquals(LiensFichiers.Ref("a/b.kt", 12), l.ref("./a/b.kt:12:4"))
        assertEquals(LiensFichiers.Ref("ccs_app/web/files.js", null), l.ref("/home/c/ccs/ccs_app/web/files.js"))
        assertNull(l.ref("/ailleurs/README.md"))
        assertNull(l.ref("inconnu.md"))
        assertNull(l.ref("a/../README.md"))
        assertNull(l.ref("deux mots"))
    }

    @Test
    fun dansUnTexte() {
        val t = "Voir README.md et a/b.kt:3, pas x.md ni http://site/README.md."
        val r = l.trouver(t)
        assertEquals(listOf("README.md", "a/b.kt:3"), r.map { it.texte })
        assertEquals(t.indexOf("README.md"), r[0].index)
        assertEquals(3, r[1].ligne)
        assertEquals("/home/c/ccs/a/b.kt", l.absolu(r[1]))
        assertEquals(emptyList<LiensFichiers.Ref>(), LiensFichiers("/x", emptySet()).trouver(t))
    }
}
