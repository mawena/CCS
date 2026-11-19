package com.mawena.ccs.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.AssistChip
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.mawena.ccs.BuildConfig
import com.mawena.ccs.reseau.Carte
import com.mawena.ccs.reseau.Cartes
import com.mawena.ccs.reseau.EtatConnexion
import com.mawena.ccs.reseau.Jauge
import kotlinx.coroutines.launch

/** Accueil provisoire : version du serveur (`/api/health`) et cartes des comptes (`accounts.cards`). */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun EcranAccueil(modele: ModeleAppli) {
    val etat by modele.etat.collectAsStateWithLifecycle()
    val identifiants by modele.identifiants.collectAsStateWithLifecycle()
    val portee = rememberCoroutineScope()
    var version by remember { mutableStateOf<String?>(null) }
    var cartes by remember { mutableStateOf<Cartes?>(null) }
    var erreur by remember { mutableStateOf<String?>(null) }
    var charge by remember { mutableStateOf(false) }
    val connecte = etat is EtatConnexion.Connecte

    suspend fun charger() {
        charge = true
        val serveur = identifiants?.serveur ?: modele.adresse.value
        version = runCatching { modele.depot.api.sante(serveur).version }.getOrElse { version }
        runCatching { modele.depot.client.appeler("accounts.cards", Cartes.serializer()) }
            .onSuccess { cartes = it; erreur = null }
            .onFailure { erreur = it.message }
        charge = false
    }

    LaunchedEffect(connecte) { if (connecte) charger() }

    PullToRefreshBox(
        isRefreshing = charge,
        onRefresh = { portee.launch { charger() } },
        modifier = Modifier.fillMaxSize(),
    ) {
        LazyColumn(
            Modifier.fillMaxSize(),
            contentPadding = PaddingValues(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            item {
                Card(Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                        Text("CCS", style = MaterialTheme.typography.titleLarge)
                        Text("Serveur : ${identifiants?.serveur.orEmpty()}")
                        Text("Version du serveur : ${version ?: "…"}")
                        Text("Appli : ${BuildConfig.VERSION_NAME}")
                        Text(
                            "Compte : ${identifiants?.utilisateur.orEmpty()}" +
                                if (identifiants?.portier == true) " (Portier)" else " (jeton d'appareil)",
                        )
                    }
                }
            }
            erreur?.let { e -> item { Text(e, color = MaterialTheme.colorScheme.error) } }
            cartes?.let { c ->
                if (c.cards.isEmpty()) item { Text("Aucun compte.") }
                items(c.cards, key = { it.name }) { CarteCompte(it) }
            }
        }
    }
}

@Composable
private fun CarteCompte(c: Carte) {
    val teinte = remember(c.color) {
        runCatching { Color(android.graphics.Color.parseColor(c.color)) }.getOrNull()
    }
    Card(
        Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceContainer),
    ) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Box(Modifier.size(12.dp).background(teinte ?: MaterialTheme.colorScheme.primary, CircleShape))
                Spacer(Modifier.width(8.dp))
                Column(Modifier.weight(1f)) {
                    Text(c.name, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
                    val sous = listOf(c.plan, c.email).filter { it.isNotBlank() }.joinToString(" · ")
                    if (sous.isNotEmpty()) {
                        Text(sous, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                }
                if (c.active) AssistChip(onClick = {}, label = { Text("Actif") })
            }
            c.status?.let { s ->
                Text(
                    s.text,
                    color = when (s.kind) {
                        "error" -> MaterialTheme.colorScheme.error
                        "warning" -> Color(0xFFE5A50A)
                        "success" -> Color(0xFF33D17A)
                        else -> MaterialTheme.colorScheme.onSurface
                    },
                    style = MaterialTheme.typography.bodyMedium,
                )
            }
            c.main.forEach { JaugeCompte(it) }
            c.details.forEach {
                Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
    }
}

@Composable
private fun JaugeCompte(j: Jauge) {
    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Row {
            Text(j.label, Modifier.weight(1f), style = MaterialTheme.typography.bodyMedium)
            Text("${j.percent.toInt()} %", style = MaterialTheme.typography.bodyMedium)
        }
        val p = (j.percent / 100).toFloat().coerceIn(0f, 1f)
        LinearProgressIndicator(
            progress = { p }, Modifier.fillMaxWidth(),
            color = when {
                p >= 0.9f -> MaterialTheme.colorScheme.error
                p >= 0.7f -> Color(0xFFE5A50A)
                else -> MaterialTheme.colorScheme.primary
            },
        )
        if (j.reset.isNotBlank()) {
            Text(j.reset, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}
