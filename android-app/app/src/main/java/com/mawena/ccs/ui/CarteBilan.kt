package com.mawena.ccs.ui

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.ContentCopy
import androidx.compose.material.icons.filled.Error
import androidx.compose.material.icons.filled.ExpandLess
import androidx.compose.material.icons.filled.ExpandMore
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.mawena.ccs.reseau.Bilan
import com.mawena.ccs.reseau.Verification
import kotlinx.coroutines.launch

/** « Bilan de santé » (`pages-health.js`) : erreurs et avertissements d'abord, commande à copier. */
@Composable
fun CarteBilan(modele: ModeleAppli) {
    val avis = LocalAvis.current
    val portee = rememberCoroutineScope()
    var bilan by remember { mutableStateOf<Bilan?>(null) }
    var erreur by remember { mutableStateOf<String?>(null) }
    var enCours by remember { mutableStateOf(false) }
    var reussiesOuvertes by remember { mutableStateOf(false) }

    fun lancer() {
        portee.launch {
            enCours = true
            erreur = null
            try {
                val r = modele.depot.client.appeler("doctor.run", Bilan.serializer())
                bilan = r
                if (r.errors == 0 && r.warnings == 0) avis.dire("Tout va bien.")
            } catch (e: Exception) {
                erreur = e.texte()
            }
            enCours = false
        }
    }

    Card(Modifier.fillMaxWidth(), colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceContainer)) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("Bilan de santé", Modifier.weight(1f), style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
                FilledTonalButton(onClick = { lancer() }, enabled = !enCours) { Text("Lancer le bilan") }
            }
            Text(
                "Vérifie le service, les comptes, Claude Code, le téléphone et le serveur.",
                style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            when {
                enCours -> Chargement("Vérification en cours…")
                erreur != null -> EtatErreur(erreur!!) { lancer() }
                else -> bilan?.let { b ->
                    Text(
                        b.summary, fontWeight = FontWeight.SemiBold,
                        color = when {
                            b.errors > 0 -> MaterialTheme.colorScheme.error
                            b.warnings > 0 -> Avertissement
                            else -> Reussite
                        },
                    )
                    b.checks.filter { it.statut != "ok" }.forEach { LigneVerification(it) }
                    val bonnes = b.checks.filter { it.statut == "ok" }
                    if (bonnes.isNotEmpty()) {
                        Row(
                            Modifier.clip(RoundedCornerShape(8.dp)).clickable { reussiesOuvertes = !reussiesOuvertes }.padding(vertical = 4.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Icon(if (reussiesOuvertes) Icons.Filled.ExpandLess else Icons.Filled.ExpandMore, null, tint = MaterialTheme.colorScheme.primary)
                            Text("${bonnes.size} vérification(s) réussie(s)", color = MaterialTheme.colorScheme.primary, style = MaterialTheme.typography.labelLarge)
                        }
                        AnimatedVisibility(reussiesOuvertes) {
                            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) { bonnes.forEach { LigneVerification(it) } }
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun LigneVerification(v: Verification) {
    val presse = LocalClipboardManager.current
    val avis = LocalAvis.current
    val (icone, teinte) = when (v.statut) {
        "erreur" -> Icons.Filled.Error to MaterialTheme.colorScheme.error
        "avertissement" -> Icons.Filled.Warning to Avertissement
        else -> Icons.Filled.CheckCircle to Reussite
    }
    Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
        Icon(icone, contentDescription = v.statut, tint = teinte, modifier = Modifier.size(20.dp))
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(2.dp)) {
            Text(v.nom, fontWeight = FontWeight.SemiBold, style = MaterialTheme.typography.bodyMedium)
            if (v.detail.isNotBlank()) {
                Text(v.detail, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            v.commande?.takeIf { it.isNotBlank() }?.let { cmd ->
                Surface(color = MaterialTheme.colorScheme.surfaceContainerHighest, shape = RoundedCornerShape(8.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(start = 10.dp)) {
                        Text(cmd, Modifier.weight(1f).padding(vertical = 6.dp), fontFamily = FontFamily.Monospace, style = MaterialTheme.typography.bodySmall)
                        IconButton(onClick = { presse.setText(AnnotatedString(cmd)); avis.dire("Commande copiée.") }) {
                            Icon(Icons.Filled.ContentCopy, contentDescription = "Copier la commande : $cmd", Modifier.size(18.dp))
                        }
                    }
                }
            }
        }
    }
}
