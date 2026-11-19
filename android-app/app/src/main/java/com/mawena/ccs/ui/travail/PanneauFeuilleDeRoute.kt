package com.mawena.ccs.ui.travail

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ExpandLess
import androidx.compose.material.icons.filled.ExpandMore
import androidx.compose.material3.Button
import androidx.compose.material3.Checkbox
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.mawena.ccs.logique.FeuilleRoute
import com.mawena.ccs.reseau.EtatConnexion
import com.mawena.ccs.reseau.FeuilleDeRoute
import com.mawena.ccs.reseau.InvitationTache
import com.mawena.ccs.reseau.PhaseFeuille
import com.mawena.ccs.reseau.ResultatCase
import com.mawena.ccs.reseau.RpcException
import com.mawena.ccs.reseau.TacheFeuille
import com.mawena.ccs.ui.Chargement
import com.mawena.ccs.ui.EtatErreur
import com.mawena.ccs.ui.EtatVide
import com.mawena.ccs.ui.LocalAvis
import com.mawena.ccs.ui.ModeleAppli
import com.mawena.ccs.ui.texte
import kotlinx.coroutines.launch
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

/**
 * Feuille de route d'un projet (`web/roadmap.js`) : phases avec leur progression (repliables ;
 * celles qui ont encore une case vide ouvertes), cases à cocher (le pont refuse si la ligne a changé
 * entre-temps), « Faire… » sur une tâche : dans ce chat (si on est dans un chat), dans un nouveau
 * chat, ou cette nuit (tâche de fond).
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun PanneauFeuilleDeRoute(
    modele: ModeleAppli,
    cwd: String,
    dansCeChat: ((String) -> Unit)? = null,
    nouveauChat: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    val client = modele.depot.client
    val etat by modele.etat.collectAsStateWithLifecycle()
    val avis = LocalAvis.current
    val portee = rememberCoroutineScope()
    var feuille by remember { mutableStateOf<FeuilleDeRoute?>(null) }
    var erreur by remember { mutableStateOf<String?>(null) }
    var charge by remember { mutableStateOf(false) }
    val ouvertes = remember { mutableStateListOf<Int>() }
    val enCours = remember { mutableStateListOf<Int>() }     // cases en cours d'envoi (par ligne)
    var aFaire by remember { mutableStateOf<Pair<PhaseFeuille, TacheFeuille>?>(null) }
    val liste = rememberLazyListState()

    suspend fun charger() {
        charge = true
        try {
            val f = client.appeler("roadmap.read", FeuilleDeRoute.serializer(), buildJsonObject { put("cwd", cwd) })
            if (feuille == null) { ouvertes.clear(); ouvertes.addAll(FeuilleRoute.ouvertes(f.phases)) }
            feuille = f
            erreur = null
        } catch (e: Exception) {
            erreur = e.texte()
        } finally {
            charge = false
        }
    }
    LaunchedEffect(etat is EtatConnexion.Connecte) { if (etat is EtatConnexion.Connecte) charger() }

    /** Remplace la case dans la feuille gardée (sans tout relire : le défilement reste). */
    fun poser(t: TacheFeuille, fait: Boolean) {
        val f = feuille ?: return
        feuille = f.copy(phases = f.phases.map { p -> p.copy(tasks = p.tasks.map { if (it.line == t.line) it.copy(done = fait) else it }) })
    }

    fun cocher(t: TacheFeuille, fait: Boolean) {
        val chemin = feuille?.path ?: return
        if (t.line in enCours) return
        enCours.add(t.line)
        poser(t, fait)
        portee.launch {
            try {
                val r = client.appeler("roadmap.toggle", ResultatCase.serializer(), buildJsonObject {
                    put("path", chemin); put("line", t.line); put("text", t.text); put("done", fait)
                })
                if (!r.changed) {
                    avis.dire("La feuille de route avait déjà changé : elle est rechargée.")
                    charger()
                }
            } catch (e: Exception) {
                poser(t, !fait)
                avis.dire(e.texte(), action = "Recharger") { portee.launch { charger() } }
            } finally {
                enCours.remove(t.line)
            }
        }
    }

    val f = feuille
    PullToRefreshBox(isRefreshing = charge && f != null, onRefresh = { portee.launch { charger() } }, modifier = modifier.fillMaxSize()) {
        when {
            f == null && erreur != null -> EtatErreur(erreur!!) { portee.launch { charger() } }
            f == null -> Chargement()
            f.path == null -> EtatVide("Pas de ROADMAP.md dans ce projet.")
            else -> LazyColumn(Modifier.fillMaxSize(), state = liste, contentPadding = PaddingValues(bottom = 24.dp)) {
                if (f.title.isNotBlank()) item(key = "titre") {
                    Text(f.title, Modifier.padding(16.dp), style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
                }
                f.phases.forEachIndexed { i, p ->
                    item(key = "p$i") {
                        val prog = FeuilleRoute.progression(p)
                        Column(
                            Modifier.fillMaxWidth().clickable { if (i in ouvertes) ouvertes.remove(i) else ouvertes.add(i) }
                                .padding(horizontal = 16.dp, vertical = 10.dp),
                            verticalArrangement = Arrangement.spacedBy(6.dp),
                        ) {
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                Text(p.title, Modifier.weight(1f), style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold)
                                Text(prog.toString(), style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                                Icon(if (i in ouvertes) Icons.Filled.ExpandLess else Icons.Filled.ExpandMore, null)
                            }
                            LinearProgressIndicator({ prog.fraction }, Modifier.fillMaxWidth())
                        }
                    }
                    if (i in ouvertes) itemsIndexed(p.tasks, key = { _, t -> "t${t.line}" }) { _, t ->
                        LigneTache(t, envoi = t.line in enCours, cocher = { cocher(t, it) }, faire = { aFaire = p to t })
                    }
                    item(key = "s$i") { HorizontalDivider() }
                }
            }
        }
    }
    // la phase en cours à l'écran au premier affichage
    LaunchedEffect(f?.path) {
        val ph = f?.phases ?: return@LaunchedEffect
        val n = FeuilleRoute.enCours(ph) ?: return@LaunchedEffect
        var index = if (f.title.isNotBlank()) 1 else 0
        for (k in 0 until n) index += 2 + (if (k in ouvertes) ph[k].tasks.size else 0)
        if (index > 0) liste.scrollToItem(index)
    }

    aFaire?.let { (p, t) ->
        FeuilleFaire(
            t, dansCeChat != null,
            fermer = { aFaire = null },
            choisir = { ou ->
                aFaire = null
                val chemin = feuille?.path ?: return@FeuilleFaire
                portee.launch {
                    val invitation = try {
                        client.appeler("roadmap.task_prompt", InvitationTache.serializer(), buildJsonObject {
                            put("path", chemin); put("text", t.text); put("phase", p.title)
                        }).prompt
                    } catch (e: Exception) {
                        avis.dire(e.texte()); return@launch
                    }
                    try {
                        when (ou) {
                            Ou.Chat -> dansCeChat?.invoke(invitation)
                            Ou.Nouveau -> nouveauChat(invitation)
                            Ou.Nuit -> {
                                client.appeler("tasks.add", buildJsonObject {
                                    put("message", invitation); put("cwd", cwd); put("when", "nuit")
                                    put("roadmap", buildJsonObject { put("path", chemin); put("text", t.text); put("phase", p.title) })
                                })
                                avis.dire("Tâche ajoutée pour cette nuit.")
                            }
                        }
                    } catch (e: RpcException) {
                        avis.dire(e.texte())
                    }
                }
            },
        )
    }
}

