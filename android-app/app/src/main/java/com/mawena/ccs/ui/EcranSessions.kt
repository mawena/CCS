package com.mawena.ccs.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.AddComment
import androidx.compose.material.icons.filled.Clear
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Folder
import androidx.compose.material.icons.filled.FolderOff
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExtendedFloatingActionButton
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.ListItem
import androidx.compose.material3.ListItemDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.mawena.ccs.logique.EtatChat
import com.mawena.ccs.logique.Format
import com.mawena.ccs.reseau.ChatOuvert
import com.mawena.ccs.reseau.EtatConnexion
import com.mawena.ccs.reseau.ListeChats
import com.mawena.ccs.reseau.ListeProjets
import com.mawena.ccs.reseau.Projet
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

private const val PAS_PROJETS = 40
private const val PAS_CONVERSATIONS = 60

/** Couleur de la pastille d'un état de chat (« En cours »). */
@Composable
fun couleurEtat(t: EtatChat.Ton): Color = when (t) {
    EtatChat.Ton.Occupe -> MaterialTheme.colorScheme.primary
    EtatChat.Ton.Attente -> Avertissement
    EtatChat.Ton.Pret -> Reussite
    EtatChat.Ton.Arret -> MaterialTheme.colorScheme.outline
}

/**
 * Sessions (`sessions.js`, version téléphone : une colonne) : « En cours » (chats ouverts dans le
 * pont, état en direct), projets, conversations récentes, recherche, corbeille, nouvelle session.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun EcranSessions(
    modele: ModeleAppli,
    ouvrirProjet: (String) -> Unit,
    ouvrirChat: (DestChat) -> Unit,
) {
    val client = modele.depot.client
    val etat by modele.etat.collectAsStateWithLifecycle()
    val avis = LocalAvis.current
    val portee = rememberCoroutineScope()
    var recherche by rememberSaveable { mutableStateOf("") }
    var liste by remember { mutableStateOf<ListeProjets?>(null) }
    var chats by remember { mutableStateOf<List<ChatOuvert>>(emptyList()) }
    val etats = remember { mutableStateMapOf<String, String>() }   // chat_id → état poussé en direct
    var erreur by remember { mutableStateOf<String?>(null) }
    var charge by remember { mutableStateOf(false) }
    var montresProjets by remember { mutableIntStateOf(PAS_PROJETS) }
    var montresConvs by remember { mutableIntStateOf(PAS_CONVERSATIONS) }
    var nouvelle by remember { mutableStateOf(false) }
    var nouvelleDans by remember { mutableStateOf("") }
    var ajouter by remember { mutableStateOf(false) }
    var corbeille by remember { mutableStateOf(false) }
    var aRetirer by remember { mutableStateOf<Projet?>(null) }
    var aFermer by remember { mutableStateOf<ChatOuvert?>(null) }
    val actions = remember { EtatActions() }
    val connecte = etat is EtatConnexion.Connecte

    suspend fun chargerChats() {
        runCatching { client.appeler("chat.list", ListeChats.serializer()) }.onSuccess {
            chats = it.chats
            etats.clear()
        }
    }

    suspend fun charger() {
        charge = true
        try {
            liste = client.appeler("projects.list", ListeProjets.serializer(), buildJsonObject { put("query", recherche) })
            erreur = null
        } catch (e: Exception) {
            erreur = e.texte()
        }
        charge = false
    }

    fun relire() { portee.launch { charger() } }

    LaunchedEffect(connecte) {
        if (connecte) { chargerChats(); charger() }
    }
    LaunchedEffect(recherche) {
        if (liste == null) return@LaunchedEffect
        delay(300)
        montresProjets = PAS_PROJETS
        montresConvs = PAS_CONVERSATIONS
        charger()
    }
    // État des chats en direct (StateChanged) ; un chat inconnu : la liste est relue.
    LaunchedEffect(Unit) {
        client.evenements("chat.event").collect { d ->
            val id = (d["chat_id"] as? JsonPrimitive)?.content ?: return@collect
            val ev = d["event"] as? JsonObject ?: return@collect
            if ((ev["type"] as? JsonPrimitive)?.content != "StateChanged") return@collect
            val s = (ev["state"] as? JsonPrimitive)?.content ?: return@collect
            if (chats.any { it.chatId == id }) etats[id] = s else chargerChats()
        }
    }

    val ouvertes = chats.mapNotNull { it.sessionId }.toSet()

    Box(Modifier.fillMaxSize()) {
        PullToRefreshBox(
            isRefreshing = charge && liste != null,
            onRefresh = { portee.launch { chargerChats(); charger() } },
            modifier = Modifier.fillMaxSize(),
        ) {
            LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(bottom = 96.dp)) {
                item {
                    OutlinedTextField(
                        recherche, { recherche = it }, singleLine = true,
                        placeholder = { Text("Rechercher une conversation") },
                        leadingIcon = { Icon(Icons.Filled.Search, null) },
                        trailingIcon = {
                            if (recherche.isNotEmpty()) IconButton(onClick = { recherche = "" }) { Icon(Icons.Filled.Clear, "Effacer la recherche") }
                        },
                        modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp),
                    )
                }
                if (chats.isNotEmpty()) {
                    item { TitreSection("En cours", Modifier.padding(horizontal = 16.dp)) }
                    items(chats, key = { "chat-" + it.chatId }) { ch ->
                        val e = EtatChat.de(etats[ch.chatId] ?: ch.state)
                        ListItem(
                            headlineContent = { Text(Format.base(ch.cwd), maxLines = 1, overflow = TextOverflow.Ellipsis) },
                            supportingContent = { Text("${e.libelle} · ${Format.base(ch.cwd)}") },
                            leadingContent = { Pastille(couleurEtat(e.ton), 12.dp) },
                            trailingContent = {
                                IconButton(onClick = { aFermer = ch }) { Icon(Icons.Filled.Close, "Fermer ${Format.base(ch.cwd)}") }
                            },
                            colors = ListItemDefaults.colors(containerColor = Color.Transparent),
                            modifier = Modifier.clickable {
                                ouvrirChat(DestChat(ch.cwd, ch.sessionId, ch.path, Format.base(ch.cwd), ch.chatId))
                            },
                        )
                    }
                    item { HorizontalDivider(Modifier.padding(vertical = 4.dp)) }
                }
                val l = liste
                when {
                    l == null && erreur != null -> item { EtatErreur(erreur!!) { relire() } }
                    l == null -> item { Chargement() }
                    l.projets.isEmpty() && l.conversations.isEmpty() -> item {
                        if (recherche.isNotBlank()) {
                            EtatVide("Rien trouvé pour « ${recherche.trim()} ».") {
                                OutlinedButton(onClick = { recherche = "" }) { Text("Effacer la recherche") }
                            }
                        } else {
                            EtatVide("Aucun projet ni conversation pour l'instant.")
                        }
                    }
                    else -> {
                        erreur?.let { m -> item { Text(m, Modifier.padding(horizontal = 16.dp), color = MaterialTheme.colorScheme.error) } }
                        item {
                            TitreSection("Projets", Modifier.padding(start = 16.dp, end = 8.dp)) {
                                TextButton(onClick = { ajouter = true }) {
                                    Icon(Icons.Filled.Add, null)
                                    Text("Ajouter")
                                }
                            }
                        }
                        val projets = l.projets
                        if (projets.isEmpty()) item { Text("Aucun projet ne correspond.", Modifier.padding(16.dp), color = MaterialTheme.colorScheme.onSurfaceVariant) }
                        items(projets.take(montresProjets), key = { "projet-" + it.cwd }) { p ->
                            LigneProjet(
                                p,
                                surOuvrir = { ouvrirProjet(p.cwd!!) },
                                surNouveauChat = { nouvelleDans = p.cwd!!; nouvelle = true },
                                surRetirer = { aRetirer = p },
                            )
                        }
                        if (projets.size > montresProjets) item {
                            TextButton(onClick = { montresProjets += PAS_PROJETS }, Modifier.padding(horizontal = 8.dp)) {
                                Text("Voir plus de projets (${projets.size - montresProjets})")
                            }
                        }
                        item { TitreSection("Conversations récentes", Modifier.padding(horizontal = 16.dp)) }
                        val convs = l.conversations
                        if (convs.isEmpty()) item {
                            Text(
                                if (recherche.isNotBlank()) "Aucune conversation ne correspond." else "Aucune conversation.",
                                Modifier.padding(16.dp), color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                        items(convs.take(montresConvs), key = { "conv-" + it.path }) { c ->
                            LigneConversation(
                                modele, c, ouverte = c.sessionId in ouvertes, montrerProjet = true,
                                surOuvrir = { ouvrirChat(DestChat(c.cwd, c.sessionId, c.path, c.titre)) },
                                surMenu = { actions.menu = c },
                            )
                        }
                        if (convs.size > montresConvs) item {
                            TextButton(onClick = { montresConvs += PAS_CONVERSATIONS }, Modifier.padding(horizontal = 8.dp)) {
                                Text("Voir plus de conversations (${convs.size - montresConvs})")
                            }
                        }
                        item {
                            TextButton(onClick = { corbeille = true }, Modifier.padding(horizontal = 8.dp, vertical = 8.dp)) {
                                Icon(Icons.Filled.Delete, null)
                                Text("Corbeille", Modifier.padding(start = 8.dp))
                            }
                        }
                    }
                }
            }
        }
        ExtendedFloatingActionButton(
            onClick = { nouvelleDans = ""; nouvelle = true },
            icon = { Icon(Icons.Filled.AddComment, null) },
            text = { Text("Nouvelle session") },
            modifier = Modifier.align(Alignment.BottomEnd).padding(16.dp),
        )
    }

    ActionsConversation(
        modele, actions,
        ouvrir = { c -> ouvrirChat(DestChat(c.cwd, c.sessionId, c.path, c.titre)) },
        changee = { relire() },
    )
    if (nouvelle) {
        FeuilleNouvelleSession(
            modele,
            connus = liste?.projets.orEmpty().filter { it.exists }.mapNotNull { it.cwd },
            initial = nouvelleDans,
            fermer = { nouvelle = false },
            ouvert = { r, chemin ->
                nouvelle = false
                portee.launch { chargerChats() }
                ouvrirChat(DestChat(r.cwd.ifEmpty { chemin }, r.sessionId, r.path, Format.base(r.cwd.ifEmpty { chemin }), r.chatId))
            },
        )
    }
    if (ajouter) DialogueAjouterProjet(modele, fermer = { ajouter = false }, ajoute = { ajouter = false; relire() })
    if (corbeille) DialogueCorbeille(modele, fermer = { corbeille = false }, changee = { relire() })
    aRetirer?.let { p ->
        Confirmation(
            titre = "Retirer « ${p.name} » de la liste ?",
            texte = "Le dossier et ses conversations ne sont pas effacés ; le projet revient dans la liste si une nouvelle conversation y démarre.",
            confirmer = "Retirer", danger = true,
            surNon = { aRetirer = null },
            surOui = {
                aRetirer = null
                portee.launch {
                    try {
                        client.appeler("projects.remove", buildJsonObject { put("cwd", p.cwd) })
                        avis.dire("« ${p.name} » retiré de la liste.")
                        charger()
                    } catch (e: Exception) {
                        avis.dire(e.texte())
                    }
                }
            },
        )
    }
    aFermer?.let { ch ->
        Confirmation(
            titre = "Fermer le chat « ${Format.base(ch.cwd)} » ?",
            texte = "Claude s'arrête ; la conversation reste dans l'historique.",
            confirmer = "Fermer", danger = true,
            surNon = { aFermer = null },
            surOui = {
                aFermer = null
                portee.launch {
                    runCatching { client.appeler("chat.close", buildJsonObject { put("chat_id", ch.chatId) }) }
                    chargerChats()
                }
            },
        )
    }
}

@Composable
private fun LigneProjet(p: Projet, surOuvrir: () -> Unit, surNouveauChat: () -> Unit, surRetirer: () -> Unit) {
    var menu by remember { mutableStateOf(false) }
    ListItem(
        headlineContent = {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                Text(p.name, Modifier.weight(1f, fill = false), maxLines = 1, overflow = TextOverflow.Ellipsis)
                p.profile?.let { Etiquette(it) }
            }
        },
        supportingContent = {
            Text("${p.total} conversation(s)" + (if (p.open > 0) " · ${p.open} ouverte(s)" else "") + (if (!p.exists) " · dossier absent" else ""))
        },
        leadingContent = {
            Icon(if (p.exists) Icons.Filled.Folder else Icons.Filled.FolderOff, null, tint = MaterialTheme.colorScheme.primary)
        },
        trailingContent = {
            Row {
                if (p.exists) IconButton(onClick = surNouveauChat) { Icon(Icons.Filled.AddComment, "Nouveau chat dans ${p.name}") }
                Box {
                    IconButton(onClick = { menu = true }) { Icon(Icons.Filled.MoreVert, "Actions pour ${p.name}") }
                    DropdownMenu(expanded = menu, onDismissRequest = { menu = false }) {
                        DropdownMenuItem(text = { Text("Retirer de la liste") }, onClick = { menu = false; surRetirer() })
                    }
                }
            }
        },
        colors = ListItemDefaults.colors(containerColor = Color.Transparent),
        modifier = Modifier.clickable(onClick = surOuvrir),
    )
}
