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
    /** Durée visée d'une trame Opus. Les récepteurs acceptent aussi 20 ms (anciens émetteurs). */
    const val TRAME_MS = 10
    /** Échantillons (par canal) d'une trame de 10 ms : 480. */
    const val ECHANTILLONS_TRAME = FREQUENCE * TRAME_MS / 1000
    /** Échantillons d'une trame de 20 ms (encodeur Opus d'Android, anciens émetteurs) : 960. */
    const val ECHANTILLONS_ANCIENNE_TRAME = FREQUENCE * 20 / 1000
    /** Plus long paquet Opus : 120 ms. */
    const val ECHANTILLONS_MAX = FREQUENCE * 120 / 1000
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

    /**
     * Échantillons (par canal, 48 kHz) d'un paquet Opus, lus dans son octet TOC (RFC 6716, § 3.1) :
     * 480 pour 10 ms, 960 pour 20 ms. null si le paquet est vide ou incohérent.
     */
    fun echantillonsOpus(paquet: ByteArray): Int? {
        if (paquet.isEmpty()) return null
        val toc = paquet[0].toInt() and 0xff
        val config = toc shr 3
        val parTrame = when {
            config < 12 -> intArrayOf(480, 960, 1920, 2880)[config % 4]     // SILK : 10, 20, 40, 60 ms
            config < 16 -> intArrayOf(480, 960)[config % 2]                 // hybride : 10, 20 ms
            else -> intArrayOf(120, 240, 480, 960)[config % 4]              // CELT : 2,5, 5, 10, 20 ms
        }
        val nombre = when (toc and 0x03) {
            0 -> 1
            1, 2 -> 2
            else -> if (paquet.size < 2) return null else paquet[1].toInt() and 0x3f
        }
        val n = parTrame * nombre
        return if (n in 1..ECHANTILLONS_MAX) n else null
    }

    /**
     * Numérotation d'un émetteur : séquence et horodatage de départ aléatoires, +1 par trame et,
     * pour l'horodatage, la durée lue dans la trame (480 pour 10 ms, 960 pour 20 ms).
     */
    class Numeroteur(private var sequence: Int, private var horodatage: Long, val ssrc: Long) {
        fun paquet(trame: ByteArray): ByteArray {
            val p = paquetRtp(sequence, horodatage, ssrc, trame)
            sequence = (sequence + 1) and 0xffff
            horodatage = (horodatage + (echantillonsOpus(trame) ?: ECHANTILLONS_TRAME)) and 0xffffffffL
            return p
        }

        companion object {
            fun auHasard(r: java.util.Random = java.security.SecureRandom()) =
                Numeroteur(r.nextInt(0x10000), r.nextInt().toLong() and 0xffffffffL, r.nextInt().toLong() and 0xffffffffL)
        }
    }

    // ---- tampon de gigue ---------------------------------------------------------------------

    /** Ce que rend le tampon à chaque tic (une durée de trame). */
    sealed interface Sortie {
        /** Pas encore assez de paquets (départ, ou reprise après un long trou) : ne rien jouer. */
        data object Attente : Sortie
        /** Paquet manquant : masquage de perte ou silence. */
        data object Perte : Sortie
        class Trame(val donnees: ByteArray) : Sortie
    }

    /**
     * Tampon de gigue compté en trames (réglé par [GigueAdaptative]) : les paquets sont rangés par numéro de séquence (étendu
     * au-delà de 16 bits), les retardataires et les doublons jetés. La lecture commence quand
     * [minTrames] trames attendent ; au-delà de [maxTrames], les plus anciennes sont jetées pour
     * rattraper le retard. Après [videMax] tics sans rien, on repart de zéro (l'émetteur s'est tu,
     * ou a recommencé avec une autre numérotation). Pas thread-safe : l'appelant synchronise.
     */
    class TamponGigue(minTrames: Int = 3, maxTrames: Int = 7, val videMax: Int = 5) {
        var minTrames = minTrames
            private set
        var maxTrames = maxTrames
            private set
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

        /** Change le départ et le plafond (en trames) sans perdre les paquets en attente. */
        fun regler(min: Int, max: Int) {
            minTrames = maxOf(1, min)
            maxTrames = maxOf(minTrames, max)
        }

        /** La trame de ce tic. */
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

    /** Réglages du tampon de gigue adaptatif (les mêmes sur iOS). */
    object Gigue {
        /** Retard visé au départ d'un flux. */
        const val DEPART_MS = 30
        const val MINIMUM_MS = 20
        const val MAXIMUM_MS = 150
        /** Montée sur incident, descente après un moment stable. */
        const val PAS_MS = 10
        /** Au-delà du retard visé plus cette marge, les plus vieilles trames sont sautées. */
        const val MARGE_MS = 40
        /** Joué sans perte ni creux pendant 10 s : on redescend d'un pas. */
        const val STABLE_MS = 10_000
        /** Après une montée, les incidents des 500 ms suivantes ne comptent pas (une rafale = un pas). */
        const val REPIT_MS = 500
        /** Un creux plus long que 300 ms est un silence de la source, pas un tampon trop court. */
        const val CREUX_COURT_MS = 300
    }

    /**
     * Tampon de gigue adaptatif : démarre bas (30 ms), monte d'un pas (10 ms) à chaque perte ou creux
     * court (sous-alimentation), redescend d'un pas après 10 s stables, entre 20 et 150 ms. Compte en
     * trames selon la durée de la dernière trame reçue (10 ou 20 ms, lue dans l'octet TOC).
     * Pas thread-safe : l'appelant synchronise.
     */
    class GigueAdaptative(cibleMs: Int = Gigue.DEPART_MS) {
        val tampon = TamponGigue()
        var cibleMs = cibleMs.coerceIn(Gigue.MINIMUM_MS, Gigue.MAXIMUM_MS)
            private set
        /** Échantillons de la dernière trame reçue : 480 (10 ms) ou 960 (20 ms) le plus souvent. */
        var echantillons = ECHANTILLONS_TRAME
            private set
        private var stableMs = 0
        private var repitMs = 0
        private var creuxMs: Int? = null      // durée du creux en cours

        init { appliquer() }

        /** Durée d'une trame (ms, arrondie vers le bas). */
        val dureeTrameMs: Int get() = maxOf(1, echantillons * 1000 / FREQUENCE)

        fun ajouter(sequence: Int, donnees: ByteArray): Boolean {
            val n = echantillonsOpus(donnees)
            if (n != null && n != echantillons) {
                echantillons = n
                appliquer()
            }
            return tampon.ajouter(sequence, donnees)
        }

        fun prendre(): Sortie {
            val s = tampon.prendre()
            val d = dureeTrameMs
            repitMs = maxOf(0, repitMs - d)
            when (s) {
                is Sortie.Trame -> {
                    val c = creuxMs
                    if (c != null) {
                        creuxMs = null
                        if (c <= Gigue.CREUX_COURT_MS) incident()
                    } else {
                        stableMs += d
                        if (stableMs >= Gigue.STABLE_MS) {
                            stableMs = 0
                            if (cibleMs > Gigue.MINIMUM_MS) {
                                cibleMs = maxOf(Gigue.MINIMUM_MS, cibleMs - Gigue.PAS_MS)
                                appliquer()
                            }
                        }
                    }
                }
                // tampon vide : creux (sous-alimentation ou source qui se tait), jugé à la reprise ;
                // trou avec des trames derrière : paquet perdu, incident tout de suite
                Sortie.Perte -> {
                    if (tampon.taille == 0) creuxMs = (creuxMs ?: 0) + d else incident()
                }
                Sortie.Attente -> {
                    val c = creuxMs
                    if (c != null) creuxMs = c + d
                }
            }
            return s
        }

        fun vider() {
            tampon.vider()
            creuxMs = null
            stableMs = 0
        }

        private fun incident() {
            stableMs = 0
            if (repitMs > 0) return
            repitMs = Gigue.REPIT_MS
            if (cibleMs < Gigue.MAXIMUM_MS) {
                cibleMs = minOf(Gigue.MAXIMUM_MS, cibleMs + Gigue.PAS_MS)
                appliquer()
            }
        }

        private fun appliquer() {
            val parMs = FREQUENCE / 1000
            fun trames(ms: Int) = (ms * parMs + echantillons - 1) / echantillons
            val depart = maxOf(1, trames(cibleMs))
            tampon.regler(depart, depart + maxOf(1, trames(Gigue.MARGE_MS)))
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
