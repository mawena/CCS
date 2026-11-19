package com.mawena.ccs.ui.chat

import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyListState
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Label
import androidx.compose.material.icons.filled.AccountTree
import androidx.compose.material.icons.filled.Checklist
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.History
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material.icons.filled.Terminal
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.material.icons.filled.Folder
import androidx.compose.material.icons.filled.KeyboardArrowDown
import androidx.compose.material.icons.filled.KeyboardArrowUp
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.SmartToy
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.SmallFloatingActionButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextField
import androidx.compose.material3.TextFieldDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import androidx.lifecycle.repeatOnLifecycle
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.mawena.ccs.logique.Citation
import com.mawena.ccs.logique.ElementFil
import com.mawena.ccs.logique.LigneFil
import com.mawena.ccs.logique.LiensFichiers
import com.mawena.ccs.logique.Recherche
import com.mawena.ccs.logique.BarreAgents
import com.mawena.ccs.logique.StatutAgent
import com.mawena.ccs.logique.Format
import com.mawena.ccs.ui.BarreHaut
import com.mawena.ccs.ui.DestChat
import com.mawena.ccs.ui.EtatErreur
import com.mawena.ccs.ui.LocalAvis
import com.mawena.ccs.ui.ModeleAppli
import com.mawena.ccs.ui.Reussite
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

private val ETATS = mapOf(
    "busy" to "Claude travaille…", "starting" to "Démarrage…", "permission" to "Attend ta réponse",
    "suspended" to "En veille", "stopped" to "Arrêté",
)

/**
 * Écran Chat (`ChatView` de `web/chat.js`) : fil en direct (le plus récent en bas, liste inversée :
 * seul l'élément qui change se redessine), sous-agents en pastilles, recherche, étiquettes,
 * citation, options, saisie avec images et commandes `/` et `!`.
 */
