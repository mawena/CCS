package com.mawena.ccs.reseau

import com.mawena.ccs.donnees.Identifiants
import com.mawena.ccs.donnees.Preferences
import com.mawena.ccs.logique.Appareils
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/**
 * Connexion de l'onglet Fichiers à un appareil (`web/files-browser.js`) : une seconde connexion
 * `/api/ws?protocol=1&machine=<id>`, la même que celle de la machine pilotée, mais SANS changer la
 * machine pilotée de l'appli. Si l'appareil est justement la machine pilotée, la connexion
 * principale sert telle quelle. Le dernier appareil choisi est gardé dans `prefs`.
 *
 * [fabrique] crée un client fixé sur une machine (non démarré) ; [identifiants] rend ceux en cours.
 */
class ConnexionFichiers(
    private val principal: CcsClient,
    private val fabrique: (machine: String) -> CcsClient,
    private val identifiants: () -> Identifiants?,
    private val prefs: Preferences? = null,
) {
    /** Appareil ouvert et son client ; `propre` : connexion à part, à fermer en le quittant. */
    data class Ouverte(val appareil: String, val client: CcsClient, val propre: Boolean)

    private val _ouverte = MutableStateFlow<Ouverte?>(null)
    val ouverte: StateFlow<Ouverte?> = _ouverte.asStateFlow()

    /** Dernier appareil choisi ("" : le serveur). */
    val memorise: String get() = prefs?.lire(Appareils.CLE_MEMOIRE).orEmpty()

    /** Ouvre `appareil` (ou garde la connexion s'il l'est déjà) et le retient comme dernier choisi. */
    @Synchronized
    fun ouvrir(appareil: String): Ouverte {
        prefs?.ecrire(Appareils.CLE_MEMOIRE, appareil.ifEmpty { null })
        val pilotee = principal.machine.value
        val o = _ouverte.value
        if (o != null && o.appareil == appareil && o.propre != Appareils.partageConnexion(appareil, pilotee)) return o
        fermer()
        val n = if (Appareils.partageConnexion(appareil, pilotee)) {
            Ouverte(appareil, principal, propre = false)
        } else {
            val c = fabrique(appareil)
            identifiants()?.let { c.demarrer(it) }
            Ouverte(appareil, c, propre = true)
        }
        _ouverte.value = n
        return n
    }

    /** Client de `appareil`, ouvert au besoin (écran d'un fichier ouvert depuis l'onglet). */
    fun clientPour(appareil: String): CcsClient {
        val o = _ouverte.value
        return if (o != null && o.appareil == appareil) o.client else ouvrir(appareil).client
    }

    /** Ferme la connexion à part (appareil quitté, onglet quitté, déconnexion). */
    @Synchronized
    fun fermer() {
        val o = _ouverte.value ?: return
        _ouverte.value = null
        if (o.propre) o.client.arreter()
    }

    /** Nouvel essai tout de suite (bouton « Réessayer »). */
    fun reessayer() {
        val o = _ouverte.value ?: return
        val arretee = o.client.etat.value.let { it is EtatConnexion.Arrete || it is EtatConnexion.Refuse }
        if (o.propre && arretee) identifiants()?.let { o.client.demarrer(it) } else o.client.reessayer()
    }
}
