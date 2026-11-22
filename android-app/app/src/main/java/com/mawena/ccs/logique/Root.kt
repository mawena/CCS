package com.mawena.ccs.logique

import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.longOrNull

/**
 * Mot de passe root demandé aux appareils (phase 34), sans Android : ce que le pont envoie
 * (`root.ask`, `root.resolved`, `root.used`, `root.forgotten`, réponse de `root.status`) et ce que
 * l'appli en montre (fenêtre de la demande, « root gardé, X min »).
 *
 * Le mot de passe n'apparaît jamais ici : il va du champ de saisie à `root.answer`, rien de plus.
 *
 * Les heures du pont (`expires_at`, secondes depuis 1970) viennent d'une autre horloge que celle du
 * téléphone : les échéances sont recalculées sur l'horloge du téléphone, bornées par les durées du
 * gardien (5 min pour une demande, 1 h pour le mot de passe gardé).
 */
data class DemandeRoot(
    val id: String,
    val machine: String,
    val commande: String,
    /** Échéance sur l'horloge du téléphone (ms). */
    val echeanceMs: Long,
    val essais: Int,
    /** Message du pont après un mauvais mot de passe (« Mot de passe refusé (essai 1 sur 3). »). */
    val erreur: String? = null,
)

/** Mot de passe gardé en mémoire par le pont, jusqu'à `finMs` (horloge du téléphone). */
data class GardeRoot(val machine: String, val finMs: Long)

/** Commande lancée avec le mot de passe gardé (avis discret). */
data class UsageRoot(val machine: String, val commande: String)

data class EtatRoot(
    val demande: DemandeRoot? = null,
    val garde: GardeRoot? = null,
    /** Réponse envoyée, en attente du pont (vérification par sudo, jusqu'à 30 s). */
    val envoi: Boolean = false,
    /** Erreur locale de la dernière réponse (réseau, autre appareil…), sinon celle du pont. */
    val avis: String? = null,
)

object Root {
    const val DEMANDE_MS = 5 * 60_000L
    const val GARDE_MS = 60 * 60_000L
    /** Marge d'horloge admise entre le pont et le téléphone. */
    private const val MARGE_MS = 30_000L

    private fun JsonObject.texte(cle: String) = (this[cle] as? JsonPrimitive)?.contentOrNull

    /**
     * Échéance locale d'une heure du pont : si l'écart avec l'horloge du téléphone n'est pas
     * plausible (horloges décalées), on retombe sur `maintenant + defautMs`.
     */
    fun echeance(expiresAt: Double?, maintenantMs: Long, defautMs: Long): Long {
        val delta = expiresAt?.let { (it * 1000).toLong() - maintenantMs }
        return if (delta == null || delta <= 0 || delta > defautMs + MARGE_MS) maintenantMs + defautMs else maintenantMs + delta
    }

    /** Lit un `root.ask` (ou le `pending` de `root.status`) ; null s'il manque l'identifiant. */
    fun lireDemande(d: JsonObject?, maintenantMs: Long): DemandeRoot? {
        if (d == null) return null
        val id = d.texte("id")?.takeIf { it.isNotBlank() } ?: return null
        return DemandeRoot(
            id = id,
            machine = d.texte("machine")?.takeIf { it.isNotBlank() } ?: "Une machine",
            commande = d.texte("command").orEmpty(),
            echeanceMs = echeance((d["expires_at"] as? JsonPrimitive)?.doubleOrNull, maintenantMs, DEMANDE_MS),
            essais = (d["tries_left"] as? JsonPrimitive)?.intOrNull ?: 0,
            erreur = d.texte("error")?.takeIf { it.isNotBlank() },
        )
    }

    fun lireUsage(d: JsonObject): UsageRoot =
        UsageRoot(d.texte("machine")?.takeIf { it.isNotBlank() } ?: "Une machine", d.texte("command").orEmpty())

    /** Nouvelle demande (ou la même, revenue avec `error` après un mauvais mot de passe). */
    fun apresDemande(e: EtatRoot, d: JsonObject, maintenantMs: Long): EtatRoot {
        val dem = lireDemande(d, maintenantMs) ?: return e
        return e.copy(demande = dem, envoi = false, avis = null)
    }

    /** `root.resolved` : la fenêtre de cette demande se ferme (réponse ici ou ailleurs). */
    fun apresReglee(e: EtatRoot, d: JsonObject): EtatRoot {
        val id = d.texte("id")
        if (e.demande == null || e.demande.id != id) return e
        return e.copy(demande = null, envoi = false, avis = null)
    }

