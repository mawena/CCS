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
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ExpandLess
import androidx.compose.material.icons.filled.ExpandMore
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
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
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.mawena.ccs.logique.ChangementsChat
import com.mawena.ccs.logique.Format
import com.mawena.ccs.reseau.Changements
import com.mawena.ccs.reseau.FichierChange
import com.mawena.ccs.reseau.PlanRetour
import com.mawena.ccs.reseau.PointRetour
import com.mawena.ccs.reseau.ResultatRetour
import com.mawena.ccs.ui.Avertissement
import com.mawena.ccs.ui.Chargement
import com.mawena.ccs.ui.Demandes
import com.mawena.ccs.ui.EtatErreur
import com.mawena.ccs.ui.EtatVide
import com.mawena.ccs.ui.LocalAvis
import com.mawena.ccs.ui.ModeleAppli
import com.mawena.ccs.ui.Reussite
import com.mawena.ccs.ui.TitreSection
import com.mawena.ccs.ui.VueDemandes
import com.mawena.ccs.ui.chat.CorpsDiff
import com.mawena.ccs.ui.texte
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.add
import kotlinx.serialization.json.addJsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import kotlinx.serialization.json.putJsonArray

/**
 * Changements de la session (`web/chat-changes.js`) : fichiers changés par Claude avec leur diff,
 * « Annuler ce fichier », « Revenir ici » (état des fichiers d'avant un message). Toute écriture
 * est confirmée et gardée par les empreintes montrées (le pont refuse si le fichier a bougé).
 */
@Composable
fun PanneauChangements(modele: ModeleAppli, chatId: String?, cwd: String, ouvrirFichier: (String) -> Unit, change: () -> Unit = {}) {
    val client = modele.depot.client
    val avis = LocalAvis.current
    val portee = rememberCoroutineScope()
    val demandes = remember { Demandes() }
    var r by remember { mutableStateOf<Changements?>(null) }
    var erreur by remember { mutableStateOf<String?>(null) }
    var occupe by remember { mutableStateOf(false) }
    val ouverts = remember { mutableStateListOf<String>() }

    suspend fun charger() {
        if (chatId == null) { erreur = "Le chat n'est pas encore ouvert."; return }
        try {
            r = client.appeler("work.changes", Changements.serializer(), buildJsonObject { put("chat_id", chatId) })
            erreur = null
        } catch (e: Exception) {
            erreur = e.texte()
        }
    }
    LaunchedEffect(chatId) { charger() }

    fun annuler(f: FichierChange) = portee.launch {
        if (!demandes.confirmer("Annuler les changements de ${Format.base(f.path)} ?", ChangementsChat.texteAnnulation(f), "Annuler ce fichier", danger = true)) return@launch
        occupe = true
        try {
            client.appeler("work.undo", buildJsonObject {
                put("chat_id", chatId); put("path", f.path)
                put("expected", f.sha256?.let { JsonPrimitive(it) } ?: JsonNull)
            })
            avis.dire("Fichier remis comme avant la session.")
            change()
        } catch (e: Exception) {
            avis.dire(e.texte())
        } finally {
            occupe = false
        }
        charger()
    }

    fun revenir(p: PointRetour) = portee.launch {
        occupe = true
        val plan = try {
            client.appeler("rewind.plan", PlanRetour.serializer(), buildJsonObject { put("chat_id", chatId); put("message_id", p.messageId) })
        } catch (e: Exception) {
            avis.dire(e.texte()); occupe = false; return@launch
        }
        occupe = false
        if (plan.steps.isEmpty()) { avis.dire("Tout est déjà comme avant ce message."); return@launch }
        if (!demandes.confirmer(ChangementsChat.titreRetour(plan), ChangementsChat.texteRetour(plan, cwd), "Revenir en arrière", danger = true)) return@launch
        occupe = true
        try {
            val res = client.appeler("rewind.apply", ResultatRetour.serializer(), buildJsonObject {
                put("chat_id", chatId); put("message_id", p.messageId)
                putJsonArray("expected") {
                    plan.steps.forEach { s -> addJsonObject { put("path", s.path); put("sha256", s.sha256?.let { JsonPrimitive(it) } ?: JsonNull) } }
                }
            })
            avis.dire("${res.count} fichier(s) remis comme avant ce message.")
            change()
        } catch (e: Exception) {
            avis.dire(e.texte())
        } finally {
            occupe = false
        }
        charger()
    }

    val c = r
    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(horizontal = 12.dp, vertical = 8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        item {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("Fichiers changés", Modifier.weight(1f), fontWeight = FontWeight.SemiBold)
                TextButton(onClick = { portee.launch { charger() } }, enabled = !occupe) { Text("Actualiser") }
            }
        }
        when {
            c == null && erreur != null -> item { EtatErreur(erreur!!) { portee.launch { charger() } } }
            c == null -> item { Chargement() }
            c.unknown -> item { EtatVide("Le format de l'historique des fichiers de Claude Code n'est pas reconnu : rien ne peut être annulé d'ici.") }
            else -> {
                if (c.files.isEmpty()) item { EtatVide("Aucun fichier n'a changé depuis le début de la session.") }
                items(c.files, key = { "f" + it.path }) { f ->
                    CarteChangement(
                        f, cwd, ouvert = f.path in ouverts, occupe = occupe,
                        basculer = { if (f.path in ouverts) ouverts.remove(f.path) else ouverts.add(f.path) },
                        ouvrir = { ouvrirFichier(f.path) }, annuler = { annuler(f) },
                    )
                }
                if (c.points.isNotEmpty()) {
                    item {
                        Column {
                            TitreSection("Revenir avant un message")
                            Text("Remet les fichiers dans l'état où ils étaient avant ce message.", style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                    }
                    items(c.points.asReversed(), key = { "p" + it.messageId }) { p ->
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Text(p.text.replace(Regex("\\s+"), " "), Modifier.weight(1f), maxLines = 2, overflow = TextOverflow.Ellipsis,
                                style = MaterialTheme.typography.bodyMedium)
                            TextButton(onClick = { revenir(p) }, enabled = !occupe) { Text("Revenir ici") }
                        }
                    }
                }
            }
        }
    }
    VueDemandes(demandes)
}

