package com.mawena.ccs.ui

import android.net.Uri
import androidx.navigation.NavBackStackEntry

/** Routes de navigation hors onglets : Analyse, écran Projet et écran Chat. */
object Routes {
    const val ANALYSE = "analyse"
    const val PROJET = "projet?cwd={cwd}"
    const val CHAT = "chat?cwd={cwd}&sid={sid}&chemin={chemin}&titre={titre}&chat={chat}&envoi={envoi}&jeton={jeton}"
    const val REGLAGES = "reglages"
    const val TERMINAUX = "terminaux"
    const val TERMINAL = "terminal?id={id}"
    const val JARVIS = "jarvis"

    const val FICHIER = "fichier?chemin={chemin}&ligne={ligne}&appareil={appareil}"
    const val FICHIERS_PROJET = "fichiers-projet?cwd={cwd}"
    const val GIT_PROJET = "git-projet?cwd={cwd}"
    const val COMMIT = "git-commit?cwd={cwd}&id={id}"

    fun projet(cwd: String) = "projet?cwd=${Uri.encode(cwd)}"
    /** `appareil` : appareil de l'onglet Fichiers ("" : le serveur) ; null : connexion principale. */
    fun fichier(chemin: String, ligne: Int? = null, appareil: String? = null) =
        "fichier?chemin=${Uri.encode(chemin)}&ligne=${ligne ?: ""}&appareil=${Uri.encode(com.mawena.ccs.logique.Appareils.versRoute(appareil))}"
    fun fichiersProjet(cwd: String) = "fichiers-projet?cwd=${Uri.encode(cwd)}"
    fun gitProjet(cwd: String) = "git-projet?cwd=${Uri.encode(cwd)}"
    fun terminal(id: String) = "terminal?id=${Uri.encode(id)}"
    fun commit(cwd: String, id: String) = "git-commit?cwd=${Uri.encode(cwd)}&id=${Uri.encode(id)}"

    /** Onglet à allumer pour une route (Projet et Chat sont sous Sessions, Analyse sous Accueil). */
    fun onglet(route: String?): String? = when {
        route == null -> null
        route.startsWith("projet") || route.startsWith("chat") -> Onglet.Sessions.route
        route.startsWith("fichier") -> Onglet.Fichiers.route
        route.startsWith("git") -> Onglet.Git.route
        route == ANALYSE -> Onglet.Accueil.route
        route == REGLAGES || route == JARVIS || route.startsWith("terminal") -> Onglet.Plus.route
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
    /** Texte à envoyer une fois le chat ouvert (nouveau chat pour une tâche de la feuille de route). */
    val aEnvoyer: String? = null,
    /** Identifie cet envoi prévu (il ne part qu'une fois). */
    val jeton: String? = null,
) {
    fun route(): String = "chat?cwd=${e(cwd)}&sid=${e(sessionId)}&chemin=${e(chemin)}&titre=${e(titre)}&chat=${e(chatId)}" +
        "&envoi=${e(aEnvoyer)}&jeton=${e(jeton)}"

    private fun e(t: String?) = Uri.encode(t.orEmpty())

    companion object {
        fun de(entree: NavBackStackEntry): DestChat {
            val a = entree.arguments
            fun lire(cle: String) = a?.getString(cle)?.takeIf { it.isNotEmpty() }
            return DestChat(lire("cwd").orEmpty(), lire("sid"), lire("chemin"), lire("titre"), lire("chat"), lire("envoi"), lire("jeton"))
        }

        /** Nouveau chat dans `cwd` qui envoie `texte` dès qu'il est ouvert. */
        fun nouveauAvec(cwd: String, texte: String): DestChat {
            return DestChat(cwd, titre = com.mawena.ccs.logique.Format.base(cwd), aEnvoyer = texte, jeton = java.util.UUID.randomUUID().toString())
        }
    }
}
