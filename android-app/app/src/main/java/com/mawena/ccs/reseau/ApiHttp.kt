package com.mawena.ccs.reseau

import com.mawena.ccs.donnees.Adresse
import com.mawena.ccs.donnees.Identifiants
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.KSerializer
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.IOException

/** Ajoute l'authentification : jeton d'appareil en Bearer, ou cookies de Portier. */
fun Request.Builder.authentifier(i: Identifiants): Request.Builder = apply {
    when {
        i.jeton != null -> header("Authorization", "Bearer ${i.jeton}")
        i.cookies != null -> header("Cookie", i.cookies)
    }
}

/** Routes HTTP de `ccs-web` (hors WebSocket). */
class ApiHttp(private val http: OkHttpClient) {
    private val typeJson = "application/json".toMediaType()

    suspend fun sante(base: String): Sante = obtenir(base, "api/health", Sante.serializer())

    suspend fun portier(base: String): InfoPortier = obtenir(base, "api/portier", InfoPortier.serializer())

    /** Utilisateur reconnu avec ces identifiants, ou null si le serveur les refuse (401). */
    suspend fun session(i: Identifiants): InfoSession? = withContext(Dispatchers.IO) {
        val req = Request.Builder().url(Adresse.api(i.serveur, "api/session")).authentifier(i).build()
        http.newCall(req).execute().use { r ->
            when {
                r.code == 401 -> null
                !r.isSuccessful -> throw IOException("Erreur ${r.code}")
                else -> CodecRpc.json.decodeFromString(InfoSession.serializer(), r.body!!.string())
            }
        }
    }

    /** Appairage : identifiant, mot de passe Ubuntu et code → jeton d'appareil (`status` = `ok`). */
    suspend fun appairer(base: String, utilisateur: String, motDePasse: String, code: String, nom: String) =
        poster(base, "api/pair", buildJsonObject {
            put("user", utilisateur)
            put("password", motDePasse)
            put("code", code)
            put("name", nom)
        }.toString())

    /** Première connexion : premier code du secret reçu → jeton d'appareil. */
    suspend fun inscrire(base: String, enAttente: String, code: String) =
        poster(base, "api/enroll", buildJsonObject {
            put("pending", enAttente)
            put("code", code)
        }.toString())

    private suspend fun <T> obtenir(base: String, chemin: String, serialiseur: KSerializer<T>): T =
        withContext(Dispatchers.IO) {
            val req = Request.Builder().url(Adresse.api(base, chemin)).build()
            http.newCall(req).execute().use { r ->
                if (!r.isSuccessful) throw IOException("Erreur ${r.code}")
                CodecRpc.json.decodeFromString(serialiseur, r.body?.string().orEmpty())
            }
        }

    private suspend fun poster(base: String, chemin: String, corps: String): ReponseConnexion =
        withContext(Dispatchers.IO) {
            val req = Request.Builder().url(Adresse.api(base, chemin)).post(corps.toRequestBody(typeJson)).build()
            try {
                http.newCall(req).execute().use { r -> lireReponse(r.code, r.body?.string().orEmpty()) }
            } catch (e: IOException) {
                ReponseConnexion(status = "error", message = "Serveur injoignable.")
            }
        }

    companion object {
        /** Réponse de `/api/pair` ou `/api/enroll` d'après le code HTTP et le corps. */
        fun lireReponse(code: Int, corps: String): ReponseConnexion = when (code) {
            in 200..299 -> runCatching { CodecRpc.json.decodeFromString(ReponseConnexion.serializer(), corps) }
                .getOrElse { ReponseConnexion(status = "error", message = "Réponse illisible du serveur.") }
            401 -> ReponseConnexion(status = "refused", message = corps.ifBlank { "Connexion refusée." })
            503 -> ReponseConnexion(status = "error", message = "Service de connexion indisponible.")
            else -> ReponseConnexion(status = "error", message = "Erreur $code")
        }
    }
}
