package com.mawena.ccs.ui.terminal

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Terminal
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ExtendedFloatingActionButton
import androidx.compose.material3.Icon
import androidx.compose.material3.ListItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.SuggestionChip
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.foundation.layout.Box
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.mawena.ccs.logique.Format
import com.mawena.ccs.logique.TachesFond
import com.mawena.ccs.reseau.EtatComptes
import com.mawena.ccs.reseau.EtatConnexion
import com.mawena.ccs.reseau.InfoTerminal
import com.mawena.ccs.reseau.ListeProjets
import com.mawena.ccs.ui.BarreHaut
import com.mawena.ccs.ui.EtatErreur
import com.mawena.ccs.ui.LocalAvis
import com.mawena.ccs.ui.ModeleAppli
import com.mawena.ccs.ui.TitreSection
import com.mawena.ccs.ui.texte
import kotlinx.coroutines.launch

/**
 * Terminaux : ceux ouverts dans l'appli, ceux du serveur qu'on peut reprendre (ouverts depuis la
 * version web, par exemple) et « Nouveau terminal » dans un dossier.
 */
@Composable
fun EcranTerminaux(modele: ModeleAppli, retour: () -> Unit, ouvrir: (String) -> Unit) {
    val terminaux = modele.depot.terminaux
    val locales by terminaux.sessions.collectAsStateWithLifecycle()
    val etat by modele.etat.collectAsStateWithLifecycle()
    val avis = LocalAvis.current
    val portee = rememberCoroutineScope()
    var serveur by remember { mutableStateOf<List<InfoTerminal>?>(null) }
    var erreur by remember { mutableStateOf<String?>(null) }
    var nouveau by remember { mutableStateOf(false) }

    suspend fun charger() {
        try { serveur = terminaux.lister(); erreur = null } catch (e: Exception) { erreur = e.texte() }
    }
    LaunchedEffect(etat is EtatConnexion.Connecte) { if (etat is EtatConnexion.Connecte) charger() }

    Box(Modifier.fillMaxSize()) {
        Column(Modifier.fillMaxSize()) {
            BarreHaut("Terminaux", retour = retour)
            LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(bottom = 96.dp)) {
                item { TitreSection("Dans l'appli", Modifier.padding(horizontal = 16.dp)) }
                if (locales.isEmpty()) item {
                    Text("Aucun terminal ouvert ici.", Modifier.padding(16.dp), color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                items(locales, key = { "l" + it.id }) { s ->
                    ListItem(
                        headlineContent = { Text(s.titre) },
                        supportingContent = { Text(TachesFond.cheminCourt(s.cwd) + if (s.fin != null) " · terminé" else "") },
                        leadingContent = { Icon(Icons.Filled.Terminal, null) },
                        modifier = Modifier.clickable { ouvrir(s.id) },
                    )
                }
                val autres = serveur.orEmpty().filter { i -> locales.none { it.id == i.termId } }
                if (autres.isNotEmpty()) {
                    item { TitreSection("Sur le serveur", Modifier.padding(horizontal = 16.dp)) }
                    items(autres, key = { "s" + it.termId }) { i ->
                        ListItem(
                            headlineContent = { Text(i.name) },
                            supportingContent = { Text(TachesFond.cheminCourt(i.cwd) + " · toucher pour le reprendre") },
                            leadingContent = { Icon(Icons.Filled.Terminal, null) },
                            modifier = Modifier.clickable {
                                portee.launch {
                                    try { ouvrir(terminaux.reprendre(i).id) } catch (e: Exception) { avis.dire(e.texte()) }
                                }
                            },
                        )
                    }
                }
                erreur?.let { m -> item { EtatErreur(m) { portee.launch { charger() } } } }
            }
        }
        ExtendedFloatingActionButton(
            onClick = { nouveau = true },
            icon = { Icon(Icons.Filled.Add, null) },
            text = { Text("Nouveau terminal") },
            modifier = Modifier.align(Alignment.BottomEnd).padding(16.dp),
        )
    }
    if (nouveau) DialogueNouveauTerminal(modele, fermer = { nouveau = false }) { cwd ->
        nouveau = false
        portee.launch {
            try { ouvrir(ouvrirTerminal(modele, cwd).id) } catch (e: Exception) { avis.dire("Terminal impossible : ${e.texte()}") }
        }
    }
}

/** Dossier du nouveau terminal : le dossier personnel, un projet, ou un chemin tapé (`~` permis). */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun DialogueNouveauTerminal(modele: ModeleAppli, initial: String = "", fermer: () -> Unit, ouvrir: (String) -> Unit) {
    val client = modele.depot.client
    var home by remember { mutableStateOf("") }
    var dossier by remember { mutableStateOf(initial) }
    var projets by remember { mutableStateOf<List<String>>(emptyList()) }
    LaunchedEffect(Unit) {
        runCatching { client.appeler("accounts.state", EtatComptes.serializer()) }.onSuccess {
            home = it.home
            if (dossier.isEmpty()) dossier = "~"
        }
        runCatching { client.appeler("projects.list", ListeProjets.serializer()) }.onSuccess { r ->
            projets = r.projets.filter { it.exists }.mapNotNull { it.cwd }.take(8)
        }
    }
    AlertDialog(
        onDismissRequest = fermer,
        title = { Text("Nouveau terminal") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedTextField(
                    dossier, { dossier = it }, Modifier.fillMaxWidth(), singleLine = true, label = { Text("Dossier") },
                    keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.None, autoCorrectEnabled = false),
                )
                if (projets.isNotEmpty()) FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    projets.forEach { p -> SuggestionChip({ dossier = Format.court(p, home) }, { Text(Format.base(p)) }) }
                }
            }
        },
        confirmButton = {
            Button(onClick = { ouvrir(TachesFond.dossier(dossier, home).ifEmpty { "~" }) }) { Text("Ouvrir") }
        },
        dismissButton = { TextButton(onClick = fermer) { Text("Annuler") } },
    )
}
