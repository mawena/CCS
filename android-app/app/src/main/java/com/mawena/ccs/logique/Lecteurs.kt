package com.mawena.ccs.logique

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.put
import kotlin.math.roundToInt
import kotlin.math.roundToLong

/**
 * Le téléphone comme lecteur piloté (phase 42), sans Android (testé à part) : les sessions média
 * du téléphone (Spotify, YouTube…, lues par `MediaSessionManager`) mises au format des lecteurs
 * MPRIS de l'agent Linux (`audio.report`, voir `ccs_app/audio.py`, `player_view`), et les
 * commandes `audio.control` du pont traduites en actions pour `MediaController`.
 *
 * Les constantes de `PlaybackState` et `PlaybackInfo` sont recopiées ici (valeurs stables de
 * l'API Android) pour garder ce fichier hors d'Android.
 */
object Lecteurs {
    // PlaybackState.STATE_*
    const val ETAT_ARRETE = 1
    const val ETAT_PAUSE = 2
    const val ETAT_LECTURE = 3
    const val ETAT_AVANCE_RAPIDE = 4
    const val ETAT_RETOUR_RAPIDE = 5
    const val ETAT_CHARGEMENT = 6
    const val ETAT_CONNEXION = 8
    const val ETAT_VERS_PRECEDENT = 9
    const val ETAT_VERS_SUIVANT = 10
    const val ETAT_VERS_ELEMENT = 11

    // PlaybackState.ACTION_*
    const val ACTION_PAUSE = 2L
    const val ACTION_LECTURE = 4L
    const val ACTION_PRECEDENT = 16L
    const val ACTION_SUIVANT = 32L
    const val ACTION_DEPLACER = 256L
    const val ACTION_BASCULE = 512L

    // MediaController.PlaybackInfo.VOLUME_CONTROL_*
    const val VOLUME_FIXE = 0
    const val VOLUME_RELATIF = 1
    const val VOLUME_ABSOLU = 2

    /** Comme l'agent Linux : 16 lecteurs au plus, 6 h de déplacement au plus. */
    const val MAX_LECTEURS = 16
    const val DEPLACEMENT_MAX_S = 6 * 3600.0
    const val DEPLACEMENT_DEFAUT_S = 10.0

    private val ID = Regex("^[A-Za-z0-9_][A-Za-z0-9._-]{0,199}$")

    /** Une session média du téléphone, lue par le code Android ([com.mawena.ccs.son.LecteursTelephone]). */
    data class Session(
        /** Paquet de l'appli (`com.spotify.music`) : sert d'identifiant. */
        val paquet: String,
        /** Nom affiché de l'appli (« Spotify »), vide si inconnu. */
        val nomAppli: String = "",
        /** `PlaybackState.getState()`, null sans état. */
        val etat: Int? = null,
        /** `PlaybackState.getActions()` ; 0 : l'appli n'en dit rien. */
        val actions: Long = 0L,
        val titre: String = "",
        val artiste: String = "",
        /** Position déjà extrapolée (voir [position]), en ms ; null si inconnue. */
        val positionMs: Long? = null,
        /** Durée du morceau en ms ; null ou ≤ 0 si inconnue. */
        val dureeMs: Long? = null,
        /** `PlaybackInfo` : volume courant, maximum et sorte de contrôle. */
        val volume: Int? = null,
        val volumeMax: Int? = null,
        val controleVolume: Int = VOLUME_FIXE,
    )

    /** Statut MPRIS (`Playing`, `Paused`, `Stopped`) d'un état `PlaybackState`. */
    fun statut(etat: Int?): String = when (etat) {
        ETAT_LECTURE, ETAT_AVANCE_RAPIDE, ETAT_RETOUR_RAPIDE, ETAT_CHARGEMENT, ETAT_CONNEXION,
        ETAT_VERS_PRECEDENT, ETAT_VERS_SUIVANT, ETAT_VERS_ELEMENT -> "Playing"
        ETAT_PAUSE -> "Paused"
        else -> "Stopped"
    }

    /**
     * Position courante (ms) : `PlaybackState` donne la position à l'instant [majMs] (horloge
     * `elapsedRealtime`) ; en lecture elle avance de `vitesse` ms par ms. null si inconnue.
     */
    fun position(positionMs: Long, majMs: Long, vitesse: Float, maintenantMs: Long, joue: Boolean, dureeMs: Long? = null): Long? {
        if (positionMs < 0) return null
        var p = positionMs
        if (joue && majMs > 0 && maintenantMs > majMs) p += ((maintenantMs - majMs) * vitesse.toDouble()).roundToLong()
        if (dureeMs != null && dureeMs > 0) p = p.coerceAtMost(dureeMs)
        return p.coerceAtLeast(0)
    }

