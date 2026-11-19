package com.mawena.ccs.ui.git

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Checkbox
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.SegmentedButton
import androidx.compose.material3.SegmentedButtonDefaults
import androidx.compose.material3.SingleChoiceSegmentedButtonRow
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.mawena.ccs.logique.Format
import com.mawena.ccs.logique.GitVue
import com.mawena.ccs.reseau.CommitGit
import com.mawena.ccs.reseau.DiffGit
import com.mawena.ccs.reseau.EtatConnexion
import com.mawena.ccs.reseau.EtatGit
import com.mawena.ccs.reseau.FichierGit
import com.mawena.ccs.reseau.JournalGit
import com.mawena.ccs.reseau.RefsGit
import com.mawena.ccs.reseau.ReponseDiff
import com.mawena.ccs.ui.Chargement
import com.mawena.ccs.ui.Demandes
import com.mawena.ccs.ui.EtatErreur
import com.mawena.ccs.ui.EtatVide
import com.mawena.ccs.ui.LocalAvis
import com.mawena.ccs.ui.ModeleAppli
import com.mawena.ccs.ui.TitreSection
import com.mawena.ccs.ui.VueDemandes
import com.mawena.ccs.ui.chat.CorpsDiff
import com.mawena.ccs.ui.fichiers.couleurMarque
import com.mawena.ccs.ui.texte
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonObjectBuilder
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import kotlinx.serialization.json.putJsonArray
import kotlinx.serialization.json.add

private enum class Vue(val titre: String) { Changements("Changements"), Historique("Historique"), Branches("Branches") }

/** Diff ouvert : `null` pendant le chargement. */
private class Ouvert(val diff: DiffGit?)

/**
 * Git d'un projet (`web/git.js`) : branche et suivi, fetch / pull / push (confirmés, push forcé à
 * part), fichiers indexés / modifiés / non suivis, diff dépliable, indexation par fichier et par
 * morceau, commit (message proposé, amend confirmé), historique par pages et branches.
 */
