package com.mawena.ccs.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.AccountCircle
import androidx.compose.material.icons.filled.AddComment
import androidx.compose.material.icons.filled.Terminal
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.mawena.ccs.logique.Format
import com.mawena.ccs.reseau.CompteProjet
import com.mawena.ccs.reseau.EtatConnexion
import com.mawena.ccs.reseau.ListeChats
import com.mawena.ccs.reseau.ListeProjets
import kotlinx.coroutines.launch
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

private const val PAS = 30

/**
 * Écran Projet (`project.js`) : nom et chemin, compte associé au dossier, « Nouveau chat » et les
 * conversations du projet ; onglets Feuille de route, Fichiers et Git ; terminal dans le dossier.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun EcranProjet(
    modele: ModeleAppli,
    cwd: String,
    retour: () -> Unit,
    ouvrirChat: (DestChat) -> Unit,
    ouvrirFichier: (String) -> Unit = {},
    ouvrirCommit: (String, String) -> Unit = { _, _ -> },
    ouvrirTerminal: (String) -> Unit = {},
) {
    val client = modele.depot.client
    val etat by modele.etat.collectAsStateWithLifecycle()
    val portee = rememberCoroutineScope()
    var liste by remember { mutableStateOf<ListeProjets?>(null) }
    var compte by remember { mutableStateOf<CompteProjet?>(null) }
    var ouvertes by remember { mutableStateOf<Set<String>>(emptySet()) }
    var erreur by remember { mutableStateOf<String?>(null) }
    var charge by remember { mutableStateOf(false) }
    var montres by remember { mutableIntStateOf(PAS) }
    var nouvelle by remember { mutableStateOf(false) }
    val actions = remember { EtatActions() }
    val connecte = etat is EtatConnexion.Connecte
    var onglet by androidx.compose.runtime.saveable.rememberSaveable { mutableIntStateOf(0) }

    suspend fun charger() {
        charge = true
        try {
            liste = client.appeler("projects.list", ListeProjets.serializer(), buildJsonObject { put("cwd", cwd) })
            erreur = null
        } catch (e: Exception) {
            erreur = e.texte()
        }
        runCatching { client.appeler("projects.account", CompteProjet.serializer(), buildJsonObject { put("cwd", cwd) }) }
            .onSuccess { compte = it }
        runCatching { client.appeler("chat.list", ListeChats.serializer()) }
            .onSuccess { r -> ouvertes = r.chats.mapNotNull { it.sessionId }.toSet() }
        charge = false
    }

    LaunchedEffect(connecte) { if (connecte) charger() }

    val entree = liste?.projets?.firstOrNull { it.cwd == cwd }
    Column(Modifier.fillMaxSize()) {
        BarreHaut(entree?.name ?: Format.base(cwd), cwd, retour = retour, actions = {
            if (entree?.exists != false) androidx.compose.material3.IconButton(onClick = { ouvrirTerminal(cwd) }) {
                Icon(Icons.Filled.Terminal, "Terminal dans ce projet")
            }
        })
        androidx.compose.material3.PrimaryScrollableTabRow(selectedTabIndex = onglet, edgePadding = 8.dp) {
            listOf("Conversations", "Feuille de route", "Fichiers", "Git").forEachIndexed { i, t ->
                androidx.compose.material3.Tab(selected = onglet == i, onClick = { onglet = i }, text = { Text(t) })
            }
        }
        if (onglet == 1) com.mawena.ccs.ui.travail.PanneauFeuilleDeRoute(modele, cwd, nouveauChat = { t -> ouvrirChat(DestChat.nouveauAvec(cwd, t)) })
        else if (onglet == 2) com.mawena.ccs.ui.fichiers.PanneauFichiers(modele, cwd, ouvrirFichier)
        else if (onglet == 3) com.mawena.ccs.ui.git.PanneauGit(modele, cwd, ouvrirCommit = { ouvrirCommit(cwd, it) })
        else PullToRefreshBox(
            isRefreshing = charge && liste != null,
            onRefresh = { portee.launch { charger() } },
            modifier = Modifier.fillMaxSize(),
        ) {
            LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(bottom = 24.dp)) {
                item {
                    Card(
                        Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp),
                        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceContainer),
                    ) {
                        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                            val c = compte
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                Icon(Icons.Filled.AccountCircle, null, tint = MaterialTheme.colorScheme.primary)
                                Spacer(Modifier.width(8.dp))
                                Column(Modifier.weight(1f)) {
                                    val nom = c?.preferred ?: entree?.profile
                                    Text(
                                        if (nom != null) "Compte : $nom" else "Compte : ${c?.active ?: "…"} (actif)",
                                        fontWeight = FontWeight.SemiBold,
                                    )
                                    c?.hint?.takeIf { it.isNotBlank() }?.let {
                                        Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                                    }
                                }
                            }
                            entree?.let { p ->
                                Text(
                                    "${p.total} conversation(s)" + (if (p.open > 0) " · ${p.open} ouverte(s)" else "") +
                                        (if (!p.exists) " · dossier absent" + (p.deplaceVers?.let { " (déplacé vers $it ?)" } ?: "") else ""),
                                    style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
                                )
                            }
                            Button(onClick = { nouvelle = true }, enabled = entree?.exists != false, modifier = Modifier.fillMaxWidth()) {
                                Icon(Icons.Filled.AddComment, null)
                                Spacer(Modifier.width(8.dp))
                                Text("Nouveau chat")
                            }
                        }
                    }
                }
                item { TitreSection("Conversations", Modifier.padding(horizontal = 16.dp)) }
                val l = liste
                when {
                    l == null && erreur != null -> item { EtatErreur(erreur!!) { portee.launch { charger() } } }
                    l == null -> item { Chargement() }
                    l.conversations.isEmpty() -> item { EtatVide("Pas encore de conversation dans ce projet.") }
                    else -> {
                        items(l.conversations.take(montres), key = { it.path }) { c ->
                            LigneConversation(
                                modele, c, ouverte = c.sessionId in ouvertes, montrerProjet = false,
                                surOuvrir = { ouvrirChat(DestChat(c.cwd, c.sessionId, c.path, c.titre)) },
                                surMenu = { actions.menu = c },
                            )
                        }
                        if (l.conversations.size > montres) item {
                            TextButton(onClick = { montres += PAS }, Modifier.padding(horizontal = 8.dp)) {
                                Text("Voir plus (${l.conversations.size - montres})")
                            }
                        }
                    }
                }
            }
        }
    }

    ActionsConversation(
        modele, actions,
        ouvrir = { c -> ouvrirChat(DestChat(c.cwd, c.sessionId, c.path, c.titre)) },
        changee = { portee.launch { charger() } },
    )
    if (nouvelle) {
        FeuilleNouvelleSession(
            modele, connus = listOf(cwd), initial = cwd,
            fermer = { nouvelle = false },
            ouvert = { r, chemin ->
                nouvelle = false
                ouvrirChat(DestChat(r.cwd.ifEmpty { chemin }, r.sessionId, r.path, Format.base(r.cwd.ifEmpty { chemin }), r.chatId))
            },
        )
    }
}
