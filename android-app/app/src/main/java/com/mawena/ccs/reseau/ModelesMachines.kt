package com.mawena.ccs.reseau

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/** Une machine de `machines.list` (toujours traité par le serveur, jamais relayé). */
@Serializable
data class Machine(
    val id: String = "",
    val name: String = "",
    val online: Boolean = false,
    /** Le serveur lui-même : jamais proposé (c'est « Ce serveur »). */
    val local: Boolean = false,
    val cores: Int = 0,
    val load: Double = 0.0,
    @SerialName("mem_used") val memUtilisee: Double = 0.0,
    @SerialName("mem_total") val memTotale: Double = 0.0,
    val tunnel: Boolean = false,
) {
    val nom: String get() = name.ifBlank { id }

    /** Joignable par le tunnel : on peut la piloter. */
    val choisissable: Boolean get() = online && tunnel

    /** « en ligne · charge 1.2 sur 8 cœurs », « hors ligne »… comme `describe` de `machines.js`. */
    val description: String
        get() {
            if (!online) return "hors ligne"
            val parts = mutableListOf("en ligne")
            if (cores > 0) parts += "charge ${"%.1f".format(java.util.Locale.ROOT, load)} sur $cores cœurs"
            if (!tunnel) parts += "tunnel SSH non activé"
            return parts.joinToString(" · ")
        }
}

@Serializable
data class ListeMachines(
    val machines: List<Machine> = emptyList(),
    val message: String? = null,
) {
    /** Machines autres que ce serveur. */
    val autres: List<Machine> get() = machines.filter { !it.local }
}