@OptIn(ExperimentalMaterial3Api::class, ExperimentalLayoutApi::class)
@Composable
fun PanneauGit(modele: ModeleAppli, cwd: String, ouvrirCommit: (String) -> Unit, modifier: Modifier = Modifier) {
    val client = modele.depot.client
    val etat by modele.etat.collectAsStateWithLifecycle()
    val connecte = etat is EtatConnexion.Connecte
    val avis = LocalAvis.current
    val portee = rememberCoroutineScope()
    val demandes = remember { Demandes() }

    var vue by rememberSaveable { mutableStateOf(Vue.Changements) }
    var statut by remember(cwd) { mutableStateOf<EtatGit?>(null) }
    var erreur by remember { mutableStateOf<String?>(null) }
    var charge by remember { mutableStateOf(false) }
    val ouverts = remember(cwd) { mutableStateMapOf<String, Ouvert>() }
    var journal by remember(cwd) { mutableStateOf<JournalGit?>(null) }
    var refs by remember(cwd) { mutableStateOf<RefsGit?>(null) }
    var travail by remember { mutableStateOf<String?>(null) }
    var message by rememberSaveable(cwd) { mutableStateOf("") }
    var amend by rememberSaveable(cwd) { mutableStateOf(false) }
    var menu by remember { mutableStateOf(false) }

    fun params(plus: JsonObjectBuilder.() -> Unit = {}): JsonObject = buildJsonObject { put("cwd", cwd); plus() }

    suspend fun chargerDiff(cle: String) {
        val cote = cle.substringBefore(':')
        val chemin = cle.substringAfter(':')
        try {
            val r = client.appeler("git.diff", ReponseDiff.serializer(), params {
                put("path", chemin); put("staged", cote == GitVue.Cote.Index.name)
            })
            ouverts[cle] = Ouvert(r.diff ?: DiffGit(path = chemin))
        } catch (e: Exception) {
            ouverts.remove(cle)
            avis.dire(e.texte())
        }
    }

    suspend fun chargerJournal(depuisDebut: Boolean) {
        val deja = if (depuisDebut) emptyList() else journal?.commits.orEmpty()
        try {
            val r = client.appeler("git.log", JournalGit.serializer(), params { put("skip", deja.size) })
            journal = JournalGit(deja + r.commits, r.more)
        } catch (e: Exception) {
            avis.dire(e.texte())
        }
    }

    suspend fun actualiser() {
        charge = true
        try {
            val s = client.appeler("git.status", EtatGit.serializer(), params())
            statut = s
            erreur = null
            val garder = GitVue.clesGardees(ouverts.keys, s)
            ouverts.keys.filter { it !in garder }.forEach { ouverts.remove(it) }
            coroutineScope { garder.map { async { chargerDiff(it) } }.awaitAll() }
            if (vue == Vue.Historique) chargerJournal(true)
            if (vue == Vue.Branches) refs = runCatching { client.appeler("git.refs", RefsGit.serializer(), params()) }.getOrNull()
        } catch (e: Exception) {
            erreur = e.texte()
        }
        charge = false
    }

    LaunchedEffect(connecte, cwd) { if (connecte) actualiser() }
    LaunchedEffect(vue, connecte) {
        if (!connecte) return@LaunchedEffect
        if (vue == Vue.Historique && journal == null) chargerJournal(true)
        if (vue == Vue.Branches && refs == null) {
            refs = runCatching { client.appeler("git.refs", RefsGit.serializer(), params()) }.onFailure { avis.dire(it.texte()) }.getOrNull()
        }
    }

    /** Écriture (une à la fois), puis actualisation. Rend vrai si elle a réussi. */
    fun agir(libelle: String, fait: String = "", action: suspend () -> Unit, apres: () -> Unit = {}) {
        if (travail != null) return
        portee.launch {
            travail = libelle
            var ok = false
            try {
                action()
                ok = true
                if (fait.isNotEmpty()) avis.dire(fait)
            } catch (e: Exception) {
                avis.dire(e.texte(), long = true)
            }
            travail = null
            if (ok) apres()
            actualiser()
        }
    }

    fun indexer(methode: String, chemins: List<String>) = agir(if (methode == "git.stage") "Indexation…" else "Désindexation…", action = {
        client.appeler(methode, params { putJsonArray("paths") { chemins.forEach { add(it) } } })
    })

    fun reseau(methode: String, force: Boolean = false) {
        val b = statut?.branch ?: return
        portee.launch {
            val (titre, texte, bouton) = when (methode) {
                "git.fetch" -> Triple("Fetch ?", "Récupère les nouveautés du dépôt distant, sans rien changer à ta branche.", "Fetch")
                "git.pull" -> Triple(if (b.name != null) "Pull sur « ${b.name} » ?" else "Pull ?", GitVue.textePull(b), "Pull")
                else -> if (force) Triple("Push forcé ?", "Le dépôt distant sera écrasé par ta branche (avec garde-fou : refusé si quelqu'un a poussé entre-temps).", "Pousser de force")
                else Triple(if (b.name != null) "Pousser « ${b.name} » ?" else "Pousser ?", GitVue.textePush(b), "Pousser")
            }
            if (!demandes.confirmer(titre, texte, bouton, danger = force)) return@launch
            val nom = when (methode) { "git.fetch" -> "Fetch"; "git.pull" -> "Pull"; else -> if (force) "Push forcé" else "Push" }
            agir("$nom en cours…", "$nom terminé.", action = {
                client.appeler(methode, params { if (methode == "git.push") put("force", force) }, delaiMs = 320_000)
            })
        }
    }

    fun commit() {
        if (message.isBlank()) { avis.dire("Écris le message du commit."); return }
        portee.launch {
            if (amend && !demandes.confirmer("Modifier le dernier commit ?",
                    "Son contenu et son message seront remplacés. Si tu l'as déjà poussé, il faudra un push forcé.", "Modifier")) return@launch
            val a = amend
            agir("Commit…", if (a) "Commit modifié." else "Commit créé.", action = {
                client.appeler("git.commit", params { put("message", message); put("amend", a) }, delaiMs = 120_000)
            }, apres = { message = ""; amend = false; journal = null })
        }
    }

    val s = statut
    Column(modifier.fillMaxSize()) {
        travail?.let { t ->
            Column(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 4.dp)) {
                Text(t, style = MaterialTheme.typography.bodySmall)
                LinearProgressIndicator(Modifier.fillMaxWidth())
            }
        }
        when {
            s == null && erreur != null -> EtatErreur(erreur!!) { portee.launch { actualiser() } }
            s == null -> Chargement()
            !s.repo -> EtatVide("Ce dossier n'est pas un dépôt git.")
            else -> PullToRefreshBox(isRefreshing = charge, onRefresh = { portee.launch { actualiser() } }, modifier = Modifier.fillMaxSize()) {
                LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(bottom = 32.dp)) {
                    item {
                        Card(
                            Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 8.dp),
                            colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceContainer),
                        ) {
                            Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                                Row(verticalAlignment = Alignment.CenterVertically) {
                                    Column(Modifier.weight(1f)) {
                                        Text(s.branch.name ?: "HEAD détachée", fontWeight = FontWeight.SemiBold, fontFamily = FontFamily.Monospace)
                                        Text(GitVue.synchro(s.branch), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                                    }
                                    androidx.compose.foundation.layout.Box {
                                        IconButton(onClick = { menu = true }) { Icon(Icons.Filled.MoreVert, "Plus d'actions Git") }
                                        DropdownMenu(menu, { menu = false }) {
                                            DropdownMenuItem(text = { Text("Push forcé…") }, onClick = { menu = false; reseau("git.push", force = true) })
                                            DropdownMenuItem(text = { Text("Actualiser") }, onClick = { menu = false; portee.launch { actualiser() } })
                                        }
                                    }
                                }
                                FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                    val libre = travail == null
                                    OutlinedButton(onClick = { reseau("git.fetch") }, enabled = libre) { Text("Fetch") }
                                    OutlinedButton(onClick = { reseau("git.pull") }, enabled = libre) { Text(if (s.branch.behind > 0) "Pull ↓${s.branch.behind}" else "Pull") }
                                    OutlinedButton(onClick = { reseau("git.push") }, enabled = libre) { Text(if (s.branch.ahead > 0) "Push ↑${s.branch.ahead}" else "Push") }
                                }
                            }
                        }
                    }
                    item {
                        SingleChoiceSegmentedButtonRow(Modifier.fillMaxWidth().padding(horizontal = 12.dp)) {
                            Vue.entries.forEachIndexed { i, v ->
                                SegmentedButton(selected = vue == v, onClick = { vue = v }, shape = SegmentedButtonDefaults.itemShape(i, Vue.entries.size)) {
                                    Text(v.titre, maxLines = 1)
                                }
                            }
                        }
                    }
                    when (vue) {
                        Vue.Changements -> changements(
                            s, ouverts, travail == null,
                            basculer = { cle ->
                                if (ouverts.containsKey(cle)) ouverts.remove(cle)
                                else { ouverts[cle] = Ouvert(null); portee.launch { chargerDiff(cle) } }
                            },
                            indexer = ::indexer,
                            morceau = { f, cote, i, entete ->
                                agir(if (cote == GitVue.Cote.Index) "Désindexation du morceau…" else "Indexation du morceau…", action = {
                                    client.appeler("git.hunk", params {
                                        put("path", f.path); put("index", i); put("header", entete)
                                        put("action", if (cote == GitVue.Cote.Index) "unstage" else "stage")
                                    })
                                })
                            },
                        )
                        Vue.Historique -> historique(journal, ouvrirCommit) { portee.launch { chargerJournal(false) } }
                        Vue.Branches -> branches(refs)
                    }
                    if (vue == Vue.Changements) item {
                        Column(Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 8.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                            TitreSection("Commit")
                            OutlinedTextField(message, { message = it }, Modifier.fillMaxWidth(), minLines = 3, placeholder = { Text("Message du commit") })
                            Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.clickable {
                                amend = !amend
                                if (amend && message.isBlank()) message = s.dernierMessage
                            }) {
                                Checkbox(amend, { amend = it; if (it && message.isBlank()) message = s.dernierMessage })
                                Text("Modifier le dernier commit (amend)", style = MaterialTheme.typography.bodyMedium)
                            }
                            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                Button(onClick = ::commit, enabled = travail == null && GitVue.peutCommit(s, amend)) { Text("Commit") }
                                if (s.proposed.isNotBlank()) TextButton(onClick = { message = s.proposed }, enabled = travail == null) { Text("Message proposé") }
                            }
                        }
                    }
                }
            }
        }
    }
    VueDemandes(demandes)
}

