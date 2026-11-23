package com.mawena.ccs.logique

import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.longOrNull
import kotlinx.serialization.json.put
import java.util.Base64
import kotlin.math.roundToInt
import kotlin.math.sqrt

/**
 * Oreille « bouton » de Jarvis (assistant vocal, projet voisin), sans Android : adresse
 * d'appairage, messages du protocole des oreilles (crates/jarvis-protocol), trames de son,
 * rééchantillonnage vers 16 kHz, phrase en cours. Même logique que la version web
 * (`ccs_app/web/jarvis-ear.js`) ; le lien passe par le relais de CCS (`/api/jarvis/oreille`).
 */
object Jarvis {
    const val FREQUENCE = 16_000
    /** Échantillons au plus par trame (1 s, `frame.rs`). */
    const val MAX_ECHANTILLONS_TRAME = 16_000
    /** Une trame toutes les 100 ms. */
    const val ECHANTILLONS_PAR_TRAME = 1_600
    /** Son d'une phrase au plus (14 s). */
    const val MAX_PHRASE = 14 * FREQUENCE
    /** Fermeture du relais : Jarvis injoignable ou lien rompu. */
    const val FERMETURE_INJOIGNABLE = 4011
    /** Niveau (RMS, échantillons entre -1 et 1) au-dessus duquel on parle. */
    const val SEUIL_PAROLE = 0.02f
    /** Mode « appui court » : fin après ce silence (ms), ou si rien n'est dit en 6 s. */
    const val SILENCE_FIN_MS = 1_200L
    const val SANS_PAROLE_MAX = 6 * FREQUENCE
    /** Lien fermé après 2 min sans phrase. */
    const val INACTIVITE_MS = 120_000L

    private const val PREFIXE = "jarvis://pair?"
    private val EMPREINTE = Regex("^[A-Za-z0-9_-]{43}$")
    private val CODE = Regex("^[0-9]{6}$")
    private val GUILLEMETS = charArrayOf('"', '\'', '«', '»', '“', '”', '`', '<', '>')
    private val json = Json { ignoreUnknownKeys = true }

    // ── appairage ──

    fun empreinteValide(s: String) = EMPREINTE.matches(s)

    fun codeValide(s: String) = CODE.matches(s)

    /** Saisie collée : première ligne non vide, sans espaces ni guillemets autour. */
    fun nettoyer(brut: String): String {
        val ligne = brut.lineSequence().map { it.trim() }.firstOrNull { it.isNotEmpty() } ?: return ""
        return ligne.trim { it.isWhitespace() || it in GUILLEMETS }
    }

    /** `jarvis://pair?v=1&id=…&h=…&p=7341&fp=…&c=482913` (crates/jarvis-protocol/src/pairing_uri.rs). */
    fun lireAdresse(texte: String): CibleAppairage {
        val s = nettoyer(texte)
        if (!s.startsWith(PREFIXE)) throw ErreurJarvis("Ce n'est pas une adresse d'appairage Jarvis (jarvis://pair?…).")
        val params = HashMap<String, String>()
        for (kv in s.substring(PREFIXE.length).split('&')) {
            val i = kv.indexOf('=')
            if (i < 0 || params.containsKey(kv.substring(0, i))) throw ErreurJarvis("Adresse d'appairage mal formée.")
            params[kv.substring(0, i)] = kv.substring(i + 1)
        }
        if (params["v"] != "1") throw ErreurJarvis("Version d'appairage inconnue : mets Jarvis à jour.")
        val empreinte = params["fp"].orEmpty()
        val code = params["c"].orEmpty()
        if (!empreinteValide(empreinte)) throw ErreurJarvis("Empreinte du cerveau invalide dans l'adresse.")
        if (!codeValide(code)) throw ErreurJarvis("Code d'appairage invalide dans l'adresse.")
        return CibleAppairage(code, empreinte, params["id"].orEmpty(), params["p"]?.toIntOrNull() ?: 0)
    }

    // ── messages de l'oreille ──

    fun hello(a: AppairageJarvis): String = buildJsonObject {
        put("type", "hello"); put("version", 1); put("ear_id", a.earId); put("token", a.token)
    }.toString()

    fun pair(code: String, nom: String): String = buildJsonObject {
        put("type", "pair"); put("version", 1); put("code", code); put("name", nom.take(60)); put("platform", "android")
    }.toString()

    fun wake(phrase: Long): String = buildJsonObject {
        put("type", "wake"); put("utterance", phrase); put("score", 2.0); put("level_db", 0); put("muted", false)
    }.toString()

    /** Réponse à une question de Jarvis (`await_reply`), sans mot d'éveil. */
    fun listenStart(phrase: Long): String = buildJsonObject {
        put("type", "listen_start"); put("utterance", phrase)
    }.toString()

    fun listenEnd(phrase: Long, sansParole: Boolean): String = buildJsonObject {
        put("type", "listen_end"); put("utterance", phrase); put("muted", false); put("no_speech", sansParole)
        put("cut", JsonNull)
    }.toString()

    // ── messages du cerveau (et du relais) ──

