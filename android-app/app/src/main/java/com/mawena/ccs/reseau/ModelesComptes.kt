package com.mawena.ccs.reseau

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonElement

/** Pause de la bascule et de l'orchestrateur (`accounts.state`). */
@Serializable
data class Pause(val until: String? = null, val label: String = "")

/**
 * Réponse de `accounts.state` (voir `accounts_state` dans `bridge.py`). `pause_choices` : liste de
 * paires `[choix, libellé]` (`1h`, `4h`, `demain`, `manuel`).
 */
@Serializable
data class EtatComptes(
    val user: String = "",
    val home: String = "",
    val active: String? = null,
    val colors: Map<String, String> = emptyMap(),
    val pause: Pause? = null,
    @SerialName("pause_choices") val choixPause: List<List<String>> = emptyList(),
) {
    /** Choix de pause valides : (valeur, libellé). */
    val choix: List<Pair<String, String>>
        get() = choixPause.filter { it.size >= 2 }.map { it[0] to it[1] }
}

/** Une vérification de `doctor.run` : `statut` vaut `erreur`, `avertissement` ou `ok`. */
@Serializable
data class Verification(
    val nom: String = "",
    val statut: String = "",
    val detail: String = "",
    val commande: String? = null,
)

@Serializable
data class Bilan(
    val checks: List<Verification> = emptyList(),
    val errors: Int = 0,
    val warnings: Int = 0,
    val summary: String = "",
)

/** `analysis.report` : jetons pondérés par projet, modèle, compte et heure. */
@Serializable
data class Rapport(
    val total: Double = 0.0,
    @SerialName("by_project") val parProjet: Map<String, Double> = emptyMap(),
    @SerialName("by_model") val parModele: Map<String, Double> = emptyMap(),
    @SerialName("by_account") val parCompte: Map<String, Double> = emptyMap(),
    @SerialName("by_hour") val parHeure: List<Double> = emptyList(),
    val days: Int = 7,
    val responses: Int = 0,
)

/** Réponse de `accounts.switch` (`ok` faux si `ccs switch` a échoué). */
@Serializable
data class ResultatBascule(val ok: Boolean = false)

/** Texte d'un champ de `best` ou `auto_switch` (objets libres) : `chemin` mène à une chaîne. */
fun JsonElement?.texte(vararg chemin: String): String? {
    var e: JsonElement? = this
    for (c in chemin) e = (e as? kotlinx.serialization.json.JsonObject)?.get(c)
    val p = e as? kotlinx.serialization.json.JsonPrimitive ?: return null
    return if (p.isString) p.content.takeIf { it.isNotBlank() } else null
}

/** Date en secondes (epoch) d'un champ numérique, ou null. */
fun JsonElement?.secondes(): Double? =
    (this as? kotlinx.serialization.json.JsonPrimitive)?.takeIf { !it.isString }?.content?.toDoubleOrNull()
