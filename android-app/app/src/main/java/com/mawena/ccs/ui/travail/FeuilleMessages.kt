package com.mawena.ccs.ui.travail

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
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
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.mawena.ccs.reseau.MessageEnregistre
import com.mawena.ccs.reseau.MessagesEnregistres
import com.mawena.ccs.ui.Chargement
import com.mawena.ccs.ui.Demandes
import com.mawena.ccs.ui.EtatErreur
import com.mawena.ccs.ui.EtatVide
import com.mawena.ccs.ui.LocalAvis
import com.mawena.ccs.ui.ModeleAppli
import com.mawena.ccs.ui.VueDemandes
import com.mawena.ccs.ui.texte
import kotlinx.coroutines.launch
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

private val PORTEES = listOf("global" to "Tous les projets", "projet" to "Ce projet")

/**
 * Messages enregistrés (`web/chat-saved.js`), communs à tous les projets ou propres au projet :
 * toucher l'un l'insère dans la saisie ; enregistrer le texte en cours ; supprimer (confirmé).
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun FeuilleMessages(modele: ModeleAppli, cwd: String, texteEnCours: String, fermer: () -> Unit, inserer: (String) -> Unit) {
    val client = modele.depot.client
    val avis = LocalAvis.current
    val portee = rememberCoroutineScope()
    val demandes = remember { Demandes() }
    var liste by remember { mutableStateOf<List<MessageEnregistre>?>(null) }
    var erreur by remember { mutableStateOf<String?>(null) }
    var nom by remember { mutableStateOf("") }
    var portee2 by remember { mutableStateOf("global") }
    var occupe by remember { mutableStateOf(false) }

    suspend fun charger() {
        try {
            liste = client.appeler("saved.list", MessagesEnregistres.serializer(), buildJsonObject { put("cwd", cwd) }).items
            erreur = null
        } catch (e: Exception) {
            erreur = e.texte()
        }
    }
    LaunchedEffect(cwd) { charger() }

    ModalBottomSheet(onDismissRequest = fermer, sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)) {
        Column(Modifier.fillMaxWidth().verticalScroll(rememberScrollState()).padding(horizontal = 16.dp).padding(bottom = 24.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("Messages enregistrés", style = MaterialTheme.typography.titleMedium)
            val l = liste
            when {
                l == null && erreur != null -> EtatErreur(erreur!!) { portee.launch { charger() } }
                l == null -> Chargement()
                l.isEmpty() -> EtatVide("Aucun message enregistré pour l'instant.")
                else -> Column(Modifier.heightIn(max = 420.dp)) {
                    l.forEach { m ->
                        Row(Modifier.fillMaxWidth().clickable { fermer(); inserer(m.text) }.padding(vertical = 6.dp), verticalAlignment = Alignment.CenterVertically) {
                            Column(Modifier.weight(1f)) {
                                Row {
                                    Text(m.name, fontWeight = FontWeight.SemiBold)
                                    Text(" · " + if (m.scope == "projet") "ce projet" else "tous", color = MaterialTheme.colorScheme.onSurfaceVariant)
                                }
                                Text(m.text.replace(Regex("\\s+"), " ").take(120), maxLines = 2, overflow = TextOverflow.Ellipsis,
                                    style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                            }
                            IconButton(onClick = {
                                portee.launch {
                                    if (!demandes.confirmer("Supprimer « ${m.name} » ?", "Le message enregistré disparaît.", "Supprimer", danger = true)) return@launch
                                    try {
                                        client.appeler("saved.delete", buildJsonObject { put("cwd", cwd); put("scope", m.scope); put("name", m.name) })
                                    } catch (e: Exception) { avis.dire(e.texte()) }
                                    charger()
                                }
                            }) { Icon(Icons.Filled.Delete, "Supprimer ${m.name}") }
                        }
                        HorizontalDivider()
                    }
                }
            }
            if (texteEnCours.isNotBlank()) {
                Text("Enregistrer le texte en cours", Modifier.padding(top = 8.dp), fontWeight = FontWeight.SemiBold)
                OutlinedTextField(nom, { if (it.length <= 80) nom = it }, Modifier.fillMaxWidth(), singleLine = true, label = { Text("Nom du message") })
                Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    PORTEES.forEach { (v, t) -> FilterChip(portee2 == v, { portee2 = v }, { Text(t) }) }
                }
                Button(
                    onClick = {
                        occupe = true
                        portee.launch {
                            try {
                                client.appeler("saved.save", buildJsonObject {
                                    put("cwd", cwd); put("scope", portee2); put("name", nom); put("text", texteEnCours)
                                })
                                nom = ""
                                avis.dire("Message enregistré.")
                                charger()
                            } catch (e: Exception) {
                                avis.dire(e.texte())
                            } finally {
                                occupe = false
                            }
                        }
                    },
                    enabled = nom.isNotBlank() && !occupe,
                    modifier = Modifier.fillMaxWidth(),
                ) { Text("Enregistrer") }
            }
        }
    }
    VueDemandes(demandes)
}
