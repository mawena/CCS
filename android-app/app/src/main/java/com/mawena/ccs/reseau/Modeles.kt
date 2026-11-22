package com.mawena.ccs.reseau

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonElement

@Serializable
data class Sante(val ok: Boolean = false, val version: String = "")

@Serializable
data class InfoPortier(val enabled: Boolean = false, val login: String = "")

@Serializable
data class JetonAppli(val token: String? = null)

@Serializable
data class ResultatRevocation(val revoked: Boolean = false)

@Serializable
data class InfoSession(val user: String = "", val portier: Boolean = false)

/**
 * Réponse de `/api/pair` et `/api/enroll`. `status` : `ok` (avec `token`), `code` (code TOTP
 * demandé), `enroll` (première connexion : `secret` à ajouter dans l'appli d'authentification puis
 * premier code), `blocked` (`retry_after` secondes), `refused`, `error`.
 */
@Serializable
data class ReponseConnexion(
    val status: String = "error",
    val user: String? = null,
    val token: String? = null,
    val pending: String? = null,
    val secret: String? = null,
    @SerialName("retry_after") val retryAfter: Double? = null,
    val message: String? = null,
)

@Serializable
data class Jauge(
    val kind: String? = null,
    val label: String = "",
    val percent: Double = 0.0,
    val reset: String = "",
)

@Serializable
data class StatutCarte(val text: String = "", val kind: String = "")

/** Une carte de compte de `accounts.cards` (voir `_card` dans `bridge_admin.py`). */
@Serializable
data class Carte(
    val name: String = "",
    val plan: String = "",
    val email: String = "",
    val org: String = "",
    val active: Boolean = false,
    val color: String? = null,
    val main: List<Jauge> = emptyList(),
    val others: List<Jauge> = emptyList(),
    val status: StatutCarte? = null,
    @SerialName("error_raw") val erreur: String? = null,
    val details: List<String> = emptyList(),
    @SerialName("fetched_at") val releve: JsonElement? = null,
    @SerialName("has_data") val donnees: Boolean = false,
)

@Serializable
data class Cartes(
    val cards: List<Carte> = emptyList(),
    val best: JsonElement? = null,
    @SerialName("auto_switch") val bascule: JsonElement? = null,
    @SerialName("updated_at") val misAJour: JsonElement? = null,
    @SerialName("running_chats") val chatsEnCours: Int = 0,
)
