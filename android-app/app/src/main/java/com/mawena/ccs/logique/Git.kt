package com.mawena.ccs.logique

import com.mawena.ccs.reseau.BrancheGit
import com.mawena.ccs.reseau.DiffGit
import com.mawena.ccs.reseau.EtatGit
import com.mawena.ccs.reseau.FichierGit
import com.mawena.ccs.reseau.MorceauGit
import com.mawena.ccs.reseau.RefGit

/** Ce que l'écran Git tire des réponses de `git.*` (`web/git.js`), sans Android. */
object GitVue {
    private val MARQUES = mapOf(
        "M" to "modifié", "T" to "type changé", "A" to "ajouté", "D" to "supprimé", "R" to "renommé",
        "C" to "copié", "U" to "en conflit", "?" to "non suivi",
    )

    fun marque(lettre: String): String = MARQUES[lettre] ?: lettre

    enum class Cote { Index, Travail }

    data class Groupe(
        val titre: String,
        val fichiers: List<FichierGit>,
        val cote: Cote,
        val verbe: String,
        val methode: String,
        val tout: String,
        val lettre: (FichierGit) -> String,
    )

    fun indexe(f: FichierGit) = f.staged != "." && f.staged != "?"
    fun modifie(f: FichierGit) = f.unstaged != "." && f.unstaged != "?"
    fun nonSuivi(f: FichierGit) = f.staged == "?"

    /** Indexés, Modifiés, Non suivis (groupes vides omis). */
    fun groupes(e: EtatGit): List<Groupe> = listOf(
        Groupe("Indexés", e.files.filter(::indexe), Cote.Index, "Désindexer", "git.unstage", "Tout désindexer") { it.staged },
        Groupe("Modifiés", e.files.filter(::modifie), Cote.Travail, "Indexer", "git.stage", "Tout indexer") { it.unstaged },
        Groupe("Non suivis", e.files.filter(::nonSuivi), Cote.Travail, "Indexer", "git.stage", "Tout indexer") { "?" },
    ).filter { it.fichiers.isNotEmpty() }

    fun cle(cote: Cote, chemin: String) = "${cote.name}:$chemin"

    /** Clés des diffs ouverts qui existent encore après une actualisation. */
    fun clesGardees(ouvertes: Set<String>, e: EtatGit): Set<String> {
        val existent = e.files.flatMap { f ->
            listOfNotNull(if (indexe(f)) cle(Cote.Index, f.path) else null, if (f.unstaged != ".") cle(Cote.Travail, f.path) else null)
        }.toSet()
        return ouvertes.intersect(existent)
    }

    fun peutCommit(e: EtatGit, amend: Boolean) = amend || e.files.any(::indexe)

    /** « origin/main · ↑1 ↓2 », « origin/main · à jour » ou « pas de suivi distant ». */
    fun synchro(b: BrancheGit): String {
        val s = listOfNotNull(if (b.ahead > 0) "↑${b.ahead}" else null, if (b.behind > 0) "↓${b.behind}" else null).joinToString(" ")
        val u = b.upstream ?: return "pas de suivi distant"
        return if (s.isEmpty()) "$u · à jour" else "$u · $s"
    }

    fun textePush(b: BrancheGit): String = when {
        b.upstream == null -> "Le premier push crée la branche sur le dépôt distant."
        b.ahead > 0 -> "${b.ahead} commit(s) partiront vers ${b.upstream}."
        else -> "Rien de nouveau à pousser."
    }

    fun textePull(b: BrancheGit): String = when {
        b.upstream == null -> "Cette branche ne suit aucune branche distante."
        b.behind > 0 -> "${b.behind} commit(s) arriveront de ${b.upstream}."
        else -> "Récupère et intègre les nouveautés de ${b.upstream}."
    }

    /** Un morceau s'indexe seul sauf pour un fichier non suivi, neuf ou supprimé (en entier). */
    fun parMorceau(lettre: String, d: DiffGit) = lettre != "?" && !d.nouveau && !d.deleted

    /** Lignes d'un morceau au format du diff du chat (avec numéros). */
    fun lignes(m: MorceauGit): List<Diff.Ligne> = m.lines.map { l ->
        val g = when (l.kind) { "+" -> Diff.Genre.Ajout; "-" -> Diff.Genre.Retrait; else -> Diff.Genre.Contexte }
        Diff.Ligne(g, l.text, l.ancien, l.nouveau)
    }

    /** Diff entier d'un fichier (en-têtes `@@` en séparateurs), pour le détail d'un commit. */
    fun fichier(d: DiffGit): Diff.Fichier = Diff.Fichier(
        d.path,
        d.hunks.flatMap { listOf(Diff.Ligne(Diff.Genre.Morceau, it.header)) + lignes(it) },
    )

    /** Texte quand un diff n'a rien à montrer, ou null. */
    fun sansDiff(d: DiffGit?): String? = when {
        d == null -> "Pas de différence à montrer."
        d.tropGros -> "Fichier trop gros pour être montré."
        d.binary -> "Fichier binaire : pas de diff."
        d.hunks.isEmpty() -> "Pas de différence à montrer."
        else -> null
    }

    fun etatFichier(d: DiffGit): String = when {
        d.nouveau -> "ajouté"
        d.deleted -> "supprimé"
        d.ancien != null && d.ancien != d.path -> "renommé (${d.ancien})"
        else -> "modifié"
    }

    /** Refs par genre, dans l'ordre : branches locales, distantes, tags. */
    fun refs(refs: List<RefGit>): List<Pair<String, List<RefGit>>> = listOf(
        "Branches" to refs.filter { it.kind == "branch" }.sortedBy { it.name.lowercase() },
        "Branches distantes" to refs.filter { it.kind == "remote" }.sortedBy { it.name.lowercase() },
        "Tags" to refs.filter { it.kind == "tag" }.sortedByDescending { it.name },
    ).filter { it.second.isNotEmpty() }
}
