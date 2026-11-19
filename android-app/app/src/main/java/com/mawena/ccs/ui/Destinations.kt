package com.mawena.ccs.ui

import android.net.Uri
import androidx.navigation.NavBackStackEntry

/** Routes de navigation hors onglets : Analyse, écran Projet et écran Chat. */
object Routes {
    const val ANALYSE = "analyse"
    const val PROJET = "projet?cwd={cwd}"
    const val CHAT = "chat?cwd={cwd}&sid={sid}&chemin={chemin}&titre={titre}&chat={chat}"

    const val FICHIER = "fichier?chemin={chemin}&ligne={ligne}"
    const val FICHIERS_PROJET = "fichiers-projet?cwd={cwd}"
    const val GIT_PROJET = "git-projet?cwd={cwd}"
    const val COMMIT = "git-commit?cwd={cwd}&id={id}"

    fun projet(cwd: String) = "projet?cwd=${Uri.encode(cwd)}"
    fun fichier(chemin: String, ligne: Int? = null) = "fichier?chemin=${Uri.encode(chemin)}&ligne=${ligne ?: ""}"
    fun fichiersProjet(cwd: String) = "fichiers-projet?cwd=${Uri.encode(cwd)}"
    fun gitProjet(cwd: String) = "git-projet?cwd=${Uri.encode(cwd)}"
    fun commit(cwd: String, id: String) = "git-commit?cwd=${Uri.encode(cwd)}&id=${Uri.encode(id)}"

    /** Onglet à allumer pour une route (Projet et Chat sont sous Sessions, Analyse sous Accueil). */
    fun onglet(route: String?): String? = when {
        route == null -> null
        route.startsWith("projet") || route.startsWith("chat") -> Onglet.Sessions.route
        route.startsWith("fichier") -> Onglet.Fichiers.route
        route.startsWith("git") -> Onglet.Git.route
        route == ANALYSE -> Onglet.Accueil.route
        else -> route
    }
}

/** Ce qu'ouvre l'écran Chat : une conversation de l'historique, ou un chat ouvert dans le pont. */
data class DestChat(
    val cwd: String,
    val sessionId: String? = null,
    val chemin: String? = null,
    val titre: String? = null,
    val chatId: String? = null,
) {
    fun route(): String = "chat?cwd=${e(cwd)}&sid=${e(sessionId)}&chemin=${e(chemin)}&titre=${e(titre)}&chat=${e(chatId)}"

    private fun e(t: String?) = Uri.encode(t.orEmpty())

    companion object {
        fun de(entree: NavBackStackEntry): DestChat {
            val a = entree.arguments
            fun lire(cle: String) = a?.getString(cle)?.takeIf { it.isNotEmpty() }
            return DestChat(lire("cwd").orEmpty(), lire("sid"), lire("chemin"), lire("titre"), lire("chat"))
        }
    }
}