    /** `root.forgotten` : mot de passe effacé (et demande abandonnée si `forget`). */
    fun apresOubli(e: EtatRoot, d: JsonObject): EtatRoot {
        val raison = d.texte("reason")
        val demande = if (raison == "forget" || raison == "stop") null else e.demande
        return e.copy(garde = null, demande = demande, envoi = if (demande == null) false else e.envoi)
    }

    /** Réponse de `root.status` : garde et demande en cours. */
    fun apresStatut(e: EtatRoot, r: JsonObject, maintenantMs: Long): EtatRoot {
        val garde = if ((r["kept"] as? JsonPrimitive)?.booleanOrNull == true) {
            val restant = (r["remaining"] as? JsonPrimitive)?.longOrNull
            val fin = if (restant != null && restant > 0) maintenantMs + restant.coerceAtMost(GARDE_MS / 1000) * 1000
            else echeance((r["expires_at"] as? JsonPrimitive)?.doubleOrNull, maintenantMs, GARDE_MS)
            GardeRoot(r.texte("machine")?.takeIf { it.isNotBlank() } ?: "", fin)
        } else null
        val pending = r["pending"] as? JsonObject
        val demande = lireDemande(pending, maintenantMs)
        // une réponse en cours pour la même demande reste affichée telle quelle
        val garderEnvoi = demande != null && e.envoi && e.demande?.id == demande.id
        return e.copy(
            garde = garde,
            demande = if (garderEnvoi) e.demande else demande,
            envoi = garderEnvoi,
            avis = if (garderEnvoi || demande?.id == e.demande?.id) e.avis else null,
        )
    }

    /** Échéances passées : demande et garde retirées. */
    fun apresTemps(e: EtatRoot, maintenantMs: Long): EtatRoot {
        val demande = e.demande?.takeIf { maintenantMs < it.echeanceMs }
        val garde = e.garde?.takeIf { maintenantMs < it.finMs }
        if (demande === e.demande && garde === e.garde) return e
        return e.copy(demande = demande, garde = garde, envoi = if (demande == null) false else e.envoi,
            avis = if (demande == null) null else e.avis)
    }

    /** Réponse envoyée à la demande `id`. */
    fun envoiEnCours(e: EtatRoot, id: String): EtatRoot =
        if (e.demande?.id == id) e.copy(envoi = true, avis = null) else e

    /**
     * Résultat de `root.answer` : `ok` ferme la fenêtre (le `root.resolved` suit) ; un refus garde
     * la fenêtre avec le message (le `root.ask` de la même demande apporte les essais restants ;
     * plus d'essai : `root.resolved` la ferme).
     */
    fun apresReponse(e: EtatRoot, id: String, ok: Boolean, erreur: String?): EtatRoot {
        if (e.demande?.id != id) return e
        if (ok) return e.copy(demande = null, envoi = false, avis = null)
        return e.copy(envoi = false, avis = erreur ?: "Mot de passe refusé.")
    }

    /** Message d'une erreur RPC de `root.answer`. */
    fun texteErreur(code: String?, message: String?): String = when (code) {
        "introuvable" -> "Demande expirée ou déjà réglée."
        "conflit" -> "Un autre appareil a répondu : vérification en cours."
        "invalide" -> "Réponse invalide."
        "delai" -> "Pas de réponse du serveur."
        else -> message?.takeIf { it.isNotBlank() } ?: "Réponse non envoyée."
    }

    /** L'erreur `introuvable` veut dire que la demande n'existe plus : la fenêtre se ferme. */
    fun demandePerdue(code: String?) = code == "introuvable"

    /** Minutes restantes, arrondies au-dessus (« 1 min » jusqu'à la fin). */
    fun minutes(restantMs: Long): Long = if (restantMs <= 0) 0 else (restantMs + 59_999) / 60_000

    fun texteGarde(g: GardeRoot, maintenantMs: Long): String {
        val m = minutes(g.finMs - maintenantMs)
        return if (g.machine.isBlank()) "Root gardé, $m min" else "Root gardé sur ${g.machine}, $m min"
    }

    fun texteEssais(n: Int): String = when {
        n <= 0 -> ""
        n == 1 -> "Dernier essai."
        else -> "$n essais restants."
    }

    fun texteUsage(u: UsageRoot): String =
        if (u.commande.isBlank()) "${u.machine} a lancé une commande root" else "${u.machine} a lancé en root : ${u.commande}"
}
