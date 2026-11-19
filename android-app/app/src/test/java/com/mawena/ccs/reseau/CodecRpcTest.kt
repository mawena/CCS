package com.mawena.ccs.reseau

import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.long
import kotlinx.serialization.json.put
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class CodecRpcTest {
    @Test
    fun requeteAuFormatDuServeur() {
        val texte = CodecRpc.requete(7, "files.list", buildJsonObject { put("path", "~/Work") })
        val obj = CodecRpc.json.parseToJsonElement(texte).jsonObject
        assertEquals(7L, obj["id"]!!.jsonPrimitive.long)
        assertEquals("files.list", obj["method"]!!.jsonPrimitive.content)
        assertEquals("~/Work", obj["params"]!!.jsonObject["path"]!!.jsonPrimitive.content)
    }

    @Test
    fun requeteSansParametresEnvoieUnObjetVide() {
        val obj = CodecRpc.json.parseToJsonElement(CodecRpc.requete(1, "accounts.cards")).jsonObject
        assertEquals(JsonObject(emptyMap()), obj["params"])
    }

    @Test
    fun resultat() {
        val m = CodecRpc.decoder("""{"id": 3, "result": {"n": 2}}""") as MessageRpc.Resultat
        assertEquals(3L, m.id)
        assertEquals(2, m.resultat.jsonObject["n"]!!.jsonPrimitive.int)
    }

    @Test
    fun resultatNulDevientObjetVide() {
        val m = CodecRpc.decoder("""{"id": 4, "result": null}""") as MessageRpc.Resultat
        assertEquals(JsonObject(emptyMap()), m.resultat)
    }

    @Test
    fun erreur() {
        val m = CodecRpc.decoder("""{"id": 5, "error": {"code": "refuse", "message": "Requête refusée."}}""")
        assertEquals(MessageRpc.Echec(5, "refuse", "Requête refusée."), m)
    }

    @Test
    fun erreurIncompleteGardeDesValeursParDefaut() {
        val m = CodecRpc.decoder("""{"id": 6, "error": "boum"}""") as MessageRpc.Echec
        assertEquals("erreur", m.code)
        assertTrue(m.message.isNotBlank())
    }

    @Test
    fun evenement() {
        val m = CodecRpc.decoder("""{"event": "chat.tags", "data": {"id": "s1"}}""") as MessageRpc.Evenement
        assertEquals("chat.tags", m.nom)
        assertEquals("s1", m.donnees["id"]!!.jsonPrimitive.content)
    }

    @Test
    fun evenementSansDonnees() {
        val m = CodecRpc.decoder("""{"event": "notice"}""") as MessageRpc.Evenement
        assertEquals(JsonObject(emptyMap()), m.donnees)
    }

    @Test
    fun tramesIncomprisesIgnorees() {
        assertNull(CodecRpc.decoder("pas du json"))
        assertNull(CodecRpc.decoder("[1, 2]"))
        assertNull(CodecRpc.decoder("""{"result": {}}"""))
        assertNull(CodecRpc.decoder("""{"id": "x", "result": {}}"""))
    }

    @Test
    fun cartesDeComptes() {
        val texte = """{"cards": [{"name": "perso", "plan": "Max", "active": true, "color": "#62a0ea",
            "main": [{"kind": "five_hour", "label": "5 h", "percent": 42.5, "reset": "dans 2 h"}],
            "others": [], "status": {"text": "OK", "kind": "success"}, "error_raw": null,
            "details": ["Relevé à 10:00"], "fetched_at": 1795091812.06, "has_data": true,
            "inconnu": 1}], "best": "perso", "auto_switch": true, "updated_at": 1795091812.5}"""
        val c = CodecRpc.json.decodeFromString(Cartes.serializer(), texte)
        assertEquals(1, c.cards.size)
        assertEquals("perso", c.cards[0].name)
        assertEquals(42.5, c.cards[0].main[0].percent, 0.0)
        assertEquals("success", c.cards[0].status?.kind)
        assertTrue(c.cards[0].donnees)
    }

    @Test
    fun reponsesDeConnexion() {
        assertEquals("tok", ApiHttp.lireReponse(200, """{"status": "ok", "user": "c", "token": "tok"}""").token)
        val inscription = ApiHttp.lireReponse(200, """{"status": "enroll", "pending": "p", "secret": "S", "qr_svg": "<svg/>"}""")
        assertEquals("p", inscription.pending)
        assertEquals(30.0, ApiHttp.lireReponse(200, """{"status": "blocked", "retry_after": 30}""").retryAfter!!, 0.0)
        assertEquals("refused", ApiHttp.lireReponse(401, "Identifiant incorrect").status)
        assertEquals("error", ApiHttp.lireReponse(503, "").status)
        assertEquals("error", ApiHttp.lireReponse(200, "<html>").status)
    }
}
