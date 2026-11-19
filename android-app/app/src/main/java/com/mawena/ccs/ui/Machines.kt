package com.mawena.ccs.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Cloud
import androidx.compose.material.icons.filled.Computer
import androidx.compose.material3.AssistChip
import androidx.compose.material3.AssistChipDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.ListItem
import androidx.compose.material3.ListItemDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.mawena.ccs.reseau.CcsClient

/** Le choix de machine n'a de sens que s'il existe une autre machine (ou qu'on en pilote une). */
@Composable
fun choixMachinePossible(modele: ModeleAppli): Boolean {
    val machine by modele.machine.collectAsStateWithLifecycle()
    val machines by modele.machines.collectAsStateWithLifecycle()
    return machine.isNotEmpty() || machines.isNotEmpty()
}

/** Bandeau d'accent, sur tous les écrans, tant qu'on pilote une autre machine que ce serveur. */
@Composable
fun BandeauMachine(modele: ModeleAppli, changer: () -> Unit) {
    val machine by modele.machine.collectAsStateWithLifecycle()
    if (machine.isEmpty()) return
    Surface(color = MaterialTheme.colorScheme.tertiaryContainer, contentColor = MaterialTheme.colorScheme.onTertiaryContainer, modifier = Modifier.fillMaxWidth()) {
        Row(
            Modifier.padding(start = 16.dp, end = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Icon(Icons.Filled.Computer, null, Modifier.size(18.dp))
            Text(
                "Machine pilotée : ${modele.depot.client.nomMachine}", Modifier.weight(1f),
                style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.SemiBold,
            )
            TextButton(onClick = changer) { Text("Changer") }
        }
    }
}

/** Puce « machine » (écran Sessions) : ouvre la feuille de choix. */
@Composable
fun PuceMachine(modele: ModeleAppli, modifier: Modifier = Modifier, ouvrir: () -> Unit) {
    if (!choixMachinePossible(modele)) return
    val machine by modele.machine.collectAsStateWithLifecycle()
    val autre = machine.isNotEmpty()
    AssistChip(
        onClick = ouvrir,
        label = { Text(modele.depot.client.nomMachine) },
        leadingIcon = { Icon(if (autre) Icons.Filled.Computer else Icons.Filled.Cloud, null, Modifier.size(18.dp)) },
        colors = if (autre) AssistChipDefaults.assistChipColors(
            containerColor = MaterialTheme.colorScheme.tertiaryContainer,
            labelColor = MaterialTheme.colorScheme.onTertiaryContainer,
            leadingIconContentColor = MaterialTheme.colorScheme.onTertiaryContainer,
        ) else AssistChipDefaults.assistChipColors(),
        modifier = modifier,
    )
}

/** Feuille « Machine pilotée » : ce serveur, puis les autres machines (comme `machineSheet` du web). */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun FeuilleMachines(modele: ModeleAppli, fermer: () -> Unit) {
    val machine by modele.machine.collectAsStateWithLifecycle()
    val machines by modele.machines.collectAsStateWithLifecycle()
    var cherche by remember { mutableStateOf(true) }
    var message by remember { mutableStateOf<String?>(null) }
    LaunchedEffect(Unit) {
        message = modele.rafraichirMachines()
        cherche = false
    }
    val choisir = { id: String, nom: String ->
        fermer()
        modele.choisirMachine(id, nom)
    }
    ModalBottomSheet(onDismissRequest = fermer, sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)) {
        Column(Modifier.fillMaxWidth().navigationBarsPadding().verticalScroll(rememberScrollState()).padding(bottom = 16.dp)) {
            Text("Machine pilotée", style = MaterialTheme.typography.titleLarge, modifier = Modifier.padding(horizontal = 20.dp, vertical = 8.dp))
            LigneMachine(CcsClient.CE_SERVEUR, "le VPS, toujours là", machine.isEmpty(), true, Icons.Filled.Cloud) { choisir("", "") }
            machines.forEach { m ->
                LigneMachine(m.nom, m.description, m.id == machine, m.choisissable, Icons.Filled.Computer) { choisir(m.id, m.nom) }
            }
            Text(
                when {
                    cherche && machines.isEmpty() -> "Recherche des machines…"
                    message != null -> message!!
                    machines.isNotEmpty() -> "Le PC doit être allumé, avec CCS installé."
                    else -> "Aucune autre machine sur le relais Ricochet."
                },
                style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(horizontal = 20.dp, vertical = 8.dp),
            )
        }
    }
}

@Composable
private fun LigneMachine(
    nom: String, detail: String, courante: Boolean, active: Boolean,
    icone: androidx.compose.ui.graphics.vector.ImageVector, choisir: () -> Unit,
) {
    ListItem(
        headlineContent = { Text(nom, fontWeight = if (courante) FontWeight.SemiBold else null) },
        supportingContent = { Text(detail) },
        leadingContent = { Icon(icone, null) },
        trailingContent = if (courante) ({ Icon(Icons.Filled.Check, "Machine actuelle", tint = MaterialTheme.colorScheme.primary) }) else null,
        colors = ListItemDefaults.colors(containerColor = Color.Transparent),
        modifier = Modifier
            .alpha(if (active || courante) 1f else 0.5f)
            .clickable(enabled = active && !courante, onClick = choisir),
    )
}
