package com.mawena.ccs.reseau

import kotlinx.serialization.Serializable

/** Un appareil annoncé au pont (`audio.list` : `devices`) : sortie s'il sait jouer, source s'il sait capter. */
@Serializable
data class AppareilAudio(
    val device: String = "",
    val label: String = "",
    val ip: String = "",
    val port: Int = 4010,
    val play: Boolean = false,
    val capture: Boolean = false,
    /** linux | android | ios | web | autre */
    val system: String = "autre",
    /** Secondes depuis sa dernière annonce. */
    val age: Double = 0.0,
) {
    val nom: String get() = label.ifBlank { device }
}

/** Un flux en cours (`audio.list` : `streams`). */
@Serializable
data class FluxAudio(
    val stream: String = "",
    val source: String = "",
    val target: String = "",
    val started: Double = 0.0,
)

/** Réponse de `audio.list`. */
@Serializable
data class ListeAudio(
    val devices: List<AppareilAudio> = emptyList(),
    val streams: List<FluxAudio> = emptyList(),
    val every: Int = 30,
)

/** Réponse de `audio.send`. */
@Serializable
data class EnvoiAudio(
    val stream: String = "",
    val ip: String = "",
    val port: Int = 4010,
    val channels: Int = 2,
)
