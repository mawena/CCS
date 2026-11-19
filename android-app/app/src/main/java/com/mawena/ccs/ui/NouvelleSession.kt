package com.mawena.ccs.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Folder
import androidx.compose.material3.Button
import androidx.compose.material3.Checkbox
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExposedDropdownMenuBox
import androidx.compose.material3.ExposedDropdownMenuDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.MenuAnchorType
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.rememberModalBottomSheetState
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
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.mawena.ccs.logique.ChoixSession
import com.mawena.ccs.logique.Format
import com.mawena.ccs.logique.dossiersProposes
import com.mawena.ccs.reseau.ChatOuvert
import com.mawena.ccs.reseau.CompteProjet
import com.mawena.ccs.reseau.Depots
import com.mawena.ccs.reseau.EtatComptes
import com.mawena.ccs.reseau.ProjetAjoute
import com.mawena.ccs.reseau.ResultatBascule
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

private const val MONTRES = 30

/** Liste déroulante en lecture seule (choix parmi des paires valeur → libellé). */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun Choix(
    libelle: String,
    options: List<Pair<String, String>>,
    valeur: String,
    surChoix: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    var ouvert by remember { mutableStateOf(false) }
    ExposedDropdownMenuBox(expanded = ouvert, onExpandedChange = { ouvert = it }, modifier = modifier) {
        OutlinedTextField(
            value = options.firstOrNull { it.first == valeur }?.second ?: valeur, onValueChange = {}, readOnly = true,
            singleLine = true, label = { Text(libelle) },
            trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(ouvert) },
            modifier = Modifier.menuAnchor(MenuAnchorType.PrimaryNotEditable).fillMaxWidth(),
        )
        ExposedDropdownMenu(expanded = ouvert, onDismissRequest = { ouvert = false }) {
            options.forEach { (v, t) -> DropdownMenuItem(text = { Text(t) }, onClick = { surChoix(v); ouvert = false }) }
        }
    }
}

