package com.mawena.ccs.donnees

import okhttp3.HttpUrl
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull

/** Adresse du serveur CCS : `https://ccs.mawena.cloud` par défaut, modifiable dans l'appli. */
object Adresse {
    const val PAR_DEFAUT = "https://ccs.mawena.cloud"

    /**
     * `ccs.exemple.fr` -> `https://ccs.exemple.fr`. Rend null si l'adresse n'est pas utilisable
     * (autre schéma que http/https, pas d'hôte, identifiants dans l'adresse). Requête et fragment
     * sont retirés, ainsi que la barre finale : `https://hote/ccs/` -> `https://hote/ccs`.
     */
    fun normaliser(texte: String): String? {
        var t = texte.trim()
        if (t.isEmpty() || t.any { it.isWhitespace() }) return null
        if (!t.contains("://")) t = "https://$t"
        val url = t.toHttpUrlOrNull() ?: return null
        if (url.host.isEmpty() || url.username.isNotEmpty() || url.password.isNotEmpty()) return null
        return url.newBuilder().query(null).fragment(null).build().toString().trimEnd('/')
    }

    /** `base` + chemin de l'API (`api/ws`, `api/health`…), en gardant un éventuel préfixe. */
    fun api(base: String, chemin: String): HttpUrl {
        val url = requireNotNull(normaliser(base)?.toHttpUrlOrNull()) { "adresse invalide : $base" }
        return url.newBuilder().addPathSegments(chemin.trimStart('/')).build()
    }

    /** Version du protocole du pont que parle l'appli (`docs/interfaces.md` § 2). */
    const val PROTOCOLE = 1

    /**
     * WebSocket `api/ws?protocol=1`, relayé vers une autre machine avec `&machine=<id>` (vide : ce
     * serveur). Sans `protocol`, le serveur nous prendrait pour un ancien client (anciens noms).
     */
    fun ws(base: String, machine: String = ""): HttpUrl = api(base, "api/ws").newBuilder()
        .addQueryParameter("protocol", PROTOCOLE.toString())
        .apply { if (machine.isNotEmpty()) addQueryParameter("machine", machine) }
        .build()
}

/** Petit magasin clé → texte, pour tester le stockage sans Android. */
interface Preferences {
    fun lire(cle: String): String?
    fun ecrire(cle: String, valeur: String?)
}

/** Adresse du serveur gardée dans les préférences. */
class StockageAdresse(private val prefs: Preferences) {
    fun lire(): String = prefs.lire(CLE)?.let(Adresse::normaliser) ?: Adresse.PAR_DEFAUT

    /** Enregistre l'adresse normalisée et la rend ; null (rien n'est changé) si elle est invalide. */
    fun ecrire(texte: String): String? {
        val adresse = Adresse.normaliser(texte) ?: return null
        prefs.ecrire(CLE, adresse)
        return adresse
    }

    fun reinitialiser() = prefs.ecrire(CLE, null)

    private companion object {
        const val CLE = "serveur"
    }
}
