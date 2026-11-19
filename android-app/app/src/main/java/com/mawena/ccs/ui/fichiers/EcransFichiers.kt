package com.mawena.ccs.ui.fichiers

import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.mawena.ccs.logique.Fichiers
import com.mawena.ccs.reseau.EtatConnexion
import com.mawena.ccs.reseau.RacinesFichiers
import com.mawena.ccs.ui.BarreHaut
import com.mawena.ccs.ui.Chargement
import com.mawena.ccs.ui.EtatErreur
import com.mawena.ccs.ui.ModeleAppli
import com.mawena.ccs.ui.texte
import kotlinx.coroutines.launch

/** Onglet Fichiers (`web/files-browser.js`) : dossiers permis du serveur (personnel, /var/www, /srv). */
@Composable
fun EcranFichiersOnglet(modele: ModeleAppli, ouvrirFichier: (String) -> Unit) {
    val etat by modele.etat.collectAsStateWithLifecycle()
    val connecte = etat is EtatConnexion.Connecte
    val portee = rememberCoroutineScope()
    var racines by remember { mutableStateOf<RacinesFichiers?>(null) }
    var erreur by remember { mutableStateOf<String?>(null) }
    var racine by rememberSaveable { mutableStateOf<String?>(null) }

    suspend fun charger() {
        try {
            racines = modele.depot.client.appeler("files.roots", RacinesFichiers.serializer())
            erreur = null
        } catch (e: Exception) {
            erreur = e.texte()
        }
    }
    LaunchedEffect(connecte) { if (connecte && racines == null) charger() }

    val r = racines
    Column(Modifier.fillMaxSize()) {
        BarreHaut("Fichiers", "Dossiers du serveur")
        when {
            r == null && erreur != null -> EtatErreur(erreur!!) { portee.launch { charger() } }
            r == null -> Chargement()
            else -> {
                val base = racine?.takeIf { it in r.roots } ?: r.home
                PanneauFichiers(
                    modele, base, ouvrirFichier, home = r.home, protege = null,
                    entete = {
                        if (r.roots.size > 1) Row(
                            Modifier.horizontalScroll(rememberScrollState()).padding(horizontal = 12.dp),
                            horizontalArrangement = Arrangement.spacedBy(8.dp),
                        ) {
                            r.roots.forEach { x ->
                                FilterChip(selected = x == base, onClick = { racine = x },
                                    label = { Text(if (x == r.home) "Personnel" else x) })
                            }
                        }
                    },
                )
            }
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
