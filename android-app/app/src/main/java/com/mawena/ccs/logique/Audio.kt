package com.mawena.ccs.logique

import com.mawena.ccs.reseau.EtatReseau
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.intOrNull
import java.util.TreeMap

/**
 * Son partagé sur le réseau maillé (phase 42, `docs/audio.md`), sans Android (testé à part) :
 * paquets RTP/Opus (RFC 7587), tampon de gigue, en-tête OpusHead du décodeur, nom de l'appareil et
 * lecture des événements `audio` du pont.
 */
object Audio {
    const val PORT = 4010
    const val FREQUENCE = 48_000
    const val CANAUX = 2
    const val TRAME_MS = 20
    /** Échantillons (par canal) d'une trame de 20 ms : l'horodatage RTP avance d'autant. */
    const val ECHANTILLONS_TRAME = FREQUENCE * TRAME_MS / 1000
    const val CHARGE_RTP = 96
    const val DEBIT = 96_000
    const val ANNONCE_MS = 30_000L
    /** Rien reçu pendant 10 s : on cesse d'écouter. */
    const val SILENCE_MAX_MS = 10_000L

    // ---- RTP --------------------------------------------------------------------------------

    /** Un paquet RTP lu. */
    class PaquetRtp(val sequence: Int, val horodatage: Long, val ssrc: Long, val charge: Int, val marqueur: Boolean, val donnees: ByteArray)

    /** En-tête de 12 octets (V=2, sans bourrage, extension ni CSRC) suivi de la trame Opus brute. */
    fun paquetRtp(sequence: Int, horodatage: Long, ssrc: Long, trame: ByteArray, charge: Int = CHARGE_RTP, marqueur: Boolean = false): ByteArray {
        val p = ByteArray(12 + trame.size)
        p[0] = 0x80.toByte()
        p[1] = ((if (marqueur) 0x80 else 0) or (charge and 0x7f)).toByte()
        p[2] = (sequence ushr 8).toByte()
        p[3] = sequence.toByte()
        ecrire32(p, 4, horodatage)
        ecrire32(p, 8, ssrc)
        trame.copyInto(p, 12)
        return p
    }

    /** Lit un paquet RTP (CSRC, extension et bourrage sautés) ; null s'il est invalide. */
    fun lireRtp(octets: ByteArray, longueur: Int = octets.size): PaquetRtp? {
        if (longueur < 12 || longueur > octets.size) return null
        val b0 = octets[0].toInt() and 0xff
        if (b0 ushr 6 != 2) return null
        var debut = 12 + 4 * (b0 and 0x0f)
        var fin = longueur
        if (b0 and 0x10 != 0) {                       // extension : 4 octets + longueur en mots
            if (fin < debut + 4) return null
            val mots = ((octets[debut + 2].toInt() and 0xff) shl 8) or (octets[debut + 3].toInt() and 0xff)
            debut += 4 + 4 * mots
        }
        if (b0 and 0x20 != 0) {                       // bourrage : le dernier octet en donne la taille
            val bourrage = octets[fin - 1].toInt() and 0xff
            fin -= bourrage
        }
        if (fin < debut) return null
        val b1 = octets[1].toInt() and 0xff
        return PaquetRtp(
            sequence = ((octets[2].toInt() and 0xff) shl 8) or (octets[3].toInt() and 0xff),
            horodatage = lire32(octets, 4),
            ssrc = lire32(octets, 8),
            charge = b1 and 0x7f,
            marqueur = b1 and 0x80 != 0,
            donnees = octets.copyOfRange(debut, fin),
        )
    }

    private fun ecrire32(p: ByteArray, i: Int, v: Long) {
        p[i] = (v ushr 24).toByte(); p[i + 1] = (v ushr 16).toByte(); p[i + 2] = (v ushr 8).toByte(); p[i + 3] = v.toByte()
    }

    private fun lire32(p: ByteArray, i: Int): Long =
        ((p[i].toLong() and 0xff) shl 24) or ((p[i + 1].toLong() and 0xff) shl 16) or
            ((p[i + 2].toLong() and 0xff) shl 8) or (p[i + 3].toLong() and 0xff)

    /** Numérotation d'un émetteur : séquence et horodatage de départ aléatoires, +1 et +960 par trame. */
    class Numeroteur(private var sequence: Int, private var horodatage: Long, val ssrc: Long) {
        fun paquet(trame: ByteArray): ByteArray {
            val p = paquetRtp(sequence, horodatage, ssrc, trame)
            sequence = (sequence + 1) and 0xffff
            horodatage = (horodatage + ECHANTILLONS_TRAME) and 0xffffffffL
            return p
        }

