package com.mawena.ccs.logique

import java.util.Locale
import kotlin.math.floor
import kotlin.math.roundToInt

/** Textes et calculs sans Android, partagés par les écrans (mêmes mots que la version web). */
object Format {
    /** « à l'instant », « il y a 5 min », « il y a 3 h », « hier », « il y a 4 j » (`ago` de `dom.js`). */
    fun ilYA(ts: Double?, maintenant: Double = System.currentTimeMillis() / 1000.0): String {
        if (ts == null || ts <= 0) return ""
        val s = (maintenant - ts).coerceAtLeast(0.0)
        return when {
            s < 60 -> "à l'instant"
            s < 3600 -> "il y a ${floor(s / 60).toInt()} min"
            s < 86400 -> "il y a ${floor(s / 3600).toInt()} h"
            else -> floor(s / 86400).toInt().let { if (it == 1) "hier" else "il y a $it j" }
        }
    }

    /** 1 234 567 → « 1.2 M » (`fmt` de `analysis.js`). */
    fun nombreCourt(n: Double): String = when {
        n >= 1e9 -> String.format(Locale.ROOT, "%.1f G", n / 1e9)
        n >= 1e6 -> String.format(Locale.ROOT, "%.1f M", n / 1e6)
        n >= 1e3 -> "${(n / 1e3).roundToInt()} k"
        else -> n.roundToInt().toString()
    }

    /** Dernier élément d'un chemin : `/home/x/Work/ccs` → `ccs`. */
    fun base(chemin: String?): String {
        if (chemin.isNullOrEmpty()) return ""
        return chemin.split('/').lastOrNull { it.isNotEmpty() } ?: chemin
    }

    /** `/home/x/Work/ccs` → `~/Work/ccs` quand `home` vaut `/home/x`. */
    fun court(chemin: String, home: String): String =
        if (home.isNotEmpty() && chemin.startsWith("$home/")) "~" + chemin.substring(home.length) else chemin

    /** Pourcentage arrondi et borné d'une jauge. */
    fun pourcent(p: Double): Int = p.roundToInt().coerceIn(0, 100)

    /** Lignes d'un graphique en barres : les 8 plus grosses, avec leur part du total (0..100). */
    fun barres(donnees: Map<String, Double>, total: Double, max: Int = 8): List<Triple<String, Double, Double>> =
        donnees.entries.sortedByDescending { it.value }.take(max)
            .map { Triple(it.key, it.value, if (total > 0) 100 * it.value / total else 0.0) }

    /** « utilisateur » / « assistant » (ou en anglais) → `Role`, null pour les outils et notes. */
    fun role(r: String): Role? = when (r.lowercase()) {
        "utilisateur", "user" -> Role.Toi
        "assistant" -> Role.Claude
        else -> null
    }

    enum class Role(val libelle: String) { Toi("Toi"), Claude("Claude") }
}

/** État d'un chat du pont, dit comme dans « En cours » de la version web. */
enum class EtatChat(val libelle: String, val ton: Ton) {
    Occupe("Claude travaille", Ton.Occupe),
    Permission("attend ta réponse", Ton.Attente),
    Pret("prêt", Ton.Pret),
    Demarre("démarre", Ton.Occupe),
    Veille("en veille", Ton.Arret),
    Arrete("arrêté", Ton.Arret);

    enum class Ton { Occupe, Attente, Pret, Arret }

    companion object {
        fun de(etat: String): EtatChat = when (etat) {
            "busy" -> Occupe
            "permission" -> Permission
            "idle" -> Pret
            "starting" -> Demarre
            "suspended" -> Veille
            else -> Arrete
        }
    }
}

/**
 * Dossiers proposés par « Nouvelle session » : récents, puis projets connus, puis dépôts git,
 * sans doublon, filtrés par le texte tapé (chemin complet ou court en `~`).
 */
data class DossierPropose(val chemin: String, val etiquette: String)

fun dossiersProposes(
    recents: List<String>,
    connus: List<String>,
    depots: List<String>,
    saisie: String,
    home: String,
): List<DossierPropose> {
    val vus = HashSet<String>()
    val tous = buildList {
        for ((liste, etiquette) in listOf(recents to "récent", connus to "projet", depots to "git")) {
            for (c in liste) if (vus.add(c)) add(DossierPropose(c, etiquette))
        }
    }
    val q = saisie.trim().lowercase()
    if (q.isEmpty()) return tous
    val developpe = if (q.startsWith("~")) home.lowercase() + q.substring(1) else q
    return tous.filter {
        it.chemin.lowercase().contains(developpe) || Format.court(it.chemin, home).lowercase().contains(q)
    }
}

/** Modèles et droits de « Nouvelle session » (`sessions-new.js`). */
object ChoixSession {
    val MODELES = listOf("" to "Par défaut", "opus" to "Opus", "sonnet" to "Sonnet", "haiku" to "Haiku", "fable" to "Fable")
    val DROITS = listOf(
        "manual" to "Demander", "acceptEdits" to "Modifications acceptées", "plan" to "Plan",
        "bypassPermissions" to "Tout autoriser",
    )
}

/** Périodes de l'analyse (`analysis.js`). */
val PERIODES = listOf(1 to "24 heures", 7 to "7 jours", 30 to "30 jours", 90 to "90 jours")