@Composable
fun EcranChat(
    modele: ModeleAppli,
    dest: DestChat,
    retour: () -> Unit,
    ouvrirFichier: (String, Int?) -> Unit = { _, _ -> },
    ouvrirFichiers: (String) -> Unit = {},
    ouvrirGit: (String) -> Unit = {},
    ouvrirChat: (DestChat) -> Unit = {},
    ouvrirTerminal: (String) -> Unit = {},
) {
    val mc: ModeleChat = viewModel(key = dest.route()) { ModeleChat(modele.depot, dest) }
    val vue by mc.vue.collectAsStateWithLifecycle()
    val etiquettes by mc.etiquettes.collectAsStateWithLifecycle()
    val avis = LocalAvis.current
    val portee = rememberCoroutineScope()
    LaunchedEffect(mc) {
        mc.messages.collect { m -> avis.dire(m.texte, m.action, long = m.action != null) { m.faire?.invoke() } }
    }
    // chat à l'écran (appli au premier plan) : pas de notification pour lui
    val cycle = androidx.lifecycle.compose.LocalLifecycleOwner.current
    LaunchedEffect(mc, cycle) {
        cycle.repeatOnLifecycle(androidx.lifecycle.Lifecycle.State.RESUMED) {
            var vu: String? = null
            try {
                mc.idChat.collect { vu = it; modele.depot.veille.afficher(it) }
            } finally {
                modele.depot.veille.quitter(vu)
            }
        }
    }
    com.mawena.ccs.ui.DemandeNotifications(modele)

    var choisi by remember { mutableStateOf<MessageChoisi?>(null) }
    var passage by remember { mutableStateOf<MessageChoisi?>(null) }
    var aEtiqueter by remember { mutableStateOf<MessageChoisi?>(null) }
    var voletEtiquettes by remember { mutableStateOf(false) }
    var filtreEtiquette by remember { mutableStateOf<String?>(null) }
    var recherche by remember { mutableStateOf<String?>(null) }
    var trouves by remember { mutableStateOf<List<String>>(emptyList()) }
    var position by remember { mutableIntStateOf(-1) }
    val defile = rememberLazyListState()
    var menuChat by remember { mutableStateOf(false) }
    var volet by remember { mutableStateOf<Volet?>(null) }

    val actions = remember(mc) {
        ActionsFil(
            menuMessage = { e -> choisi = MessageChoisi.de(e) },
            voirAgent = { mc.voirAgent(it) },
            repondre = { id, d, motif -> mc.repondre(id, d, motif) },
            questions = { id, r -> mc.repondreQuestions(id, r) },
            arreterShell = { mc.arreterShell(it) },
            reprendre = { mc.reprendre() },
            compacter = { mc.envoyerTexte("/compact") },
            voirEtiquette = { filtreEtiquette = it; voletEtiquettes = true },
        )
    }

    suspend fun allerA(cle: String, liste: List<LigneFil>, etat: LazyListState) {
        val i = liste.indexOfFirst { it.cle == cle }
        if (i >= 0) etat.animateScrollToItem(liste.size - 1 - i)
    }

    /** Ligne qui montre le message `msgId` (pour revenir à un message étiqueté). */
    fun ligneDuMessage(msgId: String, liste: List<LigneFil>): String? = liste.firstOrNull { l ->
        val e = (l as? LigneFil.Seul)?.element
        (e is ElementFil.MsgToi && e.msgId == msgId) || (e is ElementFil.MsgClaude && e.msgId == msgId)
    }?.cle

    val fichiers by mc.fichiers.collectAsStateWithLifecycle()
    LaunchedEffect(vue.pret, vue.etat) { if (vue.pret && vue.etat != "busy") mc.chargerFichiers() }
    val ouvre = remember(fichiers, mc.cwd) { OuvreFichier(LiensFichiers(mc.cwd, fichiers), ouvrirFichier) }

    val titre = dest.titre ?: Format.base(mc.cwd)
    CompositionLocalProvider(LocalOuvreFichier provides ouvre) {
    Column(Modifier.fillMaxSize().imePadding()) {
        BarreHaut(
            titre, ETATS[vue.etat]?.takeIf { vue.pret } ?: Format.base(mc.cwd), retour = retour,
            actions = {
                IconButton(onClick = { recherche = if (recherche == null) "" else null; trouves = emptyList(); position = -1 }) {
                    Icon(Icons.Filled.Search, "Chercher dans le fil")
                }
                IconButton(onClick = { filtreEtiquette = null; voletEtiquettes = true }) {
                    Icon(Icons.AutoMirrored.Filled.Label, "Étiquettes")
                }
                IconButton(onClick = { menuChat = true }) { Icon(Icons.Filled.MoreVert, "Plus") }
                androidx.compose.material3.DropdownMenu(menuChat, { menuChat = false }) {
                    androidx.compose.material3.DropdownMenuItem({ Text("Fichiers du projet") }, leadingIcon = { Icon(Icons.Filled.Folder, null) },
                        onClick = { menuChat = false; ouvrirFichiers(mc.cwd) })
                    androidx.compose.material3.DropdownMenuItem({ Text("Git du projet") }, leadingIcon = { Icon(Icons.Filled.AccountTree, null) },
                        onClick = { menuChat = false; ouvrirGit(mc.cwd) })
                    androidx.compose.material3.DropdownMenuItem({ Text("Changements de la session") }, leadingIcon = { Icon(Icons.Filled.History, null) },
                        onClick = { menuChat = false; volet = Volet.Changements })
                    androidx.compose.material3.DropdownMenuItem({ Text("Feuille de route") }, leadingIcon = { Icon(Icons.Filled.Checklist, null) },
                        onClick = { menuChat = false; volet = Volet.Feuille })
                    androidx.compose.material3.DropdownMenuItem({ Text("Terminal dans ce projet") }, leadingIcon = { Icon(Icons.Filled.Terminal, null) },
                        onClick = { menuChat = false; ouvrirTerminal(mc.cwd) })
                }
            },
        )
        vue.ouverture?.let { err ->
            EtatErreur("Le chat ne s'ouvre pas : $err") { mc.reessayerOuverture() }
            return@Column
        }
        recherche?.let { q ->
            BarreRecherche(
                q, trouves.size, position,
                changer = { recherche = it },
                aller = { sens ->
                    if (trouves.isNotEmpty()) {
                        position = Recherche.pas(position, trouves.size, sens)
                        portee.launch { allerA(trouves[position], vue.lignes, defile) }
                    }
                },
                fermer = { recherche = null; trouves = emptyList(); position = -1 },
            )
            LaunchedEffect(q) {
                delay(250)
                if (q.isBlank()) { trouves = emptyList(); position = -1; return@LaunchedEffect }
                mc.chargerToutHistorique()
                val l = mc.vue.value.lignes
                trouves = Recherche.trouver(l.map(LigneFil::texte), q).map { l[it].cle }
                position = trouves.size - 1                 // on part du plus récent
                if (position >= 0) { mc.voirAgent(null); allerA(trouves[position], mc.vue.value.lignes, defile) }
            }
        }
        if (vue.agents.isNotEmpty()) PastillesAgents(vue) { mc.voirAgent(it) }

        val enAgent = vue.agentVu != null
        val lignes = if (enAgent) vue.lignesAgent else vue.lignes
        val etatListe = if (enAgent) remember(vue.agentVu) { LazyListState() } else defile
        val courant = trouves.getOrNull(position)
        Box(Modifier.weight(1f).fillMaxWidth()) {
            if (!vue.pret && lignes.isEmpty()) {
                CircularProgressIndicator(Modifier.align(Alignment.Center))
            }
            val inverse = remember(lignes) { lignes.asReversed() }
            LazyColumn(
                Modifier.fillMaxSize(), state = etatListe, reverseLayout = true,
                contentPadding = PaddingValues(horizontal = 10.dp, vertical = 10.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp, Alignment.Bottom),
            ) {
                items(inverse, key = { it.cle }, contentType = { typeDe(it) }) { l ->
                    val msgId = when (val e = (l as? LigneFil.Seul)?.element) {
                        is ElementFil.MsgToi -> e.msgId
                        is ElementFil.MsgClaude -> e.msgId
                        else -> ""
                    }
                    LigneVue(l, if (msgId.isNotEmpty()) etiquettes[msgId]?.etiquettes else null, l.cle == courant, actions)
                }
                if (!enAgent && !vue.historiqueComplet) item(key = "plus") {
                    Box(Modifier.fillMaxWidth(), contentAlignment = Alignment.Center) {
                        OutlinedButton(onClick = { mc.chargerPlus() }) { Text("Messages plus anciens") }
                    }
                }
                if (enAgent && lignes.isEmpty()) item(key = "vide") {
                    Text("Ce sous-agent n'a encore rien écrit.", Modifier.padding(16.dp), color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
            val loin by remember(etatListe) { derivedStateOf { etatListe.firstVisibleItemIndex > 1 } }
            if (loin) {
                SmallFloatingActionButton(
                    onClick = { portee.launch { etatListe.animateScrollToItem(0) } },
                    modifier = Modifier.align(Alignment.BottomEnd).padding(12.dp),
                ) { Icon(Icons.Filled.KeyboardArrowDown, "Aller en bas") }
            }
        }
        // nouveau message envoyé, ou fil lu jusqu'en bas : on suit le bas
        val dernier = vue.lignes.lastOrNull()?.cle
        LaunchedEffect(dernier) {
            if (!enAgent && (defile.firstVisibleItemIndex <= 1 || (vue.lignes.lastOrNull() as? LigneFil.Seul)?.element is ElementFil.MsgToi)) {
                defile.scrollToItem(0)
            }
        }
        VueTaches(vue.taches)
        BandeauEtat(vue)
        Saisie(mc, vue, modele)
    }
    }

    volet?.let { v ->
        VoletChat(if (v == Volet.Changements) "Changements de la session" else "Feuille de route", fermer = { volet = null }) {
            if (v == Volet.Changements) {
                com.mawena.ccs.ui.travail.PanneauChangements(modele, mc.chatId, mc.cwd, ouvrirFichier = { volet = null; ouvrirFichier(it, null) },
                    change = { mc.chargerFichiers() })
            } else {
                com.mawena.ccs.ui.travail.PanneauFeuilleDeRoute(
                    modele, mc.cwd,
                    dansCeChat = { t -> volet = null; mc.envoyerTexte(t) },
                    nouveauChat = { t -> volet = null; ouvrirChat(DestChat.nouveauAvec(mc.cwd, t)) },
                )
            }
        }
    }

    choisi?.let { m ->
        MenuMessage(
            m, fermer = { choisi = null },
            repondre = { Citation.de(m.auteur, m.brut)?.let(mc::citer); choisi = null },
            passage = { passage = m; choisi = null },
            etiqueter = {
                choisi = null
                if (mc.sessionId == null || m.msgId.isEmpty()) avis.dire("Ce message ne peut pas encore être étiqueté : attends que Claude ait commencé la conversation.")
                else aEtiqueter = m
            },
        )
    }
    passage?.let { m -> DialoguePassage(m, fermer = { passage = null }) { mc.citer(it) } }
    aEtiqueter?.let { m ->
        DialogueEtiquettes(
            etiquettes[m.msgId]?.etiquettes.orEmpty(), mc.connues, Citation.uneLigne(m.texte, 160),
            fermer = { aEtiqueter = null },
        ) { tags ->
            aEtiqueter = null
            mc.etiqueter(m.msgId, tags, m.texte, if (m.auteur == Citation.Auteur.Moi) "utilisateur" else "assistant")
        }
    }
    if (voletEtiquettes) {
        FeuilleEtiquettes(etiquettes, filtreEtiquette, fermer = { voletEtiquettes = false }) { id ->
            voletEtiquettes = false
            mc.voirAgent(null)
            portee.launch {
                var cle = ligneDuMessage(id, mc.vue.value.lignes)
                if (cle == null) { mc.chargerToutHistorique(); cle = ligneDuMessage(id, mc.vue.value.lignes) }
                if (cle == null) avis.dire("Ce message n'est plus dans le fil (conversation compactée ou reprise ailleurs).")
                else { trouves = listOf(cle); position = 0; allerA(cle, mc.vue.value.lignes, defile) }
            }
        }
    }
}

private enum class Volet { Changements, Feuille }

/** Volet plein écran du chat (le tiroir de la version web). */
@OptIn(androidx.compose.material3.ExperimentalMaterial3Api::class)
@Composable
private fun VoletChat(titre: String, fermer: () -> Unit, contenu: @Composable () -> Unit) {
    androidx.compose.material3.ModalBottomSheet(
        onDismissRequest = fermer,
        sheetState = androidx.compose.material3.rememberModalBottomSheetState(skipPartiallyExpanded = true),
    ) {
        Column(Modifier.fillMaxWidth().fillMaxHeight(0.92f)) {
            Text(titre, Modifier.padding(horizontal = 16.dp, vertical = 4.dp), style = MaterialTheme.typography.titleMedium)
            Box(Modifier.weight(1f)) { contenu() }
        }
    }
}

private fun typeDe(l: LigneFil): Int = when (l) {
    is LigneFil.Groupe -> 0
    is LigneFil.Seul -> when (l.element) {
        is ElementFil.MsgToi -> 1
        is ElementFil.MsgClaude -> 2
        is ElementFil.Outil -> 3
        else -> 4
    }
}

@Composable
private fun BarreRecherche(q: String, nombre: Int, position: Int, changer: (String) -> Unit, aller: (Int) -> Unit, fermer: () -> Unit) {
    val focus = remember { FocusRequester() }
    LaunchedEffect(Unit) { focus.requestFocus() }
    Surface(color = MaterialTheme.colorScheme.surfaceContainerHigh) {
        Row(Modifier.fillMaxWidth().padding(horizontal = 4.dp), verticalAlignment = Alignment.CenterVertically) {
            TextField(
                q, changer, Modifier.weight(1f).focusRequester(focus), singleLine = true,
                placeholder = { Text("Chercher dans le fil") },
                colors = TextFieldDefaults.colors(focusedContainerColor = Color.Transparent, unfocusedContainerColor = Color.Transparent),
            )
            Text(
                when { q.isBlank() -> ""; nombre == 0 -> "Rien"; else -> "${position + 1}/$nombre" },
                style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            IconButton(onClick = { aller(-1) }) { Icon(Icons.Filled.KeyboardArrowUp, "Précédent") }
            IconButton(onClick = { aller(1) }) { Icon(Icons.Filled.KeyboardArrowDown, "Suivant") }
            IconButton(onClick = fermer) { Icon(Icons.Filled.Close, "Fermer la recherche") }
        }
    }
}

/**
 * Pastilles : « Conversation », les sous-agents au travail (et celui qu'on regarde), puis
 * « Terminés (n) » au bout : la liste des sous-agents finis, le plus récent en tête, qui rouvre leur vue.
 */
@Composable
private fun PastillesAgents(vue: VueChat, voir: (String?) -> Unit) {
    val termines = BarreAgents.termines(vue.agents)
    var liste by remember { mutableStateOf(false) }
    Row(
        Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()).padding(horizontal = 8.dp),
        horizontalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        FilterChip(vue.agentVu == null, { voir(null) }, { Text("Conversation") })
        BarreAgents.pastilles(vue.agents, vue.agentVu).forEach { a ->
            FilterChip(
                vue.agentVu == a.id, { voir(a.id) }, { Text(a.nom, maxLines = 1) },
                leadingIcon = { MarqueAgent(a.statut) },
                trailingIcon = { Icon(Icons.Filled.SmartToy, null, Modifier.size(14.dp)) },
            )
        }
        if (termines.isNotEmpty()) Box {
            FilterChip(liste, { liste = !liste }, { Text("Terminés (${termines.size})") })
            DropdownMenu(liste, { liste = false }) {
                termines.forEach { a ->
                    DropdownMenuItem(
                        text = {
                            Column {
                                Text(a.nom, maxLines = 1, overflow = androidx.compose.ui.text.style.TextOverflow.Ellipsis)
                                Text(
                                    if (a.statut == StatutAgent.Arrete) "arrêté" else "✓ terminé",
                                    style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
                                )
                            }
                        },
                        leadingIcon = { MarqueAgent(a.statut) },
                        onClick = { liste = false; voir(a.id) },
                    )
                }
            }
        }
    }
}

@Composable
private fun MarqueAgent(s: StatutAgent) {
    when (s) {
        StatutAgent.Travaille -> CircularProgressIndicator(Modifier.size(14.dp), strokeWidth = 2.dp)
        StatutAgent.Fini -> Text("✓", color = Reussite)
        StatutAgent.Arrete -> Text("■", color = MaterialTheme.colorScheme.error)
    }
}