        companion object {
            fun auHasard(r: java.util.Random = java.security.SecureRandom()) =
                Numeroteur(r.nextInt(0x10000), r.nextInt().toLong() and 0xffffffffL, r.nextInt().toLong() and 0xffffffffL)
        }
    }

    // ---- tampon de gigue ---------------------------------------------------------------------

    /** Ce que rend le tampon à chaque tic de 20 ms. */
    sealed interface Sortie {
        /** Pas encore assez de paquets (départ, ou reprise après un long trou) : ne rien jouer. */
        data object Attente : Sortie
        /** Paquet manquant : masquage de perte ou silence. */
        data object Perte : Sortie
        class Trame(val donnees: ByteArray) : Sortie
    }

    /**
     * Tampon de gigue de 60 à 150 ms : les paquets sont rangés par numéro de séquence (étendu
     * au-delà de 16 bits), les retardataires et les doublons jetés. La lecture commence quand
     * [minTrames] trames attendent ; au-delà de [maxTrames], les plus anciennes sont jetées pour
     * rattraper le retard. Après [videMax] tics sans rien, on repart de zéro (l'émetteur s'est tu,
     * ou a recommencé avec une autre numérotation). Pas thread-safe : l'appelant synchronise.
     */
    class TamponGigue(val minTrames: Int = 3, val maxTrames: Int = 7, val videMax: Int = 5) {
        private val paquets = TreeMap<Long, ByteArray>()
        private var prochain: Long? = null       // séquence étendue de la prochaine trame à jouer
        private var reference: Long? = null      // dernière séquence étendue reçue
        private var vides = 0

        val taille: Int get() = paquets.size
        val enLecture: Boolean get() = prochain != null

        /** Range un paquet ; false s'il arrive trop tard ou en double. */
        fun ajouter(sequence: Int, donnees: ByteArray): Boolean {
            val ref = reference
            var etendue = if (ref == null) sequence.toLong() + 0x10000 else etendre(sequence, ref)
            val attendu = prochain
            if (ref != null && kotlin.math.abs(etendue - ref) > SAUT_MAX) {
                vider()                                 // nouvelle numérotation : on repart
                etendue = sequence.toLong() + 0x10000
            } else if (attendu != null && etendue < attendu) {
                return false
            }
            if (paquets.containsKey(etendue)) return false
            paquets[etendue] = donnees
            if (reference == null || etendue > reference!!) reference = etendue
            return true
        }

        /** La trame de ce tic de 20 ms. */
        fun prendre(): Sortie {
            var attendu = prochain
            if (attendu == null) {
                if (paquets.size < minTrames) return Sortie.Attente
                attendu = paquets.firstKey()
            }
            if (paquets.size > maxTrames) {
                // trop de retard accumulé : on jette les plus anciennes et on saute à la suivante
                while (paquets.size > maxTrames) paquets.pollFirstEntry()
                attendu = maxOf(attendu, paquets.firstKey())
            }
            if (paquets.isNotEmpty() && paquets.firstKey() > attendu + maxTrames) attendu = paquets.firstKey()
            val trame = paquets.remove(attendu)
            // paquets plus anciens que la trame jouée : trop tard
            while (paquets.isNotEmpty() && paquets.firstKey() < attendu) paquets.pollFirstEntry()
            prochain = attendu + 1
            if (trame != null) {
                vides = 0
                return Sortie.Trame(trame)
            }
            if (paquets.isEmpty() && ++vides >= videMax) {
                prochain = null
                vides = 0
            }
            return Sortie.Perte
        }

        fun vider() {
            paquets.clear()
            prochain = null
            reference = null
            vides = 0
        }

        private companion object {
            const val SAUT_MAX = 3_000L
        }
    }

    /** Séquence RTP de 16 bits → séquence étendue la plus proche de [reference]. */
    fun etendre(sequence: Int, reference: Long): Long {
        var ecart = (sequence - (reference and 0xffff).toInt()) and 0xffff
        if (ecart >= 0x8000) ecart -= 0x10000
        return reference + ecart
    }

    // ---- Opus pour MediaCodec ----------------------------------------------------------------

