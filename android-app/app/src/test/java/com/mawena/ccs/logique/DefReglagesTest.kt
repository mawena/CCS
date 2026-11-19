package com.mawena.ccs.logique

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class DefReglagesTest {
    private val r = Json.parseToJsonElement(
        """{"chat":{"auto_clear":true,"rights":"manual","idle_suspend_min":30},"sessions":{"idle_hours":0.5},
           "alerts":{"quiet":{"start":"22:00"}},"phone":{"topic":""}}""",
    ).jsonObject

    @Test
    fun lireEtEcrireUnChemin() {
        assertTrue(DefReglages.booleen(DefReglages.lire(r, "chat.auto_clear")))
        assertFalse(DefReglages.booleen(DefReglages.lire(r, "chat.absent")))
        assertNull(DefReglages.lire(r, "x.y.z"))
        assertEquals("22:00", DefReglages.texte(DefReglages.lire(r, "alerts.quiet.start")))
        assertEquals("30", DefReglages.texte(DefReglages.lire(r, "chat.idle_suspend_min")))
        assertEquals("0.5", DefReglages.texte(DefReglages.lire(r, "sessions.idle_hours")))
        val e = DefReglages.ecrire(r, "alerts.quiet.end", JsonPrimitive("07:00"))
        assertEquals("07:00", DefReglages.texte(DefReglages.lire(e, "alerts.quiet.end")))
        assertEquals("22:00", DefReglages.texte(DefReglages.lire(e, "alerts.quiet.start")))
        val n = DefReglages.ecrire(JsonObject(emptyMap()), "a.b", JsonPrimitive(false))
        assertEquals("""{"a":{"b":false}}""", n.toString())
    }

    @Test
    fun nombresEtHeures() {
        val g = DefReglages.Genre.Nombre(1.0, 100.0)
        assertEquals(42L, DefReglages.nombre(" 42 ", g).first)
        assertEquals(2.5, DefReglages.nombre("2,5", g).first)
        assertEquals("Entre un nombre.", DefReglages.nombre("abc", g).second)
        assertEquals("Entre 1 et 100.", DefReglages.nombre("0", g).second)
        assertEquals("Entre un nombre entier.", DefReglages.nombre("2.5", DefReglages.Genre.Nombre(1.0, 10.0, true)).second)
        assertEquals("07:05", DefReglages.heure("7:05"))
        assertNull(DefReglages.heure("24:00"))
        assertNull(DefReglages.heure("7h"))
    }

    @Test
    fun tousLesReglagesDuWeb() {
        val chemins = (DefReglages.GROUPES + DefReglages.TELEPHONE).flatMap { g -> g.reglages.map { it.chemin } }
        assertEquals(chemins.size, chemins.toSet().size)
        assertTrue("chat.auto_clear" in chemins)
        assertEquals(44, chemins.size)
    }
}