    /** Volume 0-100 du lecteur, null s'il n'est pas réglable. */
    fun volumePourcent(s: Session): Int? {
        val v = s.volume ?: return null
        val max = s.volumeMax ?: return null
        if (s.controleVolume == VOLUME_FIXE || max <= 0) return null
        return (v.coerceIn(0, max) * 100.0 / max).roundToInt()
    }

    /** Identifiant valide pour le pont (`PLAYER_ID_RE`), tiré du paquet ; null s'il n'y en a pas. */
    fun identifiant(paquet: String): String? {
        val n = paquet.trim().replace(Regex("[^A-Za-z0-9._-]+"), "_").take(190)
        return n.takeIf { ID.matches(it) }
    }

    /**
     * Identifiant de chaque paquet, dans l'ordre de `getActiveSessions` (la plus récente
     * d'abord) : le paquet, suivi de `.2`, `.3`… quand une appli a plusieurs sessions ; null
     * pour un paquet inutilisable ou au-delà de [MAX_LECTEURS].
     */
    fun ids(paquets: List<String>): List<String?> {
        val vus = HashMap<String, Int>()
        var pris = 0
        return paquets.map { p ->
            val base = identifiant(p)
            if (base == null || pris >= MAX_LECTEURS) null
            else {
                pris++
                val n = (vus[base] ?: 0) + 1
                vus[base] = n
                if (n == 1) base else "$base.$n"
            }
        }
    }

    /** Les sessions retenues, avec leur identifiant (voir [ids]). */
    fun identifier(sessions: List<Session>): List<Pair<String, Session>> =
        ids(sessions.map { it.paquet }).zip(sessions).mapNotNull { (id, s) -> id?.let { it to s } }

    /** Un lecteur au format de l'agent Linux (`player_view`) ; positions et durée en secondes. */
    fun lecteur(id: String, s: Session): JsonObject {
        val a = s.actions
        // aucune action annoncée : l'appli ne dit rien, on propose les commandes de base
        val inconnu = a == 0L
        fun peut(bit: Long) = inconnu || a and bit != 0L
        return buildJsonObject {
            put("id", id)
            put("name", s.nomAppli.trim().ifEmpty { s.paquet.substringAfterLast('.') }.take(80))
            put("status", statut(s.etat))
            put("title", s.titre.trim().take(200))
            put("artist", s.artiste.trim().take(200))
            put("position", s.positionMs?.let { JsonPrimitive(it / 1000.0) } ?: JsonNull)
            put("length", s.dureeMs?.takeIf { it > 0 }?.let { JsonPrimitive(it / 1000.0) } ?: JsonNull)
            put("volume", volumePourcent(s)?.let { JsonPrimitive(it) } ?: JsonNull)
            put("can_play", peut(ACTION_LECTURE) || peut(ACTION_BASCULE))
            put("can_pause", peut(ACTION_PAUSE) || peut(ACTION_BASCULE))
            put("can_next", peut(ACTION_SUIVANT))
            put("can_prev", peut(ACTION_PRECEDENT))
            put("can_seek", !inconnu && a and ACTION_DEPLACER != 0L && (s.dureeMs ?: 0L) > 0L)
            put("can_control", true)
        }
    }

    /** La liste envoyée par `audio.report {device, players}`. */
    fun rapport(sessions: List<Session>): JsonArray = buildJsonArray {
        identifier(sessions).forEach { (id, s) -> add(lecteur(id, s)) }
    }

    /** Ce qui change vraiment (pas la position, qui avance seule) : on ne rapporte que les changements. */
    fun instantane(rapport: JsonArray): List<Map<String, Any?>> = rapport.mapNotNull { e ->
        (e as? JsonObject)?.filterKeys { it != "position" }?.mapValues { (_, v) -> v.toString() }
    }

    // ---- commandes --------------------------------------------------------------------------

    /** Une commande `audio.control` à exécuter sur une session. */
    sealed interface Commande {
        val lecteur: String

