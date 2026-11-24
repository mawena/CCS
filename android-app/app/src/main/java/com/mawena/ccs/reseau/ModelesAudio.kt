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
    /** Lecteurs MPRIS de la machine (Linux seulement), `null` ailleurs. */
    val players: List<LecteurAudio>? = null,
) {
    val nom: String get() = label.ifBlank { device }
}

/** Un lecteur MPRIS (VLC, Firefox…) d'une machine Linux, pilotable par `audio.control`. */
@Serializable
data class LecteurAudio(
    val id: String = "",
    val name: String = "",
    /** Playing | Paused | Stopped */
    val status: String = "Stopped",
    val title: String = "",
    val artist: String = "",
    /** 0-100, ou null si le lecteur ne le donne pas. */
    val volume: Double? = null,
    val can_prev: Boolean = false,
    val can_next: Boolean = false,
    val can_play: Boolean = false,
    val can_pause: Boolean = false,
    val can_seek: Boolean = false,
) {
    val joue: Boolean get() = status == "Playing"
    val morceau: String get() = listOf(artist, title).filter { it.isNotBlank() }.joinToString(" — ").ifBlank { "Rien en lecture" }
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
