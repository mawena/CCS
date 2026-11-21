package com.mawena.ccs.logique

import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.longOrNull
import java.math.BigDecimal
import java.math.RoundingMode

/**
 * Usage d'un tour (`usage` de `TurnResult`, `ccs_app/token_use.turn_usage`) : tokens lus dans le
 * cache, écrits dans le cache, frais, produits ; coût ; taille du contexte à la fin du tour.
 */
data class UsageTour(
    val entree: Long = 0,
    val cacheLu: Long = 0,
    val cacheEcrit: Long = 0,
    val produits: Long = 0,
    val coutUsd: Double = 0.0,
    val contexte: Long = 0,
    val ttlCacheS: Long = 0,
    val modele: String = "",
) {
    companion object {
        /** Usage depuis le JSON du pont ; null s'il est absent, vide ou sans aucun token. */
        fun lire(e: JsonElement?): UsageTour? {
            val o = e as? JsonObject ?: return null
            fun n(k: String) = (o[k] as? JsonPrimitive)?.let { it.longOrNull ?: it.doubleOrNull?.toLong() }?.coerceAtLeast(0) ?: 0L
            val u = UsageTour(
                n("input"), n("cache_read"), n("cache_write"), n("output"),
                (o["cost_usd"] as? JsonPrimitive)?.doubleOrNull ?: 0.0,
                n("context"), n("cache_ttl_s"),
                (o["model"] as? JsonPrimitive)?.takeIf { it.isString }?.contentOrNull.orEmpty(),
            )
            return u.takeIf { it.entree + it.cacheLu + it.cacheEcrit + it.produits + it.contexte > 0 }
        }
    }
}

/** Niveau du contexte par rapport au seuil de l'alerte : vert sous la moitié, orange jusqu'au seuil, rouge au-delà. */
enum class NiveauContexte { Vert, Orange, Rouge }

/** Consommation de tokens (`ccs_app/token_use.py`) : mêmes textes qu'au bureau et sur le web. */
object Consommation {
    /** Défaut de `context_alert.threshold_tokens` (`ccs_app/context_alert.py`). */
    const val SEUIL_DEFAUT = 150_000L

    /** Arrondi comme Python (`round`, `format(.., ".1f")`) : valeur binaire exacte, demi au pair. */
    private fun arrondi(x: Double, chiffres: Int): BigDecimal = BigDecimal(x).setScale(chiffres, RoundingMode.HALF_EVEN)

    /** 12 345 → « 12 k », 1 234 567 → « 1,2 M », 850 → « 850 » (`fmt_tokens`). */
    fun jetons(valeur: Long): String {
        val v = valeur.coerceAtLeast(0)
        return when {
            v >= 1_000_000 -> arrondi(v / 1e6, 1).toPlainString().replace('.', ',') + " M"
            v >= 1000 -> arrondi(v / 1000.0, 0).toPlainString() + " k"
            else -> v.toString()
        }
    }

    /** 0,0365 → « 0,04 $ ». */
    fun dollars(usd: Double): String = arrondi(usd, 2).toPlainString().replace('.', ',') + " $"

    /** Ligne discrète sous une réponse : « 36 k lus · 15 k écrits · 403 produits · 0,04 $ » (`summary`). */
    fun resume(u: UsageTour?): String {
        if (u == null) return ""
        val parts = ArrayList<String>()
        if (u.cacheLu > 0) parts.add("${jetons(u.cacheLu)} lus")
        val ecrits = u.cacheEcrit + u.entree
        if (ecrits > 0) parts.add("${jetons(ecrits)} écrits")
        parts.add("${jetons(u.produits)} produits")
        if (u.coutUsd != 0.0) parts.add(dollars(u.coutUsd))
        return parts.joinToString(" · ")
    }

    /** Seuil à appliquer : celui du réglage s'il est connu et positif, sinon le défaut. */
    fun seuil(reglage: Long?): Long = reglage?.takeIf { it > 0 } ?: SEUIL_DEFAUT

    fun niveau(tokens: Long, seuil: Long = SEUIL_DEFAUT): NiveauContexte {
        val s = if (seuil > 0) seuil else SEUIL_DEFAUT
        return when {
            tokens * 2 < s -> NiveauContexte.Vert
            tokens <= s -> NiveauContexte.Orange
            else -> NiveauContexte.Rouge
        }
    }

    /**
     * Avant d'envoyer `texte` : tokens que le message relira au prix fort (cache expiré, pas de
     * tour depuis), ou null s'il n'y a rien à confirmer. Les commandes `/…` (dont `/compact`) passent.
     */
    fun confirmationCache(texte: String, expire: EvChat.CacheExpire?): Long? {
        if (expire == null || Envoi.estCommandeSlash(texte.trim())) return null
        return expire.contexte
    }

    fun texteConfirmation(tokens: Long): String =
        "Le cache a expiré : ce message relira ${jetons(tokens)} tokens au prix fort."
}