        data class Lecture(override val lecteur: String) : Commande
        data class Pause(override val lecteur: String) : Commande
        data class Bascule(override val lecteur: String) : Commande
        data class Suivant(override val lecteur: String) : Commande
        data class Precedent(override val lecteur: String) : Commande
        /** Déplacement relatif, en secondes (+10 par défaut). */
        data class Deplacer(override val lecteur: String, val secondes: Double) : Commande
        /** Volume 0-100 absolu, ou relatif (« +5 », « -10 ») au volume courant. */
        data class Volume(override val lecteur: String, val valeur: Double, val relatif: Boolean) : Commande
    }

    private val ALIAS = mapOf(
        "lecture" to "play", "joue" to "play", "reprendre" to "play", "pause" to "pause",
        "playpause" to "toggle", "play-pause" to "toggle", "basculer" to "toggle",
        "suivant" to "next", "precedent" to "prev", "précédent" to "prev", "previous" to "prev",
        "avancer" to "seek", "position" to "seek", "vol" to "volume",
    )

    private fun nombre(v: JsonPrimitive?): Double? {
        if (v == null || v is JsonNull) return null
        if (!v.isString) return if (v.booleanOrNull != null) null else v.doubleOrNull
        return v.content.trim().replace(',', '.').trimEnd('s', '%').toDoubleOrNull()
    }

    /**
     * L'événement `audio` `{"action": "control", device, player, command, value}` s'il est pour
     * [moi], sinon null (autre appareil, autre action, commande inconnue ou valeur invalide).
     */
    fun lireCommande(d: JsonObject, moi: String): Commande? {
        fun t(cle: String) = (d[cle] as? JsonPrimitive)?.takeIf { it !is JsonNull }?.contentOrNull.orEmpty()
        if (t("action") != "control" || t("device") != moi) return null
        val lecteur = t("player").takeIf { ID.matches(it) } ?: return null
        val brut = t("command").trim().lowercase()
        val valeur = d["value"] as? JsonPrimitive
        return when (ALIAS[brut] ?: brut) {
            "play" -> Commande.Lecture(lecteur)
            "pause" -> Commande.Pause(lecteur)
            "toggle" -> Commande.Bascule(lecteur)
            "next" -> Commande.Suivant(lecteur)
            "prev" -> Commande.Precedent(lecteur)
            "seek" -> {
                val s = if (valeur == null || valeur is JsonNull || (valeur.isString && valeur.content.isBlank())) DEPLACEMENT_DEFAUT_S
                else nombre(valeur) ?: return null
                if (kotlin.math.abs(s) > DEPLACEMENT_MAX_S) null else Commande.Deplacer(lecteur, s)
            }
            "volume" -> {
                val n = nombre(valeur) ?: return null
                val relatif = valeur != null && valeur.isString && valeur.content.trim().take(1).let { it == "+" || it == "-" }
                Commande.Volume(lecteur, n, relatif)
            }
            else -> null
        }
    }

    /** Position visée (ms) d'un déplacement relatif, bornée au morceau. */
    fun positionVisee(positionMs: Long, secondes: Double, dureeMs: Long?): Long {
        var p = positionMs + (secondes * 1000).roundToLong()
        if (dureeMs != null && dureeMs > 0) p = p.coerceAtMost(dureeMs)
        return p.coerceAtLeast(0)
    }

    /** Volume 0-100 visé : absolu, ou relatif au volume courant (null : inconnu, rien à faire). */
    fun volumeVise(c: Commande.Volume, actuel: Int?): Int? {
        val n = if (c.relatif) (actuel ?: return null) + c.valeur else c.valeur
        return n.coerceIn(0.0, 100.0).roundToInt()
    }

    /** Pourcentage → cran de volume du lecteur (0..[max]). */
    fun cran(pourcent: Int, max: Int): Int =
        if (max <= 0) 0 else (pourcent.coerceIn(0, 100) * max / 100.0).roundToInt().coerceIn(0, max)

    /**
     * Ce qu'il faut demander à `MediaController.TransportControls` : la commande, ramenée à une
     * action simple selon l'état de la session (bascule → lecture ou pause).
     */
    enum class Action { LECTURE, PAUSE, SUIVANT, PRECEDENT, DEPLACER, VOLUME }

    fun action(c: Commande, etat: Int?): Action = when (c) {
        is Commande.Lecture -> Action.LECTURE
        is Commande.Pause -> Action.PAUSE
        is Commande.Bascule -> if (statut(etat) == "Playing") Action.PAUSE else Action.LECTURE
        is Commande.Suivant -> Action.SUIVANT
        is Commande.Precedent -> Action.PRECEDENT
        is Commande.Deplacer -> Action.DEPLACER
        is Commande.Volume -> Action.VOLUME
    }
}