/**
 * « Nouvelle session » (`sessions-new.js`) : dossier (récents, projets connus, dépôts git du disque,
 * chemin tapé), compte (conseillé pour ce dossier ; une bascule globale si on en choisit un autre),
 * modèle et droits. Ouvre le chat (`chat.open`) et rend sa réponse.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun FeuilleNouvelleSession(
    modele: ModeleAppli,
    connus: List<String>,
    initial: String = "",
    fermer: () -> Unit,
    ouvert: (ChatOuvert, String) -> Unit,
) {
    val client = modele.depot.client
    val portee = rememberCoroutineScope()
    val feuille = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    var dossier by remember { mutableStateOf(initial) }
    var home by remember { mutableStateOf("") }
    var depots by remember { mutableStateOf<List<String>?>(null) }
    var echecDepots by remember { mutableStateOf<String?>(null) }
    var essaiDepots by remember { mutableIntStateOf(0) }
    var compte by remember { mutableStateOf<CompteProjet?>(null) }
    var compteChoisi by remember { mutableStateOf<String?>(null) }
    var compteTouche by remember { mutableStateOf(false) }
    var modeleIa by remember { mutableStateOf("") }
    var droits by remember { mutableStateOf("manual") }
    var message by remember { mutableStateOf<String?>(null) }
    var occupe by remember { mutableStateOf(false) }
    val recents = remember { modele.depot.recents.lire() }

    LaunchedEffect(Unit) {
        runCatching { client.appeler("accounts.state", EtatComptes.serializer()) }.onSuccess { home = it.home }
    }
    LaunchedEffect(essaiDepots) {
        echecDepots = null
        depots = null
        try {
            depots = client.appeler("projects.folders", Depots.serializer()).folders.map { it.path }
        } catch (e: Exception) {
            echecDepots = e.texte()
        }
    }
    // Compte conseillé pour ce dossier, relu quand on arrête de taper.
    LaunchedEffect(dossier) {
        val chemin = dossier.trim()
        if (chemin.isEmpty()) return@LaunchedEffect
        delay(400)
        val r = runCatching {
            client.appeler("projects.account", CompteProjet.serializer(), buildJsonObject { put("cwd", chemin) })
        }.getOrNull() ?: return@LaunchedEffect          // dossier refusé ou inconnu : on le dira à l'ouverture
        compte = r
        if (!compteTouche || r.profiles.none { it.name == compteChoisi }) compteChoisi = r.preferred ?: r.active
    }

    fun ouvrir() {
        val chemin = dossier.trim()
        if (chemin.isEmpty()) { message = "Choisis ou tape un dossier."; return }
        portee.launch {
            message = null
            occupe = true
            try {
                val actif = compte?.active
                val choisi = compteChoisi
                if (choisi != null && actif != null && choisi != actif) {
                    val r = client.appeler("accounts.switch", ResultatBascule.serializer(), buildJsonObject { put("name", choisi) })
                    if (!r.ok) { message = "La bascule de compte a échoué : rien n'est ouvert."; return@launch }
                }
                val r = client.appeler(
                    "chat.open", ChatOuvert.serializer(),
                    buildJsonObject {
                        put("cwd", chemin)
                        put("options", buildJsonObject {
                            if (modeleIa.isNotEmpty()) put("model", modeleIa)
                            put("rights", droits)
                        })
                    },
                )
                modele.depot.recents.retenir(chemin)
                ouvert(r, chemin)
            } catch (e: Exception) {
                message = e.texte()
            } finally {
                occupe = false
            }
        }
    }

    ModalBottomSheet(onDismissRequest = fermer, sheetState = feuille) {
        Column(
            Modifier.fillMaxWidth().imePadding().navigationBarsPadding().verticalScroll(rememberScrollState())
                .padding(horizontal = 20.dp).padding(bottom = 16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Text("Nouvelle session", style = MaterialTheme.typography.titleLarge)
            OutlinedTextField(
                dossier, { dossier = it }, singleLine = true, label = { Text("Dossier") }, placeholder = { Text("~/Repo/projet") },
                leadingIcon = { Icon(Icons.Filled.Folder, null) },
                keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.None, autoCorrectEnabled = false),
                modifier = Modifier.fillMaxWidth(),
            )
            val proposes = dossiersProposes(recents, connus, depots.orEmpty(), dossier, home)
            Surface(color = MaterialTheme.colorScheme.surfaceContainerHigh, shape = RoundedCornerShape(12.dp)) {
                Column(Modifier.fillMaxWidth().heightIn(max = 260.dp).verticalScroll(rememberScrollState()).padding(vertical = 4.dp)) {
                    proposes.take(MONTRES).forEach { p ->
                        Row(
                            Modifier.fillMaxWidth().clip(RoundedCornerShape(8.dp)).clickable { dossier = p.chemin }
                                .padding(horizontal = 12.dp, vertical = 10.dp),
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.spacedBy(8.dp),
                        ) {
                            Text(
                                Format.court(p.chemin, home), Modifier.weight(1f), maxLines = 1, overflow = TextOverflow.Ellipsis,
                                fontWeight = if (p.chemin == dossier.trim()) FontWeight.SemiBold else FontWeight.Normal,
                            )
                            Etiquette(p.etiquette)
                        }
                    }
                    if (proposes.size > MONTRES) {
                        Text("${proposes.size - MONTRES} autres : tape pour filtrer.", Modifier.padding(12.dp),
                            style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                    when {
                        echecDepots != null -> EtatErreur(echecDepots!!) { essaiDepots++ }
                        depots == null -> Chargement("Recherche des dépôts git…")
                        proposes.isEmpty() -> Text(
                            "Aucun dossier connu ne correspond : le chemin tapé sera utilisé.", Modifier.padding(12.dp),
                            style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
            }
            compte?.takeIf { it.profiles.size >= 2 }?.let { cp ->
                Choix(
                    "Compte Claude",
                    cp.profiles.map { it.name to "${it.name} — ${it.email}" + if (it.active) " (actif)" else "" },
                    compteChoisi.orEmpty(),
                    { compteChoisi = it; compteTouche = true },
                    Modifier.fillMaxWidth(),
                )
                if (cp.hint.isNotBlank()) {
                    Text(cp.hint, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                if (compteChoisi != null && compteChoisi != cp.active) {
                    Text("La bascule s'applique à toutes les sessions ouvertes.", color = Avertissement, style = MaterialTheme.typography.bodySmall)
                }
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Choix("Modèle", ChoixSession.MODELES, modeleIa, { modeleIa = it }, Modifier.weight(1f))
                Choix("Droits", ChoixSession.DROITS, droits, { droits = it }, Modifier.weight(1f))
            }
            if (droits == "bypassPermissions") {
                Text(
                    "Claude pourra tout faire sans rien demander : à réserver à un dossier jetable.",
                    color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall,
                )
            }
            message?.let { Text(it, color = MaterialTheme.colorScheme.error) }
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp, Alignment.End)) {
                TextButton(onClick = fermer) { Text("Annuler") }
                Button(onClick = { ouvrir() }, enabled = !occupe) { Text("Ouvrir un chat") }
            }
        }
    }
}

/** « Ajouter un projet » (`addProject` de `sessions-manage.js`) : dossier existant ou nouveau. */
@Composable
fun DialogueAjouterProjet(modele: ModeleAppli, fermer: () -> Unit, ajoute: (String) -> Unit) {
    val portee = rememberCoroutineScope()
    val avis = LocalAvis.current
    var nouveau by remember { mutableStateOf(false) }
    var cwd by remember { mutableStateOf("") }
    var parent by remember { mutableStateOf("~/Work") }
    var nom by remember { mutableStateOf("") }
    var git by remember { mutableStateOf(true) }
    var message by remember { mutableStateOf<String?>(null) }
    var occupe by remember { mutableStateOf(false) }

    fun valider() {
        if (if (nouveau) nom.isBlank() else cwd.isBlank()) {
            message = if (nouveau) "Donne un nom au dossier." else "Choisis ou tape un dossier."
            return
        }
        portee.launch {
            occupe = true
            message = null
            try {
                val r = modele.depot.client.appeler(
                    "projects.add", ProjetAjoute.serializer(),
                    if (nouveau) buildJsonObject { put("parent", parent.trim()); put("name", nom.trim()); put("git", git) }
                    else buildJsonObject { put("cwd", cwd.trim()) },
                )
                avis.dire("Projet ajouté : ${Format.base(r.cwd)}")
                ajoute(r.cwd)
            } catch (e: Exception) {
                message = e.texte()
            }
            occupe = false
        }
    }

    AlertDialog(
        onDismissRequest = fermer,
        title = { Text("Ajouter un projet") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                listOf(false to "Dossier existant", true to "Nouveau dossier").forEach { (v, t) ->
                    Row(
                        Modifier.fillMaxWidth().selectable(selected = nouveau == v, onClick = { nouveau = v }),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        RadioButton(selected = nouveau == v, onClick = null)
                        Text(t, Modifier.padding(start = 8.dp))
                    }
                }
                val clavier = KeyboardOptions(capitalization = KeyboardCapitalization.None, autoCorrectEnabled = false)
                if (nouveau) {
                    OutlinedTextField(parent, { parent = it }, singleLine = true, label = { Text("Dans le dossier") }, keyboardOptions = clavier, modifier = Modifier.fillMaxWidth())
                    OutlinedTextField(nom, { nom = it }, singleLine = true, label = { Text("Nom") }, placeholder = { Text("mon-projet") }, keyboardOptions = clavier, modifier = Modifier.fillMaxWidth())
                    Row(Modifier.clickable { git = !git }, verticalAlignment = Alignment.CenterVertically) {
                        Checkbox(git, { git = it })
                        Text("Initialiser un dépôt git")
                    }
                } else {
                    OutlinedTextField(cwd, { cwd = it }, singleLine = true, label = { Text("Dossier") }, placeholder = { Text("~/Work/mon-projet") }, keyboardOptions = clavier, modifier = Modifier.fillMaxWidth())
                }
                message?.let { Text(it, color = MaterialTheme.colorScheme.error) }
            }
        },
        confirmButton = { Button(onClick = { valider() }, enabled = !occupe) { Text("Ajouter") } },
        dismissButton = { TextButton(onClick = fermer) { Text("Annuler") } },
    )
}
