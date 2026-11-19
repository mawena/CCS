package com.mawena.ccs.logique

import com.mawena.ccs.reseau.FichierChange
import com.mawena.ccs.reseau.PhaseFeuille
import com.mawena.ccs.reseau.PlanRetour
import com.mawena.ccs.reseau.TacheFond

/** Feuille de route (`web/roadmap.js`) : progression des phases, phase ouverte au départ. */
object FeuilleRoute {
    data class Progression(val faites: Int, val total: Int) {
        val fraction: Float get() = if (total == 0) 0f else faites.toFloat() / total
        override fun toString() = "$faites/$total"
    }

    fun progression(p: PhaseFeuille) = Progression(p.tasks.count { it.done }, p.tasks.size)

    /** Phases ouvertes d'emblée : celles qui ont encore une case vide (comme au bureau). */
    fun ouvertes(phases: List<PhaseFeuille>): Set<Int> =
        phases.indices.filter { i -> phases[i].tasks.any { !it.done } }.toSet()

    /** Première phase non finie (à montrer), ou null. */
    fun enCours(phases: List<PhaseFeuille>): Int? = phases.indexOfFirst { p -> p.tasks.any { !it.done } }.takeIf { it >= 0 }

    /** Indentation d'une sous-tâche (0 à 3 niveaux, comme le web). */
    fun niveau(profondeur: Int) = profondeur.coerceIn(0, 3)
}

/** Tâches de fond (`web/pages-tasks.js`) : états, filtres, textes. */
object TachesFond {
    val ETATS = mapOf(
        "queued" to "En attente", "running" to "En cours", "waiting" to "À reprendre (limite atteinte)",
        "done" to "Finie", "failed" to "Échouée", "cancelled" to "Annulée",
    )
    val ACTIVES = setOf("queued", "running", "waiting")

    data class Filtre(val cle: String, val libelle: String, val etats: Set<String>)

    val FILTRES = listOf(
        Filtre("actives", "À venir", ACTIVES),
        Filtre("done", "Finies", setOf("done")),
        Filtre("failed", "Échouées", setOf("failed")),
        Filtre("cancelled", "Annulées", setOf("cancelled")),
    )

    /** Droits d'une tâche : (valeur, libellé, explication). */
    val DROITS = listOf(
        Triple("lecture", "Lecture seule", "Claude lit et analyse ; tout ce qui demande une permission est refusé."),
        Triple("modifications", "Modifications des fichiers", "Claude modifie les fichiers du dossier sans demander ; le reste est refusé."),
        Triple("tout", "Tout (aucune vérification)", "Attention : Claude peut tout faire sans rien demander, y compris supprimer."),
    )
    val MODELES = listOf("" to "Modèle par défaut", "opus" to "Opus", "sonnet" to "Sonnet", "haiku" to "Haiku", "fable" to "Fable")
    val QUAND = listOf("quota" to "Dès qu'il y a du quota", "nuit" to "Cette nuit (meilleur créneau)", "heure" to "À une heure précise…")

    fun active(t: TacheFond) = t.state in ACTIVES

    fun etat(t: TacheFond) = ETATS[t.state] ?: t.state

    fun quand(t: TacheFond): String = when (t.quand) {
        "quota" -> "dès qu'il y a du quota"
        "nuit" -> "cette nuit"
        else -> "à ${t.quand}"
    }

    /** `~/…` à la place du dossier personnel (`shortPath` du web). */
    fun cheminCourt(chemin: String): String = chemin.replace(Regex("^/home/[^/]+"), "~")

    fun sousTitre(t: TacheFond, maintenant: Double = System.currentTimeMillis() / 1000.0): String {
        val parties = mutableListOf(etat(t))
        when {
            t.state == "queued" || t.state == "waiting" -> parties.add(t.note.ifEmpty { quand(t) })
            !t.error.isNullOrEmpty() -> parties.add(t.error)
            t.finished != null -> parties.add(Format.ilYA(t.finished, maintenant))
        }
        parties.add(cheminCourt(t.cwd))
        return parties.filter { it.isNotEmpty() }.joinToString(" · ")
    }

    fun titre(t: TacheFond): String = t.message.lineSequence().firstOrNull().orEmpty().take(120)

    fun droits(valeur: String) = DROITS.firstOrNull { it.first == valeur }?.second ?: valeur

    fun nombre(taches: List<TacheFond>, f: Filtre) = taches.count { it.state in f.etats }

    /** Filtre montré à l'ouverture : le premier qui a des tâches, sinon « À venir ». */
    fun filtreInitial(taches: List<TacheFond>): String =
        FILTRES.firstOrNull { f -> taches.any { it.state in f.etats } }?.cle ?: "actives"