private fun LazyListScope.changements(
    s: EtatGit,
    ouverts: Map<String, Ouvert>,
    libre: Boolean,
    basculer: (String) -> Unit,
    indexer: (String, List<String>) -> Unit,
    morceau: (FichierGit, GitVue.Cote, Int, String) -> Unit,
) {
    val groupes = GitVue.groupes(s)
    if (groupes.isEmpty()) { item { EtatVide("Rien à valider : le dossier est propre.") }; return }
    if (s.truncated) item { EtatVide("Trop de fichiers : seuls les premiers sont montrés.") }
    for (g in groupes) {
        item(key = "g:${g.titre}") {
            TitreSection("${g.titre} (${g.fichiers.size})", Modifier.padding(horizontal = 12.dp)) {
                TextButton(onClick = { indexer(g.methode, g.fichiers.map { it.path }) }, enabled = libre) { Text(g.tout) }
            }
        }
        items(g.fichiers, key = { "${g.titre}:${it.path}" }) { f ->
            val cle = GitVue.cle(g.cote, f.path)
            val lettre = g.lettre(f)
            Column(Modifier.fillMaxWidth()) {
                Row(Modifier.fillMaxWidth().clickable { basculer(cle) }.padding(start = 12.dp), verticalAlignment = Alignment.CenterVertically) {
                    Text(lettre, Modifier.width(22.dp), color = couleurMarque(if (lettre == "?") "?" else lettre), fontWeight = FontWeight.Bold,
                        fontFamily = FontFamily.Monospace)
                    Column(Modifier.weight(1f)) {
                        Text(f.path.substringAfterLast('/'), maxLines = 1, overflow = TextOverflow.Ellipsis)
                        val dossier = f.path.substringBeforeLast('/', "")
                        Text(listOf(GitVue.marque(lettre), dossier).filter { it.isNotEmpty() }.joinToString(" · "),
                            style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1, overflow = TextOverflow.Ellipsis)
                    }
                    TextButton(onClick = { indexer(g.methode, listOf(f.path)) }, enabled = libre) { Text(g.verbe) }
                }
                ouverts[cle]?.let { o -> DiffOuvert(o.diff, f, g.cote, lettre, libre, morceau) }
            }
        }
    }
}

