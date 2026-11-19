package com.mawena.ccs.ui

import android.app.Application
import android.webkit.CookieManager
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.mawena.ccs.CcsAppli
import com.mawena.ccs.donnees.Identifiants
import com.mawena.ccs.reseau.EtatConnexion
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

/** État de l'appli : adresse du serveur, identifiants gardés, connexion. */
class ModeleAppli(appli: Application) : AndroidViewModel(appli) {
    val depot = (appli as CcsAppli).depot

    private val _adresse = MutableStateFlow(depot.adresse.lire())
    val adresse: StateFlow<String> = _adresse.asStateFlow()

    private val _identifiants = MutableStateFlow(depot.coffre.lire()?.takeIf { it.serveur == _adresse.value })
    val identifiants: StateFlow<Identifiants?> = _identifiants.asStateFlow()

    /** Pourquoi on est revenu à l'écran de connexion (jeton révoqué…), affiché une fois. */
    private val _avis = MutableStateFlow<String?>(null)
    val avis: StateFlow<String?> = _avis.asStateFlow()

    val etat: StateFlow<EtatConnexion> = depot.client.etat

    init {
        val i = _identifiants.value
        if (i != null && depot.client.etat.value is EtatConnexion.Arrete) depot.client.demarrer(i)
        viewModelScope.launch {
            depot.client.etat.collect {
                if (it is EtatConnexion.Refuse) {
                    oublier()
                    _avis.value = "${it.raison} Reconnecte-toi."
                }
            }
        }
    }

    fun connecte(i: Identifiants) {
        depot.coffre.ecrire(i)
        _identifiants.value = i
        _avis.value = null
        depot.client.demarrer(i)
    }

    fun deconnecter() {
        val portier = _identifiants.value?.portier == true
        oublier()
        if (portier) CookieManager.getInstance().removeAllCookies(null)
    }

    private fun oublier() {
        depot.client.arreter()
        depot.coffre.ecrire(null)
        _identifiants.value = null
    }

    /** Rend false si l'adresse est invalide. */
    fun changerAdresse(texte: String): Boolean {
        val nouvelle = depot.adresse.ecrire(texte) ?: return false
        _adresse.value = nouvelle
        return true
    }

    fun avisLu() {
        _avis.value = null
    }
}
