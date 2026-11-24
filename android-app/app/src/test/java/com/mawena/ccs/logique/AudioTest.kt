package com.mawena.ccs.logique

import com.mawena.ccs.logique.Audio.Sortie
import com.mawena.ccs.reseau.Appareil
import com.mawena.ccs.reseau.EtatReseau
import com.mawena.ccs.reseau.NoeudServeur
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import kotlinx.serialization.json.putJsonArray
import kotlinx.serialization.json.add
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class AudioTest {
    private fun trame(i: Int) = byteArrayOf(i.toByte(), 1, 2)

    private fun lue(s: Sortie): Int? = (s as? Sortie.Trame)?.donnees?.get(0)?.toInt()

    @Test
    fun paquetRtpAllerRetour() {
        val p = Audio.paquetRtp(0xfffe, 0xfffffff0L, 0x12345678L, byteArrayOf(9, 8, 7))
        assertEquals(15, p.size)
        assertEquals(0x80, p[0].toInt() and 0xff)
        assertEquals(96, p[1].toInt() and 0xff)
        val r = Audio.lireRtp(p)!!
        assertEquals(0xfffe, r.sequence)
        assertEquals(0xfffffff0L, r.horodatage)
        assertEquals(0x12345678L, r.ssrc)
        assertEquals(96, r.charge)
        assertFalse(r.marqueur)
        assertArrayEquals(byteArrayOf(9, 8, 7), r.donnees)
    }

    @Test
    fun rtpAvecCsrcExtensionEtBourrage() {
        // V=2, P=1, X=1, CC=1 ; 1 CSRC, extension d'un mot, 2 octets de bourrage
        val p = byteArrayOf(
            0xB1.toByte(), 96, 0, 5, 0, 0, 0, 1, 0, 0, 0, 2,
            0, 0, 0, 3,                       // CSRC
            0xBE.toByte(), 0xDE.toByte(), 0, 1, 1, 2, 3, 4,   // extension
            42, 43, 0, 2,                     // charge 42 43 puis bourrage (2)
        )
        val r = Audio.lireRtp(p)!!
        assertEquals(5, r.sequence)
        assertArrayEquals(byteArrayOf(42, 43), r.donnees)
        assertNull(Audio.lireRtp(byteArrayOf(0x80.toByte(), 96, 0)))
        assertNull(Audio.lireRtp(ByteArray(12)))           // version 0
    }

    @Test
    fun numeroteurAvanceDe960() {
        val n = Audio.Numeroteur(0xffff, 0xffffffffL - 100, 7)
        val a = Audio.lireRtp(n.paquet(trame(1)))!!
        val b = Audio.lireRtp(n.paquet(trame(2)))!!
        assertEquals(0xffff, a.sequence)
        assertEquals(0, b.sequence)
        assertEquals((0xffffffffL - 100 + 960) and 0xffffffffL, b.horodatage)
        assertEquals(7L, b.ssrc)
    }

    @Test
    fun extensionDeSequence() {
        assertEquals(0x10000L + 0x10001, Audio.etendre(1, 0x10000L + 0xffff))
        assertEquals(0x10000L + 0xfffe, Audio.etendre(0xfffe, 0x20000L + 2))
        assertEquals(105L, Audio.etendre(105, 100))
    }

    @Test
    fun tamponAttendPuisJoueDansLOrdre() {
        val t = Audio.TamponGigue(minTrames = 3, maxTrames = 7)
        assertTrue(t.ajouter(11, trame(11)))
        assertTrue(t.ajouter(10, trame(10)))
        assertEquals(Sortie.Attente, t.prendre())
        assertTrue(t.ajouter(12, trame(12)))
        assertEquals(10, lue(t.prendre()))
        assertEquals(11, lue(t.prendre()))
        assertFalse(t.ajouter(10, trame(10)))       // trop tard
        assertFalse(t.ajouter(12, trame(12)))       // doublon
        assertEquals(12, lue(t.prendre()))
    }

    @Test
    fun tamponPerteEtRetardataire() {
        val t = Audio.TamponGigue(minTrames = 2, maxTrames = 7)
        t.ajouter(1, trame(1)); t.ajouter(3, trame(3)); t.ajouter(4, trame(4))
        assertEquals(1, lue(t.prendre()))
        assertEquals(Sortie.Perte, t.prendre())       // 2 manque
        assertFalse(t.ajouter(2, trame(2)))           // arrivé après son tour
        assertEquals(3, lue(t.prendre()))
    }

    @Test
    fun tamponRattrapeLeRetard() {
        val t = Audio.TamponGigue(minTrames = 3, maxTrames = 7)
        for (s in 0 until 12) t.ajouter(s, trame(s))
        // 12 en attente > 7 : les 5 plus anciennes sont jetées
        assertEquals(5, lue(t.prendre()))
        assertEquals(6, t.taille)
    }

    @Test
    fun tamponPasseLeTourDeLaSequence() {
        val t = Audio.TamponGigue(minTrames = 2, maxTrames = 7)
        t.ajouter(0xfffe, trame(1)); t.ajouter(0xffff, trame(2)); t.ajouter(0, trame(3)); t.ajouter(1, trame(4))
        assertEquals(listOf(1, 2, 3, 4), List(4) { lue(t.prendre()) })
    }

    @Test
    fun tamponRepartApresUnSilence() {
        val t = Audio.TamponGigue(minTrames = 2, maxTrames = 7, videMax = 3)
        t.ajouter(1, trame(1)); t.ajouter(2, trame(2))
        t.prendre(); t.prendre()
        repeat(3) { assertEquals(Sortie.Perte, t.prendre()) }
        assertFalse(t.enLecture)
        // l'émetteur reprend plus loin (paquets d'avant le silence perdus) : nouveau départ
        t.ajouter(40, trame(40))
        assertEquals(Sortie.Attente, t.prendre())
        t.ajouter(41, trame(41))
        assertEquals(40, lue(t.prendre()))
    }

    @Test
    fun tamponNouvelleNumerotation() {
        val t = Audio.TamponGigue(minTrames = 1, maxTrames = 7)
        t.ajouter(100, trame(1))
        assertEquals(1, lue(t.prendre()))
        assertTrue(t.ajouter(30_000, trame(2)))       // saut énorme : on repart
        assertEquals(2, lue(t.prendre()))
    }

    @Test
    fun opusHeadEtCsd() {
        val h = Audio.opusHead(canaux = 2, preSkip = 312)
        assertEquals(19, h.size)
        assertEquals("OpusHead", String(h, 0, 8, Charsets.US_ASCII))
        assertEquals(1, h[8].toInt())
        assertEquals(2, h[9].toInt())
        assertEquals(312, (h[10].toInt() and 0xff) or ((h[11].toInt() and 0xff) shl 8))
        assertEquals(48_000, (h[12].toInt() and 0xff) or ((h[13].toInt() and 0xff) shl 8) or ((h[14].toInt() and 0xff) shl 16))
        assertEquals(0, h[18].toInt())
        assertArrayEquals(byteArrayOf(0, 0xB4.toByte(), 0xC4.toByte(), 4, 0, 0, 0, 0), Audio.csdNanos(Audio.PREROULAGE_NANOS))
        assertEquals(6_500_000L, Audio.delaiCodecNanos(312))
    }

    @Test
    fun adresseMaillee() {
        assertEquals("100.64.0.3", Audio.ipMaille(listOf("192.168.1.20", "100.64.0.3", "10.0.0.2")))
        assertNull(Audio.ipMaille(listOf("192.168.1.20", "fd7a:115c::3")))
        assertEquals("100.100.1.2", Audio.ipMaille(listOf("100.100.1.2")))
        assertNull(Audio.ipMaille(listOf("100.128.0.1")))
    }

    @Test
    fun nomDeLAppareil() {
        val e = EtatReseau(
            ici = Appareil(name = "mawena-cloud", ips = listOf("100.64.0.1")),
            peers = listOf(Appareil(name = "pixel-de-charles", ips = listOf("100.64.0.3", "fd7a::3"))),
            nodes = listOf(NoeudServeur(name = "tablette", ips = listOf("100.64.0.9"))),
        )
        assertEquals("pixel-de-charles", Audio.nomAppareil(e, "100.64.0.3", "Pixel 8"))
        assertEquals("tablette", Audio.nomAppareil(e, "100.64.0.9", "x"))
        assertEquals("pixel", Audio.nomAppareil(e, "100.64.0.7", "Pixel 8"))
        assertEquals("sm-g991b", Audio.nomAppareil(null, null, "SM-G991B"))
        assertEquals("android", Audio.nomAppareil(null, null, "  "))
        assertEquals("pixel", Audio.nettoyer("Pixel.tail1234.ts.net"))
        assertNull(Audio.nettoyer("---"))
    }

    @Test
    fun evenements() {
        val recevoir = buildJsonObject {
            put("action", "receive"); put("device", "pixel"); put("stream", "a3"); put("source", "pc-bureau")
            put("from_label", "PC du bureau"); put("port", 4010); put("channels", 2)
        }
        assertEquals(Audio.Evenement.Recevoir("a3", "pc-bureau", "PC du bureau", 4010, 2), Audio.lireEvenement(recevoir, "pixel"))
        assertNull(Audio.lireEvenement(recevoir, "iphone"))
        val emettre = buildJsonObject {
            put("action", "emit"); put("device", "pixel"); put("stream", "a4"); put("target", "iphone")
            put("to_label", "iPhone"); put("ip", "100.64.0.4"); put("port", 4010)
        }
        assertEquals(Audio.Evenement.Emettre("a4", "iphone", "iPhone", "100.64.0.4", 4010), Audio.lireEvenement(emettre, "pixel"))
        val stop = buildJsonObject {
            put("action", "stop"); put("stream", "a4"); put("reason", "arrêté")
            putJsonArray("devices") { add("pixel"); add("iphone") }
        }
        assertEquals(Audio.Evenement.Arreter("a4", "arrêté"), Audio.lireEvenement(stop, "iphone"))
        assertNull(Audio.lireEvenement(stop, "pc-bureau"))
        assertNull(Audio.lireEvenement(buildJsonObject { put("action", "receive"); put("device", "pixel") }, "pixel"))
    }
}