    /** En-tête OpusHead (RFC 7845, 19 octets) : csd-0 du décodeur `audio/opus`. */
    fun opusHead(canaux: Int = CANAUX, preSkip: Int = 0, frequence: Int = FREQUENCE): ByteArray {
        val h = ByteArray(19)
        "OpusHead".toByteArray(Charsets.US_ASCII).copyInto(h)
        h[8] = 1
        h[9] = canaux.toByte()
        h[10] = preSkip.toByte(); h[11] = (preSkip ushr 8).toByte()
        h[12] = frequence.toByte(); h[13] = (frequence ushr 8).toByte()
        h[14] = (frequence ushr 16).toByte(); h[15] = (frequence ushr 24).toByte()
        // gain de sortie (16, 17) nul, famille de répartition des canaux (18) : 0
        return h
    }

    /** csd-1 (délai du codec) et csd-2 (pré-roulage de 80 ms) : nanosecondes, 64 bits petit-boutien. */
    fun csdNanos(nanos: Long): ByteArray = ByteArray(8) { i -> (nanos ushr (8 * i)).toByte() }

    fun delaiCodecNanos(preSkip: Int = 0): Long = preSkip * 1_000_000_000L / FREQUENCE
    const val PREROULAGE_NANOS = 80_000_000L

    // ---- appareil ----------------------------------------------------------------------------

    private val NOM = Regex("^[A-Za-z0-9][A-Za-z0-9._-]{0,62}$")

    /** Adresse du réseau maillé (100.64.0.0/10) parmi les adresses IPv4 de l'appareil. */
    fun ipMaille(adresses: List<String>): String? =
        adresses.firstOrNull { Reseau.adresse(it).sorte == Reseau.SorteAdresse.Maille && ':' !in it }

    /**
     * Nom de l'appareil pour le pont : celui du pair du réseau maillé (`network.status`) qui a son
     * adresse 100.64.x ; à défaut, un nom tiré du modèle (« pixel », sinon le modèle en minuscules).
     */
    fun nomAppareil(etat: EtatReseau?, ip: String?, modele: String): String {
        if (etat != null && ip != null) {
            val tous = listOfNotNull(etat.ici) + etat.peers
            val pair = tous.firstOrNull { ip in it.ips }?.name
                ?: etat.nodes.firstOrNull { ip in it.ips }?.name
            pair?.let { nettoyer(it) }?.let { return it }
        }
        if ("pixel" in modele.lowercase()) return "pixel"
        return nettoyer(modele) ?: "android"
    }

    /** Nom valide pour le pont (lettres, chiffres, `.`, `_`, `-`, 63 au plus), ou null. */
    fun nettoyer(nom: String): String? {
        val n = nom.trim().substringBefore('.').lowercase()
            .replace(Regex("[^a-z0-9._-]+"), "-").trim('-', '.', '_').take(63)
        return n.takeIf { NOM.matches(it) }
    }

    // ---- événements `audio` du pont ------------------------------------------------------------

    sealed interface Evenement {
        val flux: String

        /** Ce téléphone est la sortie : écouter sur [port] et jouer. */
        data class Recevoir(override val flux: String, val source: String, val nomSource: String, val port: Int, val canaux: Int) : Evenement
        /** Ce téléphone est la source : capter son son et l'émettre vers [ip]:[port]. */
        data class Emettre(override val flux: String, val cible: String, val nomCible: String, val ip: String, val port: Int) : Evenement
        data class Arreter(override val flux: String, val raison: String) : Evenement
    }

    /** L'événement `audio` s'il concerne [moi], sinon null. */
    fun lireEvenement(d: JsonObject, moi: String): Evenement? {
        fun t(cle: String) = (d[cle] as? JsonPrimitive)?.contentOrNull.orEmpty()
        fun n(cle: String) = (d[cle] as? JsonPrimitive)?.intOrNull
        val flux = t("stream").ifEmpty { return null }
        return when (t("action")) {
            "receive" -> if (t("device") != moi) null else Evenement.Recevoir(
                flux, t("source"), t("from_label").ifEmpty { t("source") }, n("port") ?: PORT, (n("channels") ?: CANAUX).coerceIn(1, 2),
            )
            "emit" -> if (t("device") != moi || t("ip").isEmpty()) null else Evenement.Emettre(
                flux, t("target"), t("to_label").ifEmpty { t("target") }, t("ip"), n("port") ?: PORT,
            )
            "stop" -> {
                val appareils = (d["devices"] as? JsonArray)?.mapNotNull { (it as? JsonPrimitive)?.contentOrNull }.orEmpty() +
                    listOf(t("source"), t("target"))
                if (moi !in appareils) null else Evenement.Arreter(flux, t("reason"))
            }
            else -> null
        }
    }
}
