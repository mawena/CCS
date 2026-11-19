package com.mawena.ccs.ui.chat

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Label
import androidx.compose.material.icons.automirrored.filled.Reply
import androidx.compose.material.icons.filled.ContentCopy
import androidx.compose.material.icons.filled.FormatQuote
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.SuggestionChip
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.TextRange
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.TextFieldValue
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.mawena.ccs.logique.Citation
import com.mawena.ccs.logique.ElementFil
import com.mawena.ccs.logique.EntreeEtiquettes
import com.mawena.ccs.logique.Etiquettes

/** Auteur, texte d'origine et identifiant d'un message du fil (actions « Répondre », « Étiqueter »). */
data class MessageChoisi(val auteur: Citation.Auteur, val brut: String, val msgId: String) {
    /** Texte cité ou étiqueté : pour un message qui citait, sa réponse. */
    val texte: String get() = if (auteur == Citation.Auteur.Moi) Citation.texteSource(brut) else brut

    companion object {
        fun de(e: ElementFil): MessageChoisi? = when (e) {
            is ElementFil.MsgToi -> MessageChoisi(Citation.Auteur.Moi, e.texte, e.msgId)
            is ElementFil.MsgClaude -> MessageChoisi(Citation.Auteur.Claude, e.texte, e.msgId)
            else -> null
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun MenuMessage(
    m: MessageChoisi,
    fermer: () -> Unit,
    repondre: () -> Unit,
    passage: () -> Unit,
    etiqueter: () -> Unit,
) {
    val presse = LocalClipboardManager.current
    ModalBottomSheet(onDismissRequest = fermer) {
        Column(Modifier.fillMaxWidth().padding(bottom = 24.dp)) {
            Text(
                Citation.uneLigne(m.texte, 160), Modifier.padding(horizontal = 20.dp, vertical = 8.dp),
                style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 3,
                overflow = TextOverflow.Ellipsis,
            )
            @Composable
            fun Ligne(t: String, i: ImageVector, f: () -> Unit) {
                Row(Modifier.fillMaxWidth().clickable { f() }.padding(horizontal = 20.dp, vertical = 14.dp), verticalAlignment = Alignment.CenterVertically) {
                    Icon(i, null)
                    Text(t, Modifier.padding(start = 16.dp), style = MaterialTheme.typography.bodyLarge)
                }
            }
            Ligne("Répondre", Icons.AutoMirrored.Filled.Reply) { repondre() }
            Ligne("Citer un passage…", Icons.Filled.FormatQuote) { passage() }
            Ligne("Copier", Icons.Filled.ContentCopy) { presse.setText(AnnotatedString(m.texte)); fermer() }
            Ligne("Étiqueter", Icons.AutoMirrored.Filled.Label) { etiqueter() }
        }
    }
}

/** Choisir le passage à citer : le texte du message, sélectionnable ; « Citer » prend la sélection. */
@Composable
fun DialoguePassage(m: MessageChoisi, fermer: () -> Unit, citer: (Citation.Cite) -> Unit) {
    var champ by remember { mutableStateOf(TextFieldValue(m.texte, TextRange(0, 0))) }
    AlertDialog(
        onDismissRequest = fermer,
        title = { Text("Citer un passage") },
        text = {
            Column {
                Text("Sélectionne le passage, puis « Citer ».", style = MaterialTheme.typography.bodySmall)
                OutlinedTextField(champ, { champ = it.copy(text = m.texte) }, Modifier.fillMaxWidth().heightIn(max = 360.dp).padding(top = 8.dp), readOnly = true)
            }
        },
        confirmButton = {
            TextButton(onClick = {
                val s = champ.selection
                val t = if (s.collapsed) m.texte else m.texte.substring(s.min, s.max)
                val ex = Citation.extrait(t, if (s.collapsed) Citation.MAX else Citation.MAX_SELECTION)
                if (ex.isNotEmpty()) citer(Citation.Cite(m.auteur, ex))
                fermer()
            }) { Text(if (champ.selection.collapsed) "Citer tout" else "Citer") }
        },
        dismissButton = { TextButton(onClick = fermer) { Text("Annuler") } },
    )
}

/** Étiqueter un message : saisie séparée par des virgules, suggestions des étiquettes déjà utilisées. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun DialogueEtiquettes(actuelles: List<String>, connues: List<String>, extrait: String, fermer: () -> Unit, valider: (List<String>) -> Unit) {
    var texte by remember { mutableStateOf(actuelles.joinToString(", ")) }
    val prises = Etiquettes.lire(texte).map { it.lowercase() }.toSet()
    AlertDialog(
        onDismissRequest = fermer,
        title = { Text("Étiqueter") },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState())) {
                Text(extrait, maxLines = 3, overflow = TextOverflow.Ellipsis, style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant)
                OutlinedTextField(texte, { texte = it }, Modifier.fillMaxWidth().padding(top = 8.dp),
                    label = { Text("Étiquettes (séparées par des virgules)") })
                val proposees = connues.filter { it.lowercase() !in prises }.take(20)
                if (proposees.isNotEmpty()) FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    proposees.forEach { t ->
                        SuggestionChip(onClick = {
                            texte = (Etiquettes.lire(texte) + t).joinToString(", ")
                        }, label = { Text(t) })
                    }
                }
            }
        },
        confirmButton = { TextButton(onClick = { valider(Etiquettes.lire(texte)) }) { Text("Enregistrer") } },
        dismissButton = { TextButton(onClick = fermer) { Text("Annuler") } },
    )
}

/** Volet « Étiquettes » : messages groupés par étiquette ; toucher ramène au message. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun FeuilleEtiquettes(messages: Map<String, EntreeEtiquettes>, filtre: String?, fermer: () -> Unit, aller: (String) -> Unit) {
    val groupes = remember(messages, filtre) {
        Etiquettes.parEtiquette(messages).filter { filtre == null || it.first.equals(filtre, ignoreCase = true) }
    }
    ModalBottomSheet(onDismissRequest = fermer) {
        Text(if (filtre != null) "Étiquette « $filtre »" else "Étiquettes", Modifier.padding(horizontal = 20.dp),
            style = MaterialTheme.typography.titleMedium)
        if (groupes.isEmpty()) {
            Text("Aucun message étiqueté dans cette conversation. Appuie longuement sur un message puis « Étiqueter ».",
                Modifier.padding(20.dp), style = MaterialTheme.typography.bodyMedium)
            return@ModalBottomSheet
        }
        LazyColumn(Modifier.fillMaxWidth().padding(bottom = 24.dp)) {
            groupes.forEach { (tag, liste) ->
                item(key = "t:$tag") {
                    Text(tag, Modifier.padding(start = 20.dp, top = 12.dp, bottom = 4.dp), style = MaterialTheme.typography.titleSmall,
                        color = MaterialTheme.colorScheme.primary, fontWeight = FontWeight.SemiBold)
                }
                items(liste, key = { "t:$tag:${it.first}" }) { (id, e) ->
                    Row(Modifier.fillMaxWidth().clickable { aller(id) }.padding(horizontal = 20.dp, vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                        Text(if (e.role == "utilisateur") "Toi" else "Claude", Modifier.padding(end = 8.dp),
                            style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        Text(e.extrait.ifEmpty { "(message)" }, maxLines = 2, overflow = TextOverflow.Ellipsis, style = MaterialTheme.typography.bodyMedium)
                    }
                }
            }
        }
    }
}
