package com.mawena.ccs.ui

import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Logout
import androidx.compose.material.icons.automirrored.filled.OpenInNew
import androidx.compose.material.icons.filled.BarChart
import androidx.compose.material.icons.filled.Computer
import androidx.compose.material.icons.filled.Dns
import androidx.compose.material.icons.filled.GraphicEq
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.Person
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.Terminal
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Icon
import androidx.compose.material3.ListItem
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.mawena.ccs.BuildConfig

/** Plus : machine pilotée, Jarvis, réglages, terminaux, analyse, serveur, compte, version, version web, déconnexion. */
@Composable
fun EcranPlus(
    modele: ModeleAppli,
    ouvrirAnalyse: () -> Unit,
    ouvrirReglages: () -> Unit = {},
    ouvrirTerminaux: () -> Unit = {},
    ouvrirJarvis: () -> Unit = {},
) {
    val identifiants by modele.identifiants.collectAsStateWithLifecycle()
    val contexte = LocalContext.current
    var confirmer by remember { mutableStateOf(false) }
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState())) {
        ListItem(
            headlineContent = { Text("Serveur") },
            supportingContent = { Text(identifiants?.serveur.orEmpty()) },
            leadingContent = { Icon(Icons.Filled.Dns, null) },
        )
        if (choixMachinePossible(modele)) {
            val machine by modele.machine.collectAsStateWithLifecycle()
            ListItem(
                headlineContent = { Text("Machine pilotée") },
                supportingContent = { Text(modele.depot.client.nomMachine + if (machine.isEmpty()) "" else " · toucher pour changer") },
                leadingContent = { Icon(Icons.Filled.Computer, null) },
                modifier = Modifier.clickable { modele.choixMachine.value = true },
            )
        }
        ListItem(
            headlineContent = { Text("Compte") },
            supportingContent = {
                Text(identifiants?.utilisateur.orEmpty() + when {
                    identifiants?.portier == true -> " · connexion Portier"
                    identifiants?.viaPortier == true -> " · Portier puis jeton d'appareil"
                    else -> " · jeton d'appareil"
                })
            },
            leadingContent = { Icon(Icons.Filled.Person, null) },
        )
        ListItem(
            headlineContent = { Text("Parler à Jarvis") },
            supportingContent = { Text("L'assistant vocal de la maison, par le serveur CCS et le relais Ricochet") },
            leadingContent = { Icon(Icons.Filled.GraphicEq, null) },
            modifier = Modifier.clickable(onClick = ouvrirJarvis),
        )
        ListItem(
            headlineContent = { Text("Réglages") },
            supportingContent = { Text("Thème, serveur, notifications du téléphone, réglages du serveur, appareils") },
            leadingContent = { Icon(Icons.Filled.Settings, null) },
            modifier = Modifier.clickable(onClick = ouvrirReglages),
        )
        ListItem(
            headlineContent = { Text("Terminaux") },
            supportingContent = { Text("Shell sur le serveur, clavier adapté") },
            leadingContent = { Icon(Icons.Filled.Terminal, null) },
            modifier = Modifier.clickable(onClick = ouvrirTerminaux),
        )
        ListItem(
            headlineContent = { Text("Analyse") },
            supportingContent = { Text("Usage par projet, modèle, compte et heure") },
            leadingContent = { Icon(Icons.Filled.BarChart, null) },
            modifier = Modifier.clickable(onClick = ouvrirAnalyse),
        )
        ListItem(
            headlineContent = { Text("Version de l'appli") },
            supportingContent = { Text(BuildConfig.VERSION_NAME) },
            leadingContent = { Icon(Icons.Filled.Info, null) },
        )
        ListItem(
            headlineContent = { Text("Ouvrir la version web") },
            leadingContent = { Icon(Icons.AutoMirrored.Filled.OpenInNew, null) },
            modifier = Modifier.clickable {
                identifiants?.serveur?.let {
                    runCatching { contexte.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse("$it/"))) }
                }
            },
        )
        ListItem(
            headlineContent = { Text("Se déconnecter") },
            supportingContent = { Text("Oublie le jeton sur ce téléphone (il reste révocable depuis la version web).") },
            leadingContent = { Icon(Icons.AutoMirrored.Filled.Logout, null) },
            modifier = Modifier.clickable { confirmer = true },
        )
    }
    if (confirmer) {
        AlertDialog(
            onDismissRequest = { confirmer = false },
            title = { Text("Se déconnecter ?") },
            text = { Text("Il faudra appairer de nouveau ce téléphone.") },
            confirmButton = {
                TextButton(onClick = { confirmer = false; modele.deconnecter() }) { Text("Se déconnecter") }
            },
            dismissButton = { TextButton(onClick = { confirmer = false }) { Text("Annuler") } },
        )
    }
}
