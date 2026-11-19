package com.mawena.ccs.logique

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull

/** Modifications de Claude (Edit, MultiEdit, Write) en diff par lignes (`web/chat-diff.js`). */
object Diff {
    enum class Genre { Ajout, Retrait, Contexte, Morceau }

    data class Ligne(val genre: Genre, val texte: String)

    /** Diff d'un outil de modification : fichier et lignes. */
    data class Fichier(val chemin: String, val lignes: List<Ligne>) {
        val ajouts: Int get() = lignes.count { it.genre == Genre.Ajout }
        val retraits: Int get() = lignes.count { it.genre == Genre.Retrait }
    }

    private const val LCS_MAX = 90_000      // au-delà (lignes × lignes) : tout retiré puis tout ajouté

    private fun lignes(t: String?): List<String> {
        if (t.isNullOrEmpty()) return emptyList()
        val l = t.split("\n").toMutableList()
        if (l.last().isEmpty()) l.removeAt(l.size - 1)
        return l
    }

    /** Lignes communes au début et à la fin en contexte ; le milieu par plus longue sous-suite commune. */
    fun parLignes(avant: String?, apres: String?): List<Ligne> {
        val a = lignes(avant)
        val b = lignes(apres)
        var tete = 0
        while (tete < a.size && tete < b.size && a[tete] == b[tete]) tete++
        var queue = 0
        while (queue < a.size - tete && queue < b.size - tete && a[a.size - 1 - queue] == b[b.size - 1 - queue]) queue++
        val ma = a.subList(tete, a.size - queue)
        val mb = b.subList(tete, b.size - queue)
        val out = ArrayList<Ligne>()
        a.subList(0, tete).forEach { out.add(Ligne(Genre.Contexte, it)) }
        if (ma.size.toLong() * mb.size > LCS_MAX) {
            ma.forEach { out.add(Ligne(Genre.Retrait, it)) }
            mb.forEach { out.add(Ligne(Genre.Ajout, it)) }
        } else {
            val n = ma.size
            val m = mb.size
            val dp = Array(n + 1) { IntArray(m + 1) }
            for (i in n - 1 downTo 0) for (j in m - 1 downTo 0) {
                dp[i][j] = if (ma[i] == mb[j]) dp[i + 1][j + 1] + 1 else maxOf(dp[i + 1][j], dp[i][j + 1])
            }
            var i = 0
            var j = 0
            while (i < n && j < m) {
                when {
                    ma[i] == mb[j] -> { out.add(Ligne(Genre.Contexte, ma[i])); i++; j++ }
                    dp[i + 1][j] >= dp[i][j + 1] -> out.add(Ligne(Genre.Retrait, ma[i++]))
                    else -> out.add(Ligne(Genre.Ajout, mb[j++]))
                }
            }
            while (i < n) out.add(Ligne(Genre.Retrait, ma[i++]))
            while (j < m) out.add(Ligne(Genre.Ajout, mb[j++]))
        }
        a.subList(a.size - queue, a.size).forEach { out.add(Ligne(Genre.Contexte, it)) }
        return out
    }

    private fun JsonObject.texte(cle: String): String? = (this[cle] as? JsonPrimitive)?.contentOrNull

    /** Diff d'un outil qui modifie un fichier ; null pour les autres outils. */
    fun deOutil(nom: String, entree: JsonObject?): Fichier? {
        val e = entree ?: return null
        val chemin = e.texte("file_path").orEmpty()
        if (chemin.isEmpty()) return null
        return when (nom) {
            "Edit" -> Fichier(chemin, parLignes(e.texte("old_string"), e.texte("new_string")))
            "MultiEdit" -> {
                val edits = e["edits"] as? JsonArray ?: return null
                val tout = ArrayList<Ligne>()
                edits.forEachIndexed { k, x ->
                    val o = x as? JsonObject
                    if (k > 0) tout.add(Ligne(Genre.Morceau, "modification ${k + 1}"))
                    tout.addAll(parLignes(o?.texte("old_string"), o?.texte("new_string")))
                }
                Fichier(chemin, tout)
            }
            "Write" -> Fichier(chemin, parLignes("", e.texte("content")))
            else -> null
        }
    }
}
