package com.mawena.ccs.logique

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test

class JarvisTest {
    private val fp = "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789-_abcde"

    // ── adresse d'appairage ──

    @Test
    fun adresseValide() {
        assertEquals(
            CibleAppairage("482913", fp, "a1b2", 7341),
            Jarvis.lireAdresse("jarvis://pair?v=1&id=a1b2&h=192.168.1.20,10.0.0.5&p=7341&fp=$fp&c=482913"),
        )
    }

    @Test
    fun adresseCollee() {
        val c = Jarvis.lireAdresse("\n  « jarvis://pair?v=1&id=x&h=&p=7341&fp=$fp&c=000123 »\nsuite")
        assertEquals("000123", c.code)
        assertEquals(fp, c.empreinte)
    }

    @Test
    fun adressesRefusees() {
        listOf(
            "https://jarvis/pair?v=1",
            "jarvis://pair?v=2&fp=$fp&c=123456",
            "jarvis://pair?v=1&fp=court&c=123456",
            "jarvis://pair?v=1&fp=$fp&c=12345",
            "jarvis://pair?v=1&fp=$fp&c=12345a",
            "jarvis://pair?v=1&v=1&fp=$fp&c=123456",
            "jarvis://pair?v=1&fp=$fp&c=123456&rien",
        ).forEach {
            try {
                Jarvis.lireAdresse(it)
                fail(it)
            } catch (e: ErreurJarvis) {
            }
        }
    }

    @Test
    fun empreinteEtCode() {
        assertTrue(Jarvis.empreinteValide(fp))
        assertFalse(Jarvis.empreinteValide(fp + "a"))
        assertFalse(Jarvis.empreinteValide(fp.dropLast(1) + "="))
        assertFalse(Jarvis.empreinteValide(fp.dropLast(1) + "é"))
        assertTrue(Jarvis.codeValide("012345"))
        assertFalse(Jarvis.codeValide("12345"))
        assertFalse(Jarvis.codeValide("١٢٣٤٥٦"))
    }

    // ── messages ──

    @Test
    fun messagesDeLOreille() {
        val a = AppairageJarvis("e1", "t", fp, "Jarvis", "b")
        assertEquals("""{"type":"hello","version":1,"ear_id":"e1","token":"t"}""", Jarvis.hello(a))
        assertEquals("""{"type":"wake","utterance":7,"score":2.0,"level_db":0,"muted":false}""", Jarvis.wake(7))
        assertEquals("""{"type":"listen_start","utterance":8}""", Jarvis.listenStart(8))
        assertEquals(
            """{"type":"listen_end","utterance":4000000000,"muted":false,"no_speech":true,"cut":null}""",
            Jarvis.listenEnd(4_000_000_000L, sansParole = true),
        )
        val p = Json.parseToJsonElement(Jarvis.pair("123456", "n".repeat(80))).jsonObject
        assertEquals("pair", p["type"]!!.jsonPrimitive.content)
        assertEquals("android", p["platform"]!!.jsonPrimitive.content)
        assertEquals("123456", p["code"]!!.jsonPrimitive.content)
        assertEquals(60, p["name"]!!.jsonPrimitive.content.length)
        assertEquals("1", p["version"]!!.jsonPrimitive.content)
    }

    @Test
    fun messagesDuCerveau() {
        assertEquals(
            MessageCerveau.Bienvenue("Maison"),
            Jarvis.lire("""{"type":"welcome","version":1,"brain_id":"b","brain_name":"Maison","status":{}}"""),
        )
        assertEquals(
            MessageCerveau.Appaire("e", "t", "b", "J"),
            Jarvis.lire("""{"type":"paired","ear_id":"e","token":"t","brain_id":"b","brain_name":"J"}"""),
        )
        assertEquals(MessageCerveau.Refus("wrong_code", 2), Jarvis.lire("""{"type":"rejected","reason":{"kind":"wrong_code","attempts_left":2}}"""))
        assertEquals(MessageCerveau.Refus("bad_token", null), Jarvis.lire("""{"type":"rejected","reason":{"kind":"bad_token"}}"""))
        assertEquals(MessageCerveau.Elu(3), Jarvis.lire("""{"type":"elected","utterance":3}"""))
        assertEquals(MessageCerveau.Stop(4_000_000_000L), Jarvis.lire("""{"type":"stop","utterance":4000000000}"""))
        assertEquals(MessageCerveau.Relais("Tunnel fermé."), Jarvis.lire("""{"type":"relay_error","message":"Tunnel fermé."}"""))
        assertEquals(
            MessageCerveau.Entendu("quelle heure", "Midi.", VoixJarvis("AQD+/wCA", 22050), true),
            Jarvis.lire(
                """{"type":"response","utterance":3,"response":{"type":"heard","text":"quelle heure","speech":"Midi.",""" +
                    """"ear_action":"await_reply","audio":{"pcm":"AQD+/wCA","sample_rate":22050}}}""",
            ),
        )
        assertEquals(
            MessageCerveau.Entendu("a", "b", null, false),
            Jarvis.lire("""{"type":"response","utterance":3,"response":{"type":"heard","text":"a","speech":"b","ear_action":null}}"""),
        )
        assertEquals(MessageCerveau.Reponse("Oui."), Jarvis.lire("""{"type":"response","utterance":null,"response":{"type":"reply","speech":"Oui."}}"""))
        assertEquals(MessageCerveau.Erreur("Panne."), Jarvis.lire("""{"type":"response","response":{"type":"error","message":"Panne."}}"""))
        assertEquals(MessageCerveau.Autre, Jarvis.lire("""{"type":"offline_phrase","id":"x","audio":{}}"""))
        assertEquals(MessageCerveau.Autre, Jarvis.lire("pas du json"))
    }