    /** Tâches d'un filtre, les plus récentes d'abord. */
    fun filtrer(taches: List<TacheFond>, cle: String): List<TacheFond> {
        val f = FILTRES.firstOrNull { it.cle == cle } ?: FILTRES[0]
        return taches.filter { it.state in f.etats }.asReversed()
    }

    /** `~/x` → `/home/moi/x` ; vide si rien n'est saisi. */
    fun dossier(saisi: String, home: String): String {
        val s = saisi.trim()
        return if (s.startsWith("~") && home.isNotEmpty()) home + s.substring(1) else s
    }

    private val HEURE = Regex("^([01]?\\d|2[0-3]):([0-5]\\d)$")

    /** Erreur du formulaire « Nouvelle tâche », ou null s'il peut partir. */
    fun verifier(dossier: String, message: String, quand: String, heure: String): String? = when {
        dossier.isBlank() -> "Indique le dossier du projet."
        message.isBlank() -> "Écris ce que Claude doit faire."
        quand == "heure" && !HEURE.matches(heure.trim()) -> "Choisis l'heure (HH:MM)."
        else -> null
    }

    /** Valeur de `when` envoyée à `tasks.add`. */
    fun quandEnvoye(quand: String, heure: String): String = if (quand == "heure") heure.trim().padStart(5, '0') else quand
}

/** Travail du chat (`web/chat-changes.js`) : genres de changement, diff unifié, retour arrière. */
object ChangementsChat {
    val GENRES = mapOf("created" to "créé", "deleted" to "supprimé", "modified" to "modifié")

    fun genre(f: FichierChange) = GENRES[f.kind] ?: f.kind

    private val ENTETE = Regex("^@@ -(\\d+)(?:,\\d+)? \\+(\\d+)(?:,\\d+)? @@.*")

    /** Diff unifié (`--- a`, `+++ b`, `@@ -1,3 +1,4 @@`) en lignes numérotées du chat. */
    fun lignes(diff: String): List<Diff.Ligne> {
        val out = ArrayList<Diff.Ligne>()
        var ancien = 0
        var nouveau = 0
        var dansMorceau = false
        for (l in diff.split("\n")) {
            val m = ENTETE.matchEntire(l)
            when {
                m != null -> {
                    ancien = m.groupValues[1].toInt()
                    nouveau = m.groupValues[2].toInt()
                    dansMorceau = true
                    out.add(Diff.Ligne(Diff.Genre.Morceau, l))
                }
                !dansMorceau -> Unit                                     // en-têtes ---/+++
                l.startsWith("+") -> out.add(Diff.Ligne(Diff.Genre.Ajout, l.substring(1), null, nouveau++))
                l.startsWith("-") -> out.add(Diff.Ligne(Diff.Genre.Retrait, l.substring(1), ancien++, null))
                l.startsWith(" ") -> out.add(Diff.Ligne(Diff.Genre.Contexte, l.substring(1), ancien++, nouveau++))
                l.startsWith("\\") -> Unit                               // « \ No newline at end of file »
                l.isEmpty() -> Unit
                else -> out.add(Diff.Ligne(Diff.Genre.Contexte, l, ancien++, nouveau++))
            }
        }
        return out
    }

    /** Chemin relatif au projet quand il y est. */
    fun relatif(chemin: String, cwd: String) = if (chemin.startsWith("$cwd/")) chemin.substring(cwd.length + 1) else chemin

    /** Texte de la confirmation du retour en arrière (`rewindBody` du web). */
    fun texteRetour(plan: PlanRetour, cwd: String): String {
        val liste = plan.steps.joinToString("\n") { s ->
            relatif(s.path, cwd) + (if (s.deleted) " (supprimé)" else "") + (if (s.modifieParToi) " (modifié depuis par toi ?)" else "")
        }
        val reste = if (plan.skipped.isEmpty()) "" else "\n\nLaissés tels quels (hors des dossiers permis) :\n" + plan.skipped.joinToString("\n")
        return "$liste$reste\n\nC'est définitif."
    }

    fun titreRetour(plan: PlanRetour): String {
        val n = plan.steps.size
        return "Revenir avant ce message ? ($n fichier${if (n > 1) "s" else ""})"
    }

    fun texteAnnulation(f: FichierChange): String =
        (if (f.kind == "created") "Le fichier sera supprimé (Claude l'a créé)." else "Le fichier reviendra à son état d'avant la session.") +
            " C'est définitif."
}