    private fun JsonObject.texte(cle: String): String = (this[cle] as? JsonPrimitive)?.takeIf { it !is JsonNull }?.contentOrNull.orEmpty()

    private fun JsonObject.objet(cle: String): JsonObject = this[cle] as? JsonObject ?: JsonObject(emptyMap())

    fun lire(texte: String): MessageCerveau {
        val m = runCatching { json.parseToJsonElement(texte).jsonObject }.getOrNull() ?: return MessageCerveau.Autre
        val phrase = (m["utterance"] as? JsonPrimitive)?.longOrNull ?: 0L
        return when (m.texte("type")) {
            "welcome" -> MessageCerveau.Bienvenue(m.texte("brain_name"))
            "paired" -> MessageCerveau.Appaire(m.texte("ear_id"), m.texte("token"), m.texte("brain_id"), m.texte("brain_name"))
            "rejected" -> m.objet("reason").let { r ->
                MessageCerveau.Refus(r.texte("kind"), (r["attempts_left"] as? JsonPrimitive)?.intOrNull)
            }
            "elected" -> MessageCerveau.Elu(phrase)
            "stop" -> MessageCerveau.Stop(phrase)
            "relay_error" -> MessageCerveau.Relais(m.texte("message"))
            "response" -> {
                val r = m.objet("response")
                when (r.texte("type")) {
                    "heard" -> {
                        val a = r["audio"] as? JsonObject
                        val voix = a?.texte("pcm")?.takeIf { it.isNotEmpty() }?.let { pcm ->
                            VoixJarvis(pcm, (a["sample_rate"] as? JsonPrimitive)?.intOrNull ?: 22_050)
                        }
                        MessageCerveau.Entendu(r.texte("text"), r.texte("speech"), voix, r.texte("ear_action") == "await_reply")
                    }
                    "reply" -> MessageCerveau.Reponse(r.texte("speech"))
                    "error" -> MessageCerveau.Erreur(r.texte("message").ifEmpty { "Erreur de Jarvis." })
                    else -> MessageCerveau.Autre
                }
            }
            else -> MessageCerveau.Autre
        }
    }

    /** Refus du cerveau (`rejected`), lisible. */
    fun texteRefus(motif: String, essais: Int?): String {
        val t = when (motif) {
            "unknown_ear" -> "Ce téléphone n'est plus appairé (retiré par « jarvis unpair » ?). Refais l'appairage."
            "bad_token" -> "Jeton refusé par Jarvis : refais l'appairage."
            "version" -> "Version du protocole refusée : mets CCS ou Jarvis à jour."
            "pairing_closed" -> "Pas de fenêtre d'appairage ouverte : lance « jarvis pair » sur la machine de Jarvis."
            "wrong_code" -> "Code d'appairage faux."
            else -> "Jarvis a refusé la connexion."
        }
        return if (motif == "wrong_code" && essais != null) "$t Essais restants : $essais." else t
    }

    /** Fermeture du lien par le relais : code WebSocket, dernier `relay_error`, raison de la fermeture. */
    fun texteFermeture(code: Int, relais: String?, raison: String): String {
        val detail = relais?.takeIf { it.isNotEmpty() } ?: raison.takeIf { it.isNotBlank() }
        return when (code) {
            FERMETURE_INJOIGNABLE -> "Jarvis est injoignable" + (detail?.let { " : $it" } ?: ".")
            4001 -> "Session CCS terminée : reconnecte l'appli."
            1011, 1012 -> detail ?: "Pont CCS injoignable."
            else -> detail ?: "Connexion au relais de Jarvis perdue."
        }
    }

    // ── son ──

    /** Trame de son du micro : `0x01` + phrase u32 LE + échantillons i16 LE (`frame.rs`). */
    fun trameMicro(phrase: Long, echantillons: ShortArray, debut: Int = 0, fin: Int = echantillons.size): ByteArray {
        val n = fin - debut
        val out = ByteArray(5 + 2 * n)
        out[0] = 1
        for (k in 0 until 4) out[1 + k] = (phrase ushr (8 * k)).toByte()
        for (i in 0 until n) {
            val v = echantillons[debut + i].toInt()
            out[5 + 2 * i] = v.toByte()
            out[6 + 2 * i] = (v shr 8).toByte()
        }
        return out
    }

    /** Voix de Jarvis : PCM i16 LE mono en base64 → échantillons (vide si illisible). */
    fun decoderPcm(b64: String): ShortArray {
        val o = runCatching { Base64.getDecoder().decode(b64) }.getOrNull() ?: return ShortArray(0)
        return ShortArray(o.size / 2) { i -> ((o[2 * i].toInt() and 0xFF) or (o[2 * i + 1].toInt() shl 8)).toShort() }
    }

    fun rms(morceau: FloatArray, n: Int = morceau.size): Float {
        if (n <= 0) return 0f
        var s = 0f
        for (i in 0 until n) s += morceau[i] * morceau[i]
        return sqrt(s / n)
    }
}

/** Erreur lisible telle quelle ; `refus` : motif du refus du cerveau (`unknown_ear`, `bad_token`…). */
class ErreurJarvis(message: String, val refus: String? = null) : Exception(message)

