package com.mawena.ccs.reseau

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/** Une machine de `machines.list` (toujours traité par le serveur, jamais relayé). */
@Serializable
data class Machine(
    val id: String = "",
    val name: String = "",
    val online: Boolean = false,
    /** Le serveur lui-même : sa fiche est celle du « Serveur CCS » dans l'onglet Réseau. */
    val local: Boolean = false,
    val cores: Int = 0,
    val load: Double = 0.0,
    @SerialName("mem_used") val memUtilisee: Double = 0.0,
    @SerialName("mem_total") val memTotale: Double = 0.0,
    val tunnel: Boolean = false,
    /** Nom d'hôte, nom `reseau` des réglages et adresse dans le réseau maillé (rattachement). */
    val host: String = "",
    val mesh: String = "",
    @SerialName("mesh_ip") val ipMaille: String = "",
    /** Outils inventoriés, places (travaux en cours / limite) et travaux en attente. */
    val tools: List<String> = emptyList(),
    val limit: Int = 0,
    val running: Int = 0,
    val waiting: Int = 0,
) {
    val nom: String get() = name.ifBlank { id }

    /** Limite de travaux simultanés (2 par défaut, comme le web). */
    val limite: Int get() = if (limit > 0) limit else 2

    /** Joignable par le réseau maillé ou le tunnel Ricochet : on peut la piloter. */
    val choisissable: Boolean get() = online && (tunnel || ipMaille.isNotEmpty())

    /** « en ligne · charge 1.2 sur 8 cœurs », « hors ligne »… comme `describe` de `machines.js`. */
    val description: String
        get() {
            if (!online) return "hors ligne"
            val parts = mutableListOf("en ligne")
            if (cores > 0) parts += "charge ${"%.1f".format(java.util.Locale.ROOT, load)} sur $cores cœurs"
            if (!tunnel && ipMaille.isEmpty()) parts += "tunnel SSH non activé"
            return parts.joinToString(" · ")
        }
}

@Serializable
data class ListeMachines(
    val machines: List<Machine> = emptyList(),
    val message: String? = null,
    val configured: Boolean = true,
) {
    /** Machines autres que ce serveur. */
    val autres: List<Machine> get() = machines.filter { !it.local }
}

/** Un travail de `machines.jobs` (commande lancée par `ccs remote run` ou l'onglet Réseau). */
@Serializable
data class TravailDistant(
    val id: String = "",
    val text: String = "",
    val state: String = "",
    val machine: String? = null,
    val cwd: String = "",
    val code: Int? = null,
    val created: Double? = null,
    val started: Double? = null,
    val ended: Double? = null,
    val why: String = "",
)

@Serializable
data class ListeTravaux(val jobs: List<TravailDistant> = emptyList())

@Serializable
data class JournalTravail(val text: String = "")

/** Réponse de `machines.settings` : relais Ricochet (le jeton n'est jamais renvoyé). */
@Serializable
data class ReglagesRicochet(
    val relay: String = "",
    @SerialName("token_set") val jetonDefini: Boolean = false,
    @SerialName("operator_set") val operateurDefini: Boolean = false,
    val path: String = "",
    @SerialName("default_limit") val limiteParDefaut: Int = 2,
)

/** Réponse de `machines.add` : la commande à coller sur le nouveau PC. */
@Serializable
data class PcAjoute(
    val id: String = "",
    val command: String = "",
    val mesh: Boolean = false,
    val full: Boolean = false,
    @SerialName("expires_s") val expireS: Int = 900,
)