@Composable
private fun CarteChangement(
    f: FichierChange, cwd: String, ouvert: Boolean, occupe: Boolean,
    basculer: () -> Unit, ouvrir: () -> Unit, annuler: () -> Unit,
) {
    val lignes = remember(f.diff) { if (f.tropGros || f.binary) emptyList() else ChangementsChat.lignes(f.diff) }
    Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceContainer)) {
        Column(Modifier.fillMaxWidth()) {
            Row(Modifier.fillMaxWidth().clickable(onClick = basculer).padding(12.dp), verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                        Text(Format.base(f.path), fontWeight = FontWeight.SemiBold, maxLines = 1, overflow = TextOverflow.Ellipsis)
                        Text(ChangementsChat.genre(f), style = MaterialTheme.typography.labelSmall,
                            color = when (f.kind) { "created" -> Reussite; "deleted" -> MaterialTheme.colorScheme.error; else -> Avertissement })
                        val plus = lignes.count { it.genre == com.mawena.ccs.logique.Diff.Genre.Ajout }
                        val moins = lignes.count { it.genre == com.mawena.ccs.logique.Diff.Genre.Retrait }
                        if (plus > 0) Text("+$plus", style = MaterialTheme.typography.labelSmall, color = Reussite)
                        if (moins > 0) Text("−$moins", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.error)
                    }
                    Text(ChangementsChat.relatif(f.path, cwd), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
                        maxLines = 2, overflow = TextOverflow.Ellipsis)
                }
                Icon(if (ouvert) Icons.Filled.ExpandLess else Icons.Filled.ExpandMore, null)
            }
            if (ouvert) {
                when {
                    f.tropGros -> Text("Fichier trop gros pour être montré", Modifier.padding(horizontal = 12.dp), style = MaterialTheme.typography.bodySmall)
                    f.binary -> Text("Fichier binaire : pas de diff.", Modifier.padding(horizontal = 12.dp), style = MaterialTheme.typography.bodySmall)
                    else -> CorpsDiff(lignes, Modifier.padding(horizontal = 8.dp))
                }
                Row(Modifier.padding(8.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    if (f.kind != "deleted") OutlinedButton(onClick = ouvrir) { Text("Ouvrir le fichier") }
                    OutlinedButton(onClick = annuler, enabled = !occupe) { Text("Annuler ce fichier", color = MaterialTheme.colorScheme.error) }
                }
            }
        }
    }
}
