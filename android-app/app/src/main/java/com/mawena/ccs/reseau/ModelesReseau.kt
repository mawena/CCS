package com.mawena.ccs.reseau

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/** Un appareil du réseau maillé (`network.status` : `self`, `peers`). */
@Serializable
data class Appareil(
    val name: String = "",
    val host: String = "",
    val os: String = "",
    val ips: List<String> = emptyList(),
    val online: Boolean = false,
    /** self | lan | direct | relay | idle | offline */
    val path: String = "idle",
    val endpoint: String = "",
    val relay: String = "",
    val addrs: List<String> = emptyList(),
    val rx: Long = 0,
    val tx: Long = 0,
)

/** Appareil connu du serveur Headscale (`nodes`). */
@Serializable
data class NoeudServeur(
    val id: Long? = null,
    val name: String = "",
    val host: String = "",
    val ips: List<String> = emptyList(),
    val online: Boolean = false,
)

/** Réponse de `network.status`. */
@Serializable
data class EtatReseau(
    val url: String = "",
    val domain: String = "",
    val installed: Boolean = false,
    val server: Boolean = false,
    val state: String = "",
    @SerialName("self") val ici: Appareil? = null,
    val peers: List<Appareil> = emptyList(),
    val nodes: List<NoeudServeur> = emptyList(),
    val error: String? = null,
)

/** Réponse de `network.ping`. */
@Serializable
data class Ping(
    val ok: Boolean = false,
    val path: String = "",
    val via: String = "",
    val ms: Double = 0.0,
    val error: String? = null,
)

/** Réponse de `network.key`. */
@Serializable
data class CleReseau(val key: String = "", val url: String = "", val linux: List<String> = emptyList())

@Serializable
data class AppareilValide(val name: String = "")
