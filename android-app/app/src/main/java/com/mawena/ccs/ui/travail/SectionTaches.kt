package com.mawena.ccs.ui.travail

import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Surface
import androidx.compose.material3.SuggestionChip
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.repeatOnLifecycle
import com.mawena.ccs.logique.Format
import com.mawena.ccs.logique.TachesFond
import com.mawena.ccs.reseau.ChatOuvert
import com.mawena.ccs.reseau.EtatConnexion
import com.mawena.ccs.reseau.JournalTache
import com.mawena.ccs.reseau.ListeProjets
import com.mawena.ccs.reseau.ListeTaches
import com.mawena.ccs.reseau.RpcException
import com.mawena.ccs.reseau.TacheFond
import com.mawena.ccs.ui.Avertissement
import com.mawena.ccs.ui.Chargement
import com.mawena.ccs.ui.Demandes
import com.mawena.ccs.ui.DestChat
import com.mawena.ccs.ui.EtatErreur
import com.mawena.ccs.ui.LocalAvis
import com.mawena.ccs.ui.ModeleAppli
import com.mawena.ccs.ui.Reussite
import com.mawena.ccs.ui.VueDemandes
import com.mawena.ccs.ui.texte
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

/**
 * Tâches de nuit sur l'Accueil (`web/pages-tasks.js`) : liste par état, journal d'une tâche (relu
 * toutes les 3 s tant qu'elle tourne), nouvelle tâche, reprise dans un chat, annulation et
 * suppression confirmées. Relu toutes les 15 s tant qu'une tâche est active.
 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun SectionTaches(modele: ModeleAppli, home: String, ouvrirChat: (DestChat) -> Unit) {
    val client = modele.depot.client
    val etat by modele.etat.collectAsStateWithLifecycle()
    val cycle = LocalLifecycleOwner.current.lifecycle
    val portee = rememberCoroutineScope()
    var toutes by remember { mutableStateOf<List<TacheFond>?>(null) }
    var erreur by remember { mutableStateOf<String?>(null) }
    var filtre by remember { mutableStateOf<String?>(null) }
    var detail by remember { mutableStateOf<String?>(null) }
    var nouvelle by remember { mutableStateOf(false) }

    suspend fun charger() {
        try {
            val l = client.appeler("tasks.list", ListeTaches.serializer()).tasks
            toutes = l
            if (filtre == null) filtre = TachesFond.filtreInitial(l)
            erreur = null
        } catch (e: Exception) {
            erreur = e.texte()
        }
    }
    LaunchedEffect(etat is EtatConnexion.Connecte) {
        if (etat !is EtatConnexion.Connecte) return@LaunchedEffect
        cycle.repeatOnLifecycle(Lifecycle.State.STARTED) {
            charger()
            while (true) {
                delay(15_000)
                if (toutes.orEmpty().any(TachesFond::active)) charger()
            }
        }
    }

    Card(Modifier.fillMaxWidth(), colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceContainer)) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("Tâches de nuit", Modifier.weight(1f), style = MaterialTheme.typography.titleMedium)
                Button(onClick = { nouvelle = true }) { Text("Nouvelle tâche") }
            }
            val l = toutes
            when {
                l == null && erreur != null -> EtatErreur(erreur!!) { portee.launch { charger() } }
                l == null -> Chargement()
                else -> {
                    Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        TachesFond.FILTRES.forEach { f ->
                            FilterChip(filtre == f.cle, { filtre = f.cle }, { Text("${f.libelle} (${TachesFond.nombre(l, f)})") })
                        }
                    }
                    val montrees = TachesFond.filtrer(l, filtre ?: "actives")
                    if (montrees.isEmpty()) {
                        Text(if (l.isEmpty()) "Aucune tâche pour l'instant." else "Rien dans cette catégorie.",
                            color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                    montrees.forEach { t ->
                        Row(Modifier.fillMaxWidth().clickable { detail = t.id }.padding(vertical = 6.dp), verticalAlignment = Alignment.CenterVertically) {
                            Column(Modifier.weight(1f)) {
                                Text(TachesFond.titre(t), fontWeight = FontWeight.SemiBold, maxLines = 2, overflow = TextOverflow.Ellipsis)
                                Text(TachesFond.sousTitre(t), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
                                    maxLines = 2, overflow = TextOverflow.Ellipsis)
                            }
                            PastilleEtat(t)
                        }
                        HorizontalDivider()
                    }
                }
            }
        }
    }

    detail?.let { id ->
        FeuilleTache(modele, id, fermer = { detail = null }, change = { portee.launch { charger() } }, reprendre = { d -> detail = null; ouvrirChat(d) })
    }
    if (nouvelle) FeuilleNouvelleTache(modele, home, fermer = { nouvelle = false }) {
        nouvelle = false
        filtre = "actives"
        portee.launch { charger() }
    }
}

@Composable
private fun PastilleEtat(t: TacheFond) {
    val couleur = when (t.state) {
        "running" -> MaterialTheme.colorScheme.primary
        "done" -> Reussite
        "failed" -> MaterialTheme.colorScheme.error
        "waiting" -> Avertissement
        else -> MaterialTheme.colorScheme.onSurfaceVariant
    }
    Surface(shape = MaterialTheme.shapes.small, color = couleur.copy(alpha = 0.15f)) {
        Text(TachesFond.etat(t), Modifier.padding(horizontal = 8.dp, vertical = 2.dp), color = couleur, style = MaterialTheme.typography.labelSmall)
    }
}

/** Détail et journal d'une tâche. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun FeuilleTache(modele: ModeleAppli, id: String, fermer: () -> Unit, change: () -> Unit, reprendre: (DestChat) -> Unit) {
    val client = modele.depot.client
    val avis = LocalAvis.current
    val portee = rememberCoroutineScope()
    val demandes = remember { Demandes() }
    var j by remember { mutableStateOf<JournalTache?>(null) }
    var erreur by remember { mutableStateOf<String?>(null) }
    var occupe by remember { mutableStateOf(false) }
    val defile = rememberScrollState()

    suspend fun relire(): Boolean {
        try {
            j = client.appeler("tasks.log", JournalTache.serializer(), buildJsonObject { put("id", id) })
            erreur = null
        } catch (e: RpcException) {
            erreur = e.texte()
            if (e.code == "introuvable") change()
            return false
        } catch (e: Exception) {
            erreur = e.texte()
        }
        return j?.task?.let(TachesFond::active) == true
    }
    LaunchedEffect(id) {
        while (relire()) {
            defile.scrollTo(defile.maxValue)
            delay(3000)
        }
        defile.scrollTo(defile.maxValue)
    }

    ModalBottomSheet(onDismissRequest = fermer, sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)) {
        Column(Modifier.fillMaxWidth().fillMaxHeight(0.9f).padding(horizontal = 16.dp).padding(bottom = 16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            val r = j
            val t = r?.task
            Text(t?.let(TachesFond::titre) ?: "Tâche", style = MaterialTheme.typography.titleMedium)
            if (t != null) {
                Text(
                    TachesFond.sousTitre(t) + (if (r.summary.isNotEmpty()) " · ${r.summary}" else "") + "\n" +
                        TachesFond.droits(t.rights) + (t.model?.let { " · $it" } ?: ""),
                    style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            erreur?.let { Text(it, color = MaterialTheme.colorScheme.error) }
            Surface(Modifier.weight(1f).fillMaxWidth(), color = MaterialTheme.colorScheme.surfaceContainerHighest, shape = MaterialTheme.shapes.small) {
                Text(
                    when {
                        r == null -> "Chargement…"
                        r.lines.isEmpty() -> "Pas encore de journal."
                        else -> (if (r.truncated) "… (début du journal omis)\n" else "") + r.lines.joinToString("\n")
                    },
                    Modifier.verticalScroll(defile).horizontalScroll(rememberScrollState()).padding(8.dp),
                    fontFamily = FontFamily.Monospace, fontSize = 11.sp, lineHeight = 14.sp,
                )
            }
            if (t != null) FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                if (t.sessionId != null) Button(onClick = {
                    occupe = true
                    portee.launch {
                        try {
                            val o = client.appeler("chat.open", ChatOuvert.serializer(), buildJsonObject { put("cwd", t.cwd); put("session_id", t.sessionId) })
                            reprendre(DestChat(o.cwd.ifEmpty { t.cwd }, o.sessionId ?: t.sessionId, o.path, Format.base(t.cwd), o.chatId))
                        } catch (e: Exception) {
                            avis.dire(e.texte())
                        } finally { occupe = false }
                    }
                }, enabled = !occupe) { Text("Reprendre") }
                val active = TachesFond.active(t)
                OutlinedButton(
                    onClick = {
                        portee.launch {
                            val ok = if (active) demandes.confirmer("Annuler cette tâche ?",
                                if (t.state == "running") "Claude est en train de la faire : il sera arrêté." else "Elle ne sera pas lancée.",
                                "Annuler la tâche", danger = true)
                            else demandes.confirmer("Supprimer cette tâche ?", "Son journal sera supprimé aussi.", "Supprimer", danger = true)
                            if (!ok) return@launch
                            occupe = true
                            try {
                                client.appeler(if (active) "tasks.cancel" else "tasks.remove", buildJsonObject { put("id", t.id) })
                                avis.dire(if (active) "Tâche annulée." else "Tâche supprimée.")
                                change()
                                fermer()
                            } catch (e: Exception) {
                                avis.dire(e.texte())
                            } finally { occupe = false }
                        }
                    },
                    enabled = !occupe,
                    colors = ButtonDefaults.outlinedButtonColors(contentColor = MaterialTheme.colorScheme.error),
                ) { Text(if (active) "Annuler la tâche" else "Supprimer") }
                TextButton(onClick = fermer) { Text("Fermer") }
            }
        }
    }
    VueDemandes(demandes)
}

/** Nouvelle tâche : dossier, message, quand, droits, modèle. */
@OptIn(ExperimentalMaterial3Api::class, ExperimentalLayoutApi::class)
@Composable
private fun FeuilleNouvelleTache(modele: ModeleAppli, home: String, fermer: () -> Unit, ajoutee: () -> Unit) {
    val client = modele.depot.client
    val avis = LocalAvis.current
    val portee = rememberCoroutineScope()
    val demandes = remember { Demandes() }
    var dossier by remember { mutableStateOf(if (home.isNotEmpty()) home else "") }
    var message by remember { mutableStateOf("") }
    var quand by remember { mutableStateOf("quota") }
    var heure by remember { mutableStateOf("") }
    var droits by remember { mutableStateOf("modifications") }
    var modeleIa by remember { mutableStateOf("") }
    var erreur by remember { mutableStateOf<String?>(null) }
    var occupe by remember { mutableStateOf(false) }
    var projets by remember { mutableStateOf<List<String>>(emptyList()) }
    LaunchedEffect(Unit) {
        runCatching { client.appeler("projects.list", ListeProjets.serializer()) }.onSuccess { r ->
            projets = r.projets.filter { it.exists }.mapNotNull { it.cwd }.take(10)
        }
    }

    fun tenterFermer() {
        if (message.isBlank()) { fermer(); return }
        portee.launch {
            if (demandes.confirmer("Abandonner cette tâche ?", "Le message tapé sera perdu.", "Abandonner", danger = true)) fermer()
        }
    }

    ModalBottomSheet(onDismissRequest = { tenterFermer() }, sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true, confirmValueChange = { true })) {
        Column(Modifier.fillMaxWidth().verticalScroll(rememberScrollState()).padding(horizontal = 16.dp).padding(bottom = 24.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("Nouvelle tâche", style = MaterialTheme.typography.titleMedium)
            OutlinedTextField(dossier, { dossier = it }, Modifier.fillMaxWidth(), singleLine = true, label = { Text("Dossier du projet") },
                placeholder = { Text("~/Work/mon-projet") },
                keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.None, autoCorrectEnabled = false))
            if (projets.isNotEmpty()) FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                projets.forEach { p -> SuggestionChip({ dossier = p }, { Text(Format.base(p)) }) }
            }
            OutlinedTextField(message, { message = it }, Modifier.fillMaxWidth().heightIn(min = 120.dp), label = { Text("Message") },
                placeholder = { Text("Ce que Claude doit faire…") },
                keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.Sentences))
            Text("Quand", style = MaterialTheme.typography.titleSmall, color = MaterialTheme.colorScheme.primary)
            TachesFond.QUAND.forEach { (v, t) ->
                Row(Modifier.fillMaxWidth().clickable { quand = v }, verticalAlignment = Alignment.CenterVertically) {
                    RadioButton(quand == v, { quand = v }); Text(t)
                }
            }
            if (quand == "heure") OutlinedTextField(heure, { heure = it }, singleLine = true, label = { Text("Heure (HH:MM)") },
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number))
            Text("Droits", style = MaterialTheme.typography.titleSmall, color = MaterialTheme.colorScheme.primary)
            TachesFond.DROITS.forEach { (v, t, _) ->
                Row(Modifier.fillMaxWidth().clickable { droits = v }, verticalAlignment = Alignment.CenterVertically) {
                    RadioButton(droits == v, { droits = v }); Text(t)
                }
            }
            Text(TachesFond.DROITS.first { it.first == droits }.third, style = MaterialTheme.typography.bodySmall,
                color = if (droits == "tout") MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSurfaceVariant)
            Text("Modèle", style = MaterialTheme.typography.titleSmall, color = MaterialTheme.colorScheme.primary)
            FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                TachesFond.MODELES.forEach { (v, t) -> FilterChip(modeleIa == v, { modeleIa = v }, { Text(t) }) }
            }
            erreur?.let { Text(it, color = MaterialTheme.colorScheme.error) }
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp, Alignment.End)) {
                TextButton(onClick = { tenterFermer() }) { Text("Annuler") }
                Button(onClick = {
                    val cwd = TachesFond.dossier(dossier, home)
                    erreur = TachesFond.verifier(cwd, message, quand, heure)
                    if (erreur != null) return@Button
                    occupe = true
                    portee.launch {
                        try {
                            client.appeler("tasks.add", buildJsonObject {
                                put("cwd", cwd); put("message", message); put("rights", droits)
                                if (modeleIa.isEmpty()) put("model", JsonNull) else put("model", modeleIa)
                                put("when", TachesFond.quandEnvoye(quand, heure))
                            })
                            avis.dire("Tâche ajoutée.")
                            ajoutee()
                        } catch (e: Exception) {
                            erreur = e.texte()
                        } finally { occupe = false }
                    }
                }, enabled = !occupe) { Text("Ajouter") }
            }
        }
    }
    VueDemandes(demandes)
}
