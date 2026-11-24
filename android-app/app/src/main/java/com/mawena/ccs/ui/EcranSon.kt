package com.mawena.ccs.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowForward
import androidx.compose.material.icons.filled.Computer
import androidx.compose.material.icons.filled.Language
import androidx.compose.material.icons.filled.PhoneAndroid
import androidx.compose.material.icons.filled.PhoneIphone
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Speaker
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.ListItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.mawena.ccs.reseau.AppareilAudio
import com.mawena.ccs.reseau.EnvoiAudio
import com.mawena.ccs.reseau.ListeAudio
import com.mawena.ccs.son.SonPartage
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeoutOrNull
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

private fun iconeSysteme(system: String): ImageVector = when (system) {
    "android" -> Icons.Filled.PhoneAndroid
    "ios" -> Icons.Filled.PhoneIphone
    "web" -> Icons.Filled.Language
    "linux" -> Icons.Filled.Computer
    else -> Icons.Filled.Speaker
}

/**
 * Plus → Son partagé (phase 42) : les sorties et sources du réseau maillé (`audio.list`), les flux
 * en cours (Arrêter), l'envoi du son de ce téléphone vers une sortie (accord de capture demandé à
 * chaque départ), et l'envoi de n'importe quelle source vers n'importe quelle sortie (`audio.send`).
 */
