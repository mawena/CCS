package com.mawena.ccs.ui.fichiers

import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.selection.selectableGroup
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Computer
import androidx.compose.material.icons.filled.Dns
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.material3.minimumInteractiveComponentSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.mawena.ccs.logique.Appareils
import com.mawena.ccs.logique.Fichiers
import com.mawena.ccs.reseau.ConnexionFichiers
import com.mawena.ccs.reseau.EtatConnexion
import com.mawena.ccs.reseau.RacinesFichiers
import com.mawena.ccs.ui.BarreHaut
import com.mawena.ccs.ui.Chargement
import com.mawena.ccs.ui.EtatErreur
import com.mawena.ccs.ui.ModeleAppli
import com.mawena.ccs.ui.texte
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.launch

/**
 * Onglet Fichiers (`web/files-browser.js`) : en haut, les appareils (« Serveur CCS » puis chaque PC
 * du réseau maillé, grisé s'il est injoignable) ; dessous, les dossiers permis de l'appareil choisi
 * (personnel, /var/www, /srv). Un appareil autre que la machine pilotée a sa propre connexion
 * ([com.mawena.ccs.reseau.ConnexionFichiers]), sans changer la machine pilotée de l'appli.
 * `ouvrirFichier(chemin, appareil)` ouvre un fichier sur la connexion de cet appareil.
 */
@Composable
fun EcranFichiersOnglet(modele: ModeleAppli, ouvrirFichier: (chemin: String, appareil: String) -> Unit) {
    val connexion = modele.fichiers
    val machines by modele.machines.collectAsStateWithLifecycle()
    val appareils = remember(machines) { Appareils.liste(machines) }
    val ouverte by connexion.ouverte.collectAsStateWithLifecycle()

    // états à jour (en ligne, réseau maillé, tunnel) en arrivant sur l'onglet
    LaunchedEffect(Unit) { modele.rafraichirMachines() }
    // dernier appareil choisi (la connexion est fermée en quittant l'onglet)
    LaunchedEffect(Unit) {
        if (connexion.ouverte.value == null) connexion.ouvrir(Appareils.initial(connexion.memorise, appareils))
    }

    val o = ouverte
    val nom = o?.let { Appareils.nom(it.appareil, appareils) }.orEmpty()
    Column(Modifier.fillMaxSize()) {
        BarreHaut("Fichiers", if (o == null || o.appareil == Appareils.SERVEUR) "Dossiers du serveur" else "Dossiers de $nom")
        if (appareils.size > 1) BarreAppareils(appareils, o?.appareil) { connexion.ouvrir(it) }
        if (o == null) {
            Chargement()
        } else {
            // autre appareil : nouvel état (dossier, racine), même si les chemins se ressemblent
            key(o) { NavigateurAppareil(modele, o, nom, ouvrirFichier) }
        }
    }
}

/** Puces des appareils, défilables horizontalement ; un appareil injoignable est grisé avec la raison. */
@Composable
private fun BarreAppareils(appareils: List<Appareils.Appareil>, choisi: String?, choisir: (String) -> Unit) {
    Row(
        Modifier.fillMaxWidth().selectableGroup().horizontalScroll(rememberScrollState()).padding(horizontal = 12.dp),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        appareils.forEach { a ->
            FilterChip(
                selected = a.id == choisi,
                onClick = { if (a.id != choisi) choisir(a.id) },
                enabled = a.joignable,
                modifier = Modifier.minimumInteractiveComponentSize(),
                leadingIcon = {
                    Icon(if (a.serveur) Icons.Filled.Dns else Icons.Filled.Computer, contentDescription = null, Modifier.size(18.dp))
                },
                label = { Text(if (a.joignable) a.nom else "${a.nom} · ${a.raison}", maxLines = 1) },
            )
        }
    }
}

/** Racines puis dossiers d'un appareil, sur sa connexion ; message clair s'il est injoignable. */
@Composable
private fun NavigateurAppareil(
    modele: ModeleAppli,
    o: ConnexionFichiers.Ouverte,
    nom: String,
    ouvrirFichier: (chemin: String, appareil: String) -> Unit,
) {
    val client = o.client
    val etat by client.etat.collectAsStateWithLifecycle()
    val connecte = etat is EtatConnexion.Connecte
    val portee = rememberCoroutineScope()
    var racines by remember { mutableStateOf<RacinesFichiers?>(null) }
    var erreur by remember { mutableStateOf<String?>(null) }
    var racine by rememberSaveable { mutableStateOf<String?>(null) }

    suspend fun charger() {
        try {
            racines = client.appeler("files.roots", RacinesFichiers.serializer())
            erreur = null
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            erreur = Appareils.messageInjoignable(o.appareil, nom, e.texte())
        }
    }
    LaunchedEffect(connecte) { if (connecte && racines == null) charger() }
    val reessayer: () -> Unit = {
        erreur = null
        modele.fichiers.reessayer()
        if (connecte) portee.launch { charger() }
    }

    val r = racines
    val coupe = when (val e = etat) {
        is EtatConnexion.HorsLigne -> e.raison
        is EtatConnexion.Refuse -> e.raison
        else -> null
    }
    when {
        // coupure d'abord : sa raison (fermeture 4010 du pont) est plus précise que l'appel perdu
        r == null && coupe != null -> EtatErreur(Appareils.messageInjoignable(o.appareil, nom, coupe), reessayer)
        r == null && erreur != null -> EtatErreur(erreur!!, reessayer)
        r == null -> Chargement(if (o.propre) "Connexion à $nom…" else null)
        else -> {
            val base = racine?.takeIf { it in r.roots } ?: r.home
            PanneauFichiers(
                modele, base, { ouvrirFichier(it, o.appareil) }, home = r.home, protege = null,
                entete = {
                    if (r.roots.size > 1) Row(
                        Modifier.horizontalScroll(rememberScrollState()).padding(horizontal = 12.dp),
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        r.roots.forEach { x ->
                            FilterChip(selected = x == base, onClick = { racine = x },
                                modifier = Modifier.minimumInteractiveComponentSize(),
                                label = { Text(if (x == r.home) "Personnel" else x) })
                        }
                    }
                },
                client = client,
            )
        }
    }
}

/** Fichiers d'un projet (ouvert depuis le chat). */
@Composable
fun EcranFichiersProjet(modele: ModeleAppli, cwd: String, retour: () -> Unit, ouvrirFichier: (String) -> Unit) {
    Column(Modifier.fillMaxSize()) {
        BarreHaut("Fichiers", Fichiers.nom(cwd), retour = retour)
        PanneauFichiers(modele, cwd, ouvrirFichier)
    }
}
