package com.mawena.ccs.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.clickable
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.OpenInNew
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.Visibility
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.ListItem
import androidx.compose.material3.ListItemDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextRange
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.TextFieldValue
import androidx.compose.ui.unit.dp
import com.mawena.ccs.logique.Format
import com.mawena.ccs.reseau.Conversation
import com.mawena.ccs.reseau.Corbeille
import com.mawena.ccs.reseau.Messages
import com.mawena.ccs.reseau.MiseCorbeille
import com.mawena.ccs.reseau.Renomme
import kotlinx.coroutines.launch
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

/** Ce qui est ouvert autour d'une conversation : menu, aperçu, renommage, suppression. */
class EtatActions {
    var menu by mutableStateOf<Conversation?>(null)
    var apercu by mutableStateOf<Conversation?>(null)
    var renommer by mutableStateOf<Conversation?>(null)
    var supprimer by mutableStateOf<Conversation?>(null)
}

/**
 * Menu « ⋯ » d'une conversation (`convMenu` de `sessions-conv.js`) et ses suites : Aperçu (12
 * derniers messages sans ouvrir), Renommer, Supprimer (corbeille, avec « Annuler »), Reprendre.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ActionsConversation(
    modele: ModeleAppli,
    etat: EtatActions,
    ouvrir: (Conversation) -> Unit,
    changee: () -> Unit,
    suppression: Boolean = true,
) {
    val client = modele.depot.client
    val avis = LocalAvis.current
    val portee = rememberCoroutineScope()

    etat.menu?.let { c ->
        ModalBottomSheet(onDismissRequest = { etat.menu = null }) {
            Column(Modifier.navigationBarsPadding().padding(bottom = 8.dp)) {
                Text(c.titre, Modifier.padding(horizontal = 24.dp), style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
                Text(Format.base(c.cwd), Modifier.padding(horizontal = 24.dp, vertical = 4.dp), color = MaterialTheme.colorScheme.onSurfaceVariant)
                @Composable
                fun Action(texte: String, icone: androidx.compose.ui.graphics.vector.ImageVector, danger: Boolean = false, actif: Boolean = true, faire: () -> Unit) {
                    val teinte = if (danger) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSurface
                    ListItem(
                        headlineContent = { Text(texte, color = if (actif) teinte else MaterialTheme.colorScheme.onSurfaceVariant) },
                        leadingContent = { Icon(icone, null, tint = if (actif) teinte else MaterialTheme.colorScheme.onSurfaceVariant) },
                        colors = ListItemDefaults.colors(containerColor = Color.Transparent),
                        modifier = if (actif) Modifier.clickable { etat.menu = null; faire() } else Modifier,
                    )
                }
                Action("Reprendre", Icons.AutoMirrored.Filled.OpenInNew, actif = c.dossierExiste) { ouvrir(c) }
                Action("Aperçu", Icons.Filled.Visibility) { etat.apercu = c }
                Action("Renommer", Icons.Filled.Edit) { etat.renommer = c }
                if (suppression) Action("Supprimer", Icons.Filled.Delete, danger = true) { etat.supprimer = c }
            }
        }
    }

    etat.apercu?.let { c -> Apercu(modele, c, fermer = { etat.apercu = null }, reprendre = { etat.apercu = null; ouvrir(c) }) }

    etat.renommer?.let { c ->
        var texte by remember(c) { mutableStateOf(TextFieldValue(c.titre, TextRange(0, c.titre.length))) }
        var message by remember(c) { mutableStateOf<String?>(null) }
        var occupe by remember(c) { mutableStateOf(false) }
        fun valider() {
            portee.launch {
                occupe = true
                message = null
                try {
                    client.appeler(
                        "conversation.rename", Renomme.serializer(),
                        buildJsonObject { put("session_id", c.sessionId); put("title", texte.text); put("path", c.path) },
                    )
                    etat.renommer = null
                    avis.dire("Conversation renommée.")
                    changee()
                } catch (e: Exception) {
                    message = e.texte()
                }
                occupe = false
            }
        }
        AlertDialog(
            onDismissRequest = { etat.renommer = null },
            title = { Text("Renommer la conversation") },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedTextField(
                        texte, { if (it.text.length <= 200) texte = it }, singleLine = true,
                        label = { Text("Nouveau titre") },
                        keyboardOptions = KeyboardOptions(imeAction = ImeAction.Done),
                        keyboardActions = KeyboardActions(onDone = { valider() }),
                        modifier = Modifier.fillMaxWidth(),
                    )
                    message?.let { Text(it, color = MaterialTheme.colorScheme.error) }
                }
            },
            confirmButton = { Button(onClick = { valider() }, enabled = !occupe) { Text("Renommer") } },
            dismissButton = { TextButton(onClick = { etat.renommer = null }) { Text("Annuler") } },
        )
    }

    etat.supprimer?.let { c ->
        Confirmation(
            titre = "Supprimer cette conversation ?",
            texte = "« ${c.titre} » part dans la corbeille de CCS : tu peux la restaurer pendant 30 jours.",
            confirmer = "Supprimer", danger = true,
            surNon = { etat.supprimer = null },
            surOui = {
                etat.supprimer = null
                portee.launch {
                    try {
                        val r = client.appeler(
                            "conversation.trash", MiseCorbeille.serializer(),
                            buildJsonObject {
                                put("path", c.path); put("session_id", c.sessionId); put("cwd", c.cwd); put("title", c.titre)
                            },
                        )
                        changee()
                        avis.dire("Conversation mise à la corbeille.", action = "Annuler") {
                            portee.launch {
                                try {
                                    client.appeler("conversation.restore", buildJsonObject { put("tid", r.tid) })
                                    avis.dire("Conversation restaurée.")
                                    changee()
                                } catch (e: Exception) {
                                    avis.dire(e.texte())
                                }
                            }
                        }
                    } catch (e: Exception) {
                        avis.dire(e.texte())
                    }
                }
            },
        )
    }
}

private const val MESSAGES_APERCU = 12

@Composable
private fun Apercu(modele: ModeleAppli, c: Conversation, fermer: () -> Unit, reprendre: () -> Unit) {
    var messages by remember(c) { mutableStateOf<Messages?>(null) }
    var erreur by remember(c) { mutableStateOf<String?>(null) }
    var essai by remember { mutableIntStateOf(0) }
    LaunchedEffect(c, essai) {
        erreur = null
        try {
            messages = modele.depot.client.appeler(
                "conversation.messages", Messages.serializer(),
                buildJsonObject { put("path", c.path); put("limit", MESSAGES_APERCU * 3) },
            )
        } catch (e: Exception) {
            erreur = e.texte()
        }
    }
    AlertDialog(
        onDismissRequest = fermer,
        title = { Text(c.titre, maxLines = 2) },
        text = {
            when {
                erreur != null -> EtatErreur(erreur!!) { essai++ }
                messages == null -> Chargement()
                else -> {
                    val vus = messages!!.messages.filter { Format.role(it.role) != null && it.text.isNotBlank() }.takeLast(MESSAGES_APERCU)
                    if (vus.isEmpty()) Text("Rien à afficher dans cette conversation.", color = MaterialTheme.colorScheme.onSurfaceVariant)
                    else LazyColumn(Modifier.heightIn(max = 420.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                        items(vus) { m ->
                            Column {
                                Text(Format.role(m.role)!!.libelle, style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.primary)
                                Text(if (m.text.length > 700) m.text.take(700) + "…" else m.text, style = MaterialTheme.typography.bodyMedium)
                            }
                        }
                    }
                }
            }
        },
        confirmButton = { Button(onClick = reprendre, enabled = c.dossierExiste) { Text("Reprendre") } },
        dismissButton = { TextButton(onClick = fermer) { Text("Fermer") } },
    )
}

/** Corbeille (`openTrash` de `sessions-manage.js`) : conversations supprimées, à restaurer. */
@Composable
fun DialogueCorbeille(modele: ModeleAppli, fermer: () -> Unit, changee: () -> Unit) {
    val client = modele.depot.client
    val avis = LocalAvis.current
    val portee = rememberCoroutineScope()
    var corbeille by remember { mutableStateOf<Corbeille?>(null) }
    var erreur by remember { mutableStateOf<String?>(null) }
    var essai by remember { mutableIntStateOf(0) }
    var enCours by remember { mutableStateOf<String?>(null) }
    LaunchedEffect(essai) {
        erreur = null
        try {
            corbeille = client.appeler("conversation.trash_list", Corbeille.serializer())
        } catch (e: Exception) {
            erreur = e.texte()
        }
    }
    AlertDialog(
        onDismissRequest = fermer,
        title = { Text("Corbeille") },
        text = {
            val c = corbeille
            when {
                erreur != null -> EtatErreur(erreur!!) { essai++ }
                c == null -> Chargement()
                else -> Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text(
                        "Les conversations supprimées y restent ${c.days} jours, puis sont effacées.",
                        style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    val elements = c.items.sortedByDescending { it.supprimeLe ?: 0.0 }
                    if (elements.isEmpty()) Text("La corbeille est vide.")
                    else LazyColumn(Modifier.heightIn(max = 400.dp)) {
                        items(elements, key = { it.tid }) { it ->
                            ListItem(
                                headlineContent = { Text(it.title?.ifBlank { null } ?: "(sans titre)", maxLines = 2) },
                                supportingContent = {
                                    Text(listOfNotNull(Format.base(it.cwd).ifEmpty { null }, it.supprimeLe?.let { t -> "supprimée ${Format.ilYA(t)}" }).joinToString(" · "))
                                },
                                trailingContent = {
                                    TextButton(enabled = enCours == null, onClick = {
                                        portee.launch {
                                            enCours = it.tid
                                            try {
                                                client.appeler("conversation.restore", buildJsonObject { put("tid", it.tid) })
                                                avis.dire("Conversation restaurée.")
                                                changee()
                                                essai++
                                            } catch (e: Exception) {
                                                avis.dire(e.texte())
                                            }
                                            enCours = null
                                        }
                                    }) { Text("Restaurer") }
                                },
                                colors = ListItemDefaults.colors(containerColor = Color.Transparent),
                            )
                        }
                    }
                }
            }
        },
        confirmButton = { TextButton(onClick = fermer) { Text("Fermer") } },
    )
}
