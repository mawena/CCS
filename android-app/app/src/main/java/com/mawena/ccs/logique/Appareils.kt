package com.mawena.ccs.logique

import com.mawena.ccs.reseau.Machine

/**
 * Appareils de l'onglet Fichiers (`web/files-browser.js`) : le serveur CCS, puis chaque PC du
 * réseau maillé où CCS est installé. Un PC est joignable s'il est en ligne et qu'on l'atteint par le
 * réseau maillé (`mesh_ip`) ou le tunnel Ricochet ; sinon sa puce est grisée avec la raison.
 */
object Appareils {
    /** Identifiant du serveur CCS lui-même (connexion sans `?machine=`). */
    const val SERVEUR = ""
    const val NOM_SERVEUR = "Serveur CCS"

    /** Clé des préférences : dernier appareil choisi dans l'onglet Fichiers. */
    const val CLE_MEMOIRE = "fichiers-appareil"

    data class Appareil(
        val id: String,
        val nom: String,
        val joignable: Boolean,
        /** Pourquoi il n'est pas joignable (« hors ligne », « ni réseau maillé ni tunnel »), sinon "". */
        val raison: String = "",
    ) {
        val serveur: Boolean get() = id == SERVEUR
    }

    fun joignable(m: Machine): Boolean = !m.local && m.online && (m.ipMaille.isNotEmpty() || m.tunnel)

    fun raison(m: Machine): String = when {
        joignable(m) -> ""
        !m.online -> "hors ligne"
        else -> "ni réseau maillé ni tunnel"
    }

    /** « Serveur CCS » d'abord, puis chaque machine non locale de `machines.list`, dans l'ordre reçu. */
    fun liste(machines: List<Machine>): List<Appareil> =
        listOf(Appareil(SERVEUR, NOM_SERVEUR, true)) +
            machines.filter { !it.local && it.id.isNotEmpty() }.distinctBy { it.id }
                .map { Appareil(it.id, it.nom, joignable(it), raison(it)) }

    /**
     * Appareil à ouvrir en arrivant sur l'onglet : le dernier choisi, sauf s'il n'existe plus dans la
     * liste connue (le serveur alors). Liste encore vide (rien que le serveur) : on tente le dernier.
     */
    fun initial(memorise: String?, appareils: List<Appareil>): String {
        val m = memorise.orEmpty()
        if (m.isEmpty()) return SERVEUR
        if (appareils.none { !it.serveur }) return m
        return if (appareils.any { it.id == m }) m else SERVEUR
    }

    fun nom(id: String, appareils: List<Appareil>): String =
        appareils.firstOrNull { it.id == id }?.nom ?: id.ifEmpty { NOM_SERVEUR }

    /**
     * L'appareil est la machine déjà pilotée par l'appli : la connexion principale sert telle quelle,
     * sans en ouvrir une seconde. Sinon (y compris le serveur quand on pilote un PC) : connexion à part.
     */
    fun partageConnexion(appareil: String, pilotee: String): Boolean = appareil == pilotee

    /** « pc-bureau injoignable : hors ligne » ; pour le serveur, la raison seule. */
    fun messageInjoignable(appareil: String, nom: String, raison: String): String {
        val r = raison.trim().ifEmpty { "pas de réponse." }
            .let { if (it == RAISON_PILOTEE) "pas de réponse par le réseau maillé ni le tunnel." else it }
        return if (appareil == SERVEUR) r else "$nom injoignable : $r"
    }

    /** Raison par défaut de [com.mawena.ccs.reseau.CcsClient] pour une fermeture 4010. */
    private const val RAISON_PILOTEE = "La machine pilotée est injoignable."

    /** Argument `appareil` de la route d'un fichier : vide = connexion principale, « @id » = appareil. */
    fun versRoute(appareil: String?): String = appareil?.let { "@$it" }.orEmpty()

    fun deRoute(argument: String?): String? = argument?.takeIf { it.startsWith("@") }?.substring(1)
}