@Composable
private fun DiffOuvert(d: DiffGit?, f: FichierGit, cote: GitVue.Cote, lettre: String, libre: Boolean, morceau: (FichierGit, GitVue.Cote, Int, String) -> Unit) {
    Column(Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 4.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
        if (d == null) { Chargement("Chargement du diff…"); return@Column }
        val vide = GitVue.sansDiff(d)
        if (vide != null) { Text(vide, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant); return@Column }
        val parMorceau = GitVue.parMorceau(lettre, d)
        d.hunks.forEachIndexed { i, h ->
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(h.header, Modifier.weight(1f), fontFamily = FontFamily.Monospace, style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.primary, maxLines = 1, overflow = TextOverflow.Ellipsis)
                if (parMorceau) TextButton(onClick = { morceau(f, cote, i, h.header) }, enabled = libre) {
                    Text(if (cote == GitVue.Cote.Index) "Désindexer ce morceau" else "Indexer ce morceau", style = MaterialTheme.typography.labelMedium)
                }
            }
            CorpsDiff(remember(h) { GitVue.lignes(h) })
        }
        if (d.truncated) Text("Diff tronqué : seules les premières lignes sont montrées.", style = MaterialTheme.typography.bodySmall)
    }
}

private fun LazyListScope.historique(j: JournalGit?, ouvrir: (String) -> Unit, plus: () -> Unit) {
    when {
        j == null -> item { Chargement() }
        j.commits.isEmpty() -> item { EtatVide("Aucun commit pour l'instant.") }
        else -> {
            items(j.commits, key = { "c:" + it.id }) { c -> LigneCommit(c) { ouvrir(c.id) } }
            if (j.more) item {
                TextButton(onClick = plus, Modifier.padding(horizontal = 8.dp)) { Text("Plus de commits") }
            }
        }
    }
}

@Composable
private fun LigneCommit(c: CommitGit, surToucher: () -> Unit) {
    Column(Modifier.fillMaxWidth().clickable(onClick = surToucher).padding(horizontal = 16.dp, vertical = 8.dp)) {
        Text(c.subject, maxLines = 2, overflow = TextOverflow.Ellipsis, fontWeight = FontWeight.Medium)
        Text("${c.short} · ${c.author} · ${Format.ilYA(c.time.toDouble())}", style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1, overflow = TextOverflow.Ellipsis)
    }
}

private fun LazyListScope.branches(r: RefsGit?) {
    if (r == null) { item { Chargement() }; return }
    val tete = r.refs.firstOrNull { it.kind == "head" }?.target
    val groupes = GitVue.refs(r.refs)
    if (groupes.isEmpty()) { item { EtatVide("Aucune branche.") }; return }
    for ((titre, liste) in groupes) {
        item(key = "r:$titre") { TitreSection("$titre (${liste.size})", Modifier.padding(horizontal = 12.dp)) }
        items(liste, key = { "r:$titre:${it.name}" }) { x ->
            Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 6.dp), verticalAlignment = Alignment.CenterVertically) {
                Text(x.name, Modifier.weight(1f), fontFamily = FontFamily.Monospace, maxLines = 1, overflow = TextOverflow.Ellipsis,
                    fontWeight = if (x.kind == "branch" && x.target == tete) FontWeight.Bold else null)
                Text(x.target.take(8), fontFamily = FontFamily.Monospace, style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
    }
}