/** Appairage gardé chiffré : identifiant d'oreille, jeton, empreinte du cerveau. */
@Serializable
data class AppairageJarvis(
    val earId: String,
    val token: String,
    val fingerprint: String,
    val brainName: String = "Jarvis",
    val brainId: String = "",
)

/** Ce que donne une adresse d'appairage (ou la saisie à la main). */
data class CibleAppairage(val code: String, val empreinte: String, val cerveau: String = "", val port: Int = 0)

data class VoixJarvis(val pcm: String, val frequence: Int)

sealed interface MessageCerveau {
    data class Bienvenue(val nom: String) : MessageCerveau
    data class Appaire(val earId: String, val jeton: String, val cerveauId: String, val nom: String) : MessageCerveau
    data class Refus(val motif: String, val essais: Int?) : MessageCerveau
    data class Elu(val phrase: Long) : MessageCerveau
    data class Stop(val phrase: Long) : MessageCerveau
    data class Entendu(val texte: String, val voix: String, val audio: VoixJarvis?, val attendReponse: Boolean) : MessageCerveau
    data class Reponse(val voix: String) : MessageCerveau
    data class Erreur(val message: String) : MessageCerveau
    /** Message du relais de CCS avant sa fermeture (Jarvis injoignable…). */
    data class Relais(val message: String) : MessageCerveau
    data object Autre : MessageCerveau
}

/**
 * Rééchantillonnage vers 16 kHz par moyenne glissante (filtre suffisant pour la voix), en i16 ;
 * l'état est gardé d'un morceau à l'autre. Utilisé sur le fil du micro seulement.
 */
class Reechantillonneur(frequence: Int) {
    private val pas = frequence.toDouble() / Jarvis.FREQUENCE
    private var pos = 0.0
    private var somme = 0f
    private var n = 0

    fun pousser(entree: FloatArray, taille: Int = entree.size): ShortArray {
        val out = ShortArray((taille / pas).toInt() + 2)
        var k = 0
        for (i in 0 until taille) {
            somme += entree[i]
            n++
            if (i + 1 >= pos + pas) {
                val v = (somme / n).coerceIn(-1f, 1f)
                out[k++] = (if (v < 0) (v * 32768f).roundToInt() else (v * 32767f).roundToInt()).toShort()
                somme = 0f
                n = 0
                pos += pas
            }
        }
        pos -= taille
        return out.copyOf(k)
    }
}

/**
 * Une phrase : son du micro en attente du lien, décisions d'arrêt (14 s, silence en mode « appui
 * court », rien dit en 6 s), découpage en trames.
 */
class PhraseJarvis(
    val numero: Long,
    /** Fin au silence (appui court, réponse attendue) ; sinon au relâché. */
    var auto: Boolean,
    /** Réponse à une question de Jarvis : `listen_start` au lieu de `wake`. */
    val suite: Boolean = false,
    maintenant: Long,
) {
    /** Lien ouvert et `wake` envoyé : le son peut partir. */
    var prete = false
    /** Micro coupé : il ne reste qu'à envoyer `listen_end`. */
    var finie = false
    private var tampon = ShortArray(Jarvis.MAX_PHRASE)
    private var debut = 0
    private var fin = 0
    var total = 0
        private set
    var parle = false
        private set
    private var dernierSon = maintenant

    /** Échantillons en attente d'envoi. */
    val enAttente: Int get() = fin - debut

    /** Ajoute un morceau du micro (déjà en 16 kHz) ; rend true s'il faut arrêter la phrase. */
    fun ajouter(e: ShortArray, fort: Boolean, maintenant: Long): Boolean {
        if (fort) {
            parle = true
            dernierSon = maintenant
        }
        val pris = minOf(e.size, Jarvis.MAX_PHRASE - total)
        // tout le son d'une phrase tient dans le tampon (14 s) : on écrit à la suite
        e.copyInto(tampon, fin, 0, pris)
        fin += pris
        total += pris
        if (total >= Jarvis.MAX_PHRASE) return true
        if (auto && parle && maintenant - dernierSon > Jarvis.SILENCE_FIN_MS) return true
        if (auto && !parle && total > Jarvis.SANS_PAROLE_MAX) return true
        return false
    }

    /** Trames prêtes à partir (`toutes` : vide le tampon) ; rien tant que le lien n'est pas prêt. */
    fun trames(toutes: Boolean): List<ByteArray> {
        if (!prete) return emptyList()
        val out = ArrayList<ByteArray>()
        while (enAttente >= Jarvis.ECHANTILLONS_PAR_TRAME || (toutes && enAttente > 0)) {
            val n = minOf(Jarvis.MAX_ECHANTILLONS_TRAME, if (toutes) enAttente else Jarvis.ECHANTILLONS_PAR_TRAME)
            out += Jarvis.trameMicro(numero, tampon, debut, debut + n)
            debut += n
        }
        return out
    }

    /** Rien d'utile : pas de voix, ou moins de 0,3 s. */
    val sansParole: Boolean get() = !parle || total < Jarvis.FREQUENCE * 3 / 10
}