@Composable
fun EcranSon(modele: ModeleAppli, retour: () -> Unit) {
    val avis = LocalAvis.current
    val portee = rememberCoroutineScope()
    val client = modele.depot.client
    val son = modele.depot.son
    val identite by son.identite.collectAsStateWithLifecycle()
    val probleme by son.probleme.collectAsStateWithLifecycle()
    val reception by son.reception.collectAsStateWithLifecycle()
    val capture by son.capture.collectAsStateWithLifecycle()
    var liste by remember { mutableStateOf<ListeAudio?>(null) }
    var erreur by remember { mutableStateOf<String?>(null) }
    var choisirCibleMoi by remember { mutableStateOf(false) }
    var source by remember { mutableStateOf<AppareilAudio?>(null) }
    var cible by remember { mutableStateOf<AppareilAudio?>(null) }
    var choix by remember { mutableStateOf<String?>(null) }     // "source" | "cible"

    suspend fun recharger() {
        runCatching { client.appeler("audio.list", ListeAudio.serializer()) }
            .onSuccess { liste = it; erreur = null }
            .onFailure { erreur = it.message ?: "Pont injoignable." }
    }
    LaunchedEffect(Unit) {
        if (identite == null) son.annoncer()
        while (true) {
            recharger()
            // relu toutes les 5 s, ou tout de suite quand un flux commence ou finit
            withTimeoutOrNull(5_000) { son.changements.first() }
        }
    }
    LaunchedEffect(Unit) { son.erreurs.collect { avis.dire(it, long = true) } }

    val moi = identite?.device
    val appareils = liste?.devices.orEmpty()
    val sorties = appareils.filter { it.play }
    val sources = appareils.filter { it.capture }
    fun nom(device: String) = appareils.firstOrNull { it.device == device }?.nom ?: device

    fun envoyer(s: AppareilAudio, c: AppareilAudio) {
        if (s.device == moi) {
            son.envoyerVers(c.device, c.nom)
            return
        }
        portee.launch {
            try {
                client.appeler("audio.send", EnvoiAudio.serializer(), buildJsonObject { put("source", s.device); put("target", c.device) })
                avis.dire("Son de ${s.nom} envoyé vers ${c.nom}.")
            } catch (e: Exception) {
                avis.dire("Envoi impossible : ${e.texte()}")
            }
            recharger()
        }
    }

    Column(Modifier.fillMaxSize()) {
        BarreHaut(
            "Son partagé",
            sousTitre = identite?.let { "${it.device} · ${it.ip}" } ?: "Ce téléphone n'est pas annoncé",
            retour = retour,
            actions = {
                IconButton(onClick = { portee.launch { son.annoncer(); recharger() } }) { Icon(Icons.Filled.Refresh, "Actualiser") }
            },
        )
        Column(
            Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 16.dp, vertical = 8.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            probleme?.let { EtatErreur(it) }

            // ---- ce téléphone ----
            TitreSection("Ce téléphone")
            Card(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    val r = reception
                    if (r != null) {
                        LigneFlux("Joue le son de ${r.nomSource}") { son.arreterReception() }
                    }
                    when (val c = capture) {
                        is SonPartage.Capture.Envoi -> LigneFlux("Envoie son son vers ${c.destination.nomCible}") { son.arreterEmission() }
                        is SonPartage.Capture.Preparation -> Chargement("Envoi vers ${c.nomCible}…")
                        SonPartage.Capture.Arretee -> Unit
                    }
                    if (r == null && capture == SonPartage.Capture.Arretee) {
                        Text("Ni lecture ni envoi en cours.", color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                    if (son.saitCapter) {
                        Button(
                            onClick = { choisirCibleMoi = true },
                            enabled = identite != null,
                            modifier = Modifier.fillMaxWidth(),
                        ) { Text("Envoyer le son de ce téléphone vers…") }
                    } else {
                        Text(
                            "Envoyer le son de ce téléphone demande Android 10 ou plus ; il peut toujours jouer le son des autres.",
                            style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
            }

            // ---- flux en cours ----
            TitreSection("Flux en cours")
            val flux = liste?.streams.orEmpty()
            when {
                liste == null && erreur == null -> Chargement()
                erreur != null && liste == null -> EtatErreur(erreur!!) { portee.launch { recharger() } }
                flux.isEmpty() -> Text("Aucun flux.", color = MaterialTheme.colorScheme.onSurfaceVariant)
                else -> flux.forEach { f ->
                    LigneFlux("${nom(f.source)} → ${nom(f.target)}") {
                        portee.launch { son.arreterFlux(f.stream); recharger() }
                    }
                }
            }

            // ---- envoi de n'importe où vers n'importe où ----
            TitreSection("Envoyer le son")
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton(onClick = { choix = "source" }, modifier = Modifier.weight(1f)) {
                    Text(source?.nom ?: "Source", maxLines = 1)
                }
                Icon(Icons.AutoMirrored.Filled.ArrowForward, null)
                OutlinedButton(onClick = { choix = "cible" }, modifier = Modifier.weight(1f)) {
                    Text(cible?.nom ?: "Sortie", maxLines = 1)
                }
            }
            val s = source
            val c = cible
            Button(
                onClick = { if (s != null && c != null) envoyer(s, c) },
                enabled = s != null && c != null && s.device != c.device,
                modifier = Modifier.fillMaxWidth(),
            ) { Text("Envoyer") }

            // ---- appareils ----
            TitreSection("Sorties (${sorties.size})")
            if (sorties.isEmpty() && liste != null) Text("Aucune sortie annoncée.", color = MaterialTheme.colorScheme.onSurfaceVariant)
            sorties.forEach { LigneAppareil(it, it.device == moi) }
            TitreSection("Sources (${sources.size})")
            if (sources.isEmpty() && liste != null) Text("Aucune source annoncée.", color = MaterialTheme.colorScheme.onSurfaceVariant)
            sources.forEach { LigneAppareil(it, it.device == moi) }
            Text(
                "Chaque appareil où CCS est ouvert s'annonce toutes les 30 s. Le son passe en direct par le réseau maillé (RTP/Opus, port UDP 4010).",
                style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(vertical = 8.dp),
            )
        }
    }

    if (choisirCibleMoi) {
        ChoixAppareil(
            "Envoyer le son de ce téléphone vers…", sorties.filter { it.device != moi },
            fermer = { choisirCibleMoi = false },
        ) { a ->
            choisirCibleMoi = false
            son.envoyerVers(a.device, a.nom)
        }
    }
    choix?.let { quoi ->
        ChoixAppareil(
            if (quoi == "source") "Source" else "Sortie",
            if (quoi == "source") sources else sorties,
            fermer = { choix = null },
        ) { a ->
            if (quoi == "source") source = a else cible = a
            choix = null
        }
    }
}

@Composable
private fun LigneFlux(texte: String, arreter: () -> Unit) {
    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        Text(texte, Modifier.weight(1f))
        TextButton(onClick = arreter) { Text("Arrêter") }
    }
}

@Composable
private fun LigneAppareil(a: AppareilAudio, moi: Boolean) {
    ListItem(
        headlineContent = { Text(a.nom + if (moi) " (ce téléphone)" else "") },
        supportingContent = { Text("${a.device} · ${a.ip} · ${a.system}") },
        leadingContent = { Icon(iconeSysteme(a.system), null) },
    )
}

@Composable
private fun ChoixAppareil(titre: String, appareils: List<AppareilAudio>, fermer: () -> Unit, choisir: (AppareilAudio) -> Unit) {
    AlertDialog(
        onDismissRequest = fermer,
        title = { Text(titre) },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState())) {
                if (appareils.isEmpty()) Text("Aucun appareil annoncé.", color = MaterialTheme.colorScheme.onSurfaceVariant)
                appareils.forEach { a ->
                    ListItem(
                        headlineContent = { Text(a.nom) },
                        supportingContent = { Text(a.device) },
                        leadingContent = { Icon(iconeSysteme(a.system), null) },
                        modifier = Modifier.clickable { choisir(a) },
                    )
                }
            }
        },
        confirmButton = {},
        dismissButton = { TextButton(onClick = fermer) { Text("Annuler") } },
    )
}