    @Test
    fun textesDErreur() {
        assertEquals("Code d'appairage faux. Essais restants : 1.", Jarvis.texteRefus("wrong_code", 1))
        assertEquals("Jarvis a refusé la connexion.", Jarvis.texteRefus("inconnu", null))
        assertEquals(
            "Jarvis est injoignable : laptop-maison hors ligne.",
            Jarvis.texteFermeture(4011, "laptop-maison hors ligne.", "x"),
        )
        assertEquals("Jarvis est injoignable.", Jarvis.texteFermeture(4011, null, ""))
        assertEquals("Pont CCS injoignable.", Jarvis.texteFermeture(1011, null, ""))
        assertEquals("Connexion au relais de Jarvis perdue.", Jarvis.texteFermeture(1006, null, " "))
    }

    // ── son ──

    @Test
    fun trameMicro() {
        val t = Jarvis.trameMicro(0x01020304L, shortArrayOf(1, -2, Short.MIN_VALUE))
        assertArrayEquals(byteArrayOf(0x01, 0x04, 0x03, 0x02, 0x01, 0x01, 0x00, 0xFE.toByte(), 0xFF.toByte(), 0x00, 0x80.toByte()), t)
        // numéro de phrase au-delà de 2^31 (u32)
        val grand = Jarvis.trameMicro(0xFFFFFFFEL, shortArrayOf())
        assertArrayEquals(byteArrayOf(0x01, 0xFE.toByte(), 0xFF.toByte(), 0xFF.toByte(), 0xFF.toByte()), grand)
    }

    @Test
    fun decodagePcm() {
        assertArrayEquals(shortArrayOf(1, -2, Short.MIN_VALUE), Jarvis.decoderPcm("AQD+/wCA"))
        assertEquals(0, Jarvis.decoderPcm("pas du base64 !").size)
    }

    @Test
    fun reechantillonnage() {
        val r = Reechantillonneur(48_000)
        var total = 0
        repeat(10) {
            val s = r.pousser(FloatArray(480) { 0.5f })
            total += s.size
            assertTrue(s.all { it == 16384.toShort() })
        }
        assertEquals(1600, total)
        assertArrayEquals(shortArrayOf(Short.MIN_VALUE, Short.MAX_VALUE, Short.MAX_VALUE), Reechantillonneur(16_000).pousser(floatArrayOf(-1f, 1f, 2f)))
        val n = Reechantillonneur(44_100).pousser(FloatArray(44_100)).size
        assertTrue("$n", n in 15_999..16_000)
        // taille lue plus courte que le tableau (lecture partielle du micro)
        assertEquals(2, Reechantillonneur(48_000).pousser(FloatArray(100), 6).size)
    }

    // ── phrase ──

    @Test
    fun phraseAttendLeLienPuisDecoupe() {
        val p = PhraseJarvis(9, auto = false, maintenant = 0)
        assertFalse(p.ajouter(ShortArray(5_000) { 1 }, fort = true, maintenant = 10))
        assertTrue(p.trames(toutes = true).isEmpty())              // lien pas prêt : tout reste en attente
        p.prete = true
        assertEquals(listOf(3_205, 3_205, 3_205), p.trames(toutes = false).map { it.size })
        assertEquals(200, p.enAttente)
        assertEquals(listOf(405), p.trames(toutes = true).map { it.size })
        assertEquals(0, p.enAttente)
        assertFalse(p.sansParole)
    }

    @Test
    fun trameDeRattrapageAuPlus1s() {
        val p = PhraseJarvis(1, auto = false, maintenant = 0)
        p.ajouter(ShortArray(40_000), fort = false, maintenant = 0)
        p.prete = true
        assertEquals(listOf(32_005, 32_005, 16_005), p.trames(toutes = true).map { it.size })
    }

    @Test
    fun phraseBorneeA14s() {
        val p = PhraseJarvis(1, auto = false, maintenant = 0)
        assertFalse(p.ajouter(ShortArray(13 * 16_000), fort = true, maintenant = 0))
        assertTrue(p.ajouter(ShortArray(2 * 16_000), fort = true, maintenant = 0))
        assertEquals(14 * 16_000, p.total)
    }

    @Test
    fun finAuSilenceEnModeAuto() {
        val p = PhraseJarvis(1, auto = true, maintenant = 0)
        assertFalse(p.ajouter(ShortArray(1_600), fort = true, maintenant = 100))
        assertFalse(p.ajouter(ShortArray(1_600), fort = false, maintenant = 1_200))
        assertTrue(p.ajouter(ShortArray(1_600), fort = false, maintenant = 1_400))
        // au relâché (mode maintenu), le silence n'arrête rien
        val q = PhraseJarvis(2, auto = false, maintenant = 0)
        q.ajouter(shortArrayOf(1), fort = true, maintenant = 0)
        assertFalse(q.ajouter(shortArrayOf(1), fort = false, maintenant = 10_000))
    }

    @Test
    fun rienDitEn6s() {
        val p = PhraseJarvis(1, auto = true, maintenant = 0)
        assertFalse(p.ajouter(ShortArray(6 * 16_000), fort = false, maintenant = 0))
        assertTrue(p.ajouter(shortArrayOf(0), fort = false, maintenant = 0))
        assertTrue(p.sansParole)
        val court = PhraseJarvis(2, auto = false, maintenant = 0)
        court.ajouter(ShortArray(4_000), fort = true, maintenant = 0)
        assertTrue(court.sansParole)                               // moins de 0,3 s
    }
}