private enum class Ou { Chat, Nouveau, Nuit }

@Composable
private fun LigneTache(t: TacheFeuille, envoi: Boolean, cocher: (Boolean) -> Unit, faire: () -> Unit) {
    Row(
        Modifier.fillMaxWidth().padding(start = (8 + 20 * FeuilleRoute.niveau(t.depth)).dp, end = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Checkbox(t.done, { cocher(it) }, enabled = !envoi)
        Text(
            t.text, Modifier.weight(1f).clickable(enabled = !envoi) { cocher(!t.done) }.padding(vertical = 6.dp),
            style = MaterialTheme.typography.bodyMedium,
            color = if (t.done) MaterialTheme.colorScheme.onSurfaceVariant else MaterialTheme.colorScheme.onSurface,
            textDecoration = if (t.done) TextDecoration.LineThrough else null,
        )
        if (!t.done) TextButton(onClick = faire) { Text("Faire…") }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun FeuilleFaire(t: TacheFeuille, dansUnChat: Boolean, fermer: () -> Unit, choisir: (Ou) -> Unit) {
    ModalBottomSheet(onDismissRequest = fermer) {
        Column(Modifier.fillMaxWidth().padding(horizontal = 20.dp).padding(bottom = 24.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text("Faire cette tâche", style = MaterialTheme.typography.titleMedium)
            Text(t.text, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
            if (dansUnChat) Button(onClick = { choisir(Ou.Chat) }, Modifier.fillMaxWidth()) { Text("Dans ce chat") }
            if (dansUnChat) OutlinedButton(onClick = { choisir(Ou.Nouveau) }, Modifier.fillMaxWidth()) { Text("Nouveau chat") }
            else Button(onClick = { choisir(Ou.Nouveau) }, Modifier.fillMaxWidth()) { Text("Nouveau chat") }
            OutlinedButton(onClick = { choisir(Ou.Nuit) }, Modifier.fillMaxWidth()) { Text("Cette nuit") }
            TextButton(onClick = fermer, Modifier.fillMaxWidth()) { Text("Annuler") }
        }
    }
}
