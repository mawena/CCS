package com.mawena.ccs.ui

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.filled.BarChart
import androidx.compose.material.icons.filled.ExpandLess
import androidx.compose.material.icons.filled.ExpandMore
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.SwapHoriz
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExposedDropdownMenuBox
import androidx.compose.material3.ExposedDropdownMenuDefaults
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.Icon
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.ListItem
import androidx.compose.material3.ListItemDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.MenuAnchorType
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
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
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.repeatOnLifecycle
import com.mawena.ccs.BuildConfig
import com.mawena.ccs.logique.Format
import com.mawena.ccs.reseau.Carte
import com.mawena.ccs.reseau.Cartes
import com.mawena.ccs.reseau.EtatComptes
import com.mawena.ccs.reseau.EtatConnexion
import com.mawena.ccs.reseau.Jauge
import com.mawena.ccs.reseau.ResultatBascule
import com.mawena.ccs.reseau.secondes
import com.mawena.ccs.reseau.texte
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

/**
 * Accueil (`home.js`) : compte actif et meilleur compte, cartes des comptes (jauges, statut,
 * détails repliables, bascule avec confirmation), actualisation, pause, bilan de santé, accès à
 * l'analyse. Relu chaque minute tant que l'écran est visible, et à chaque reconnexion.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun EcranAccueil(modele: ModeleAppli, ouvrirAnalyse: () -> Unit) {
    val etat by modele.etat.collectAsStateWithLifecycle()
    val identifiants by modele.identifiants.collectAsStateWithLifecycle()
    val client = modele.depot.client
    val avis = LocalAvis.current
    val portee = rememberCoroutineScope()
    val cycle = LocalLifecycleOwner.current.lifecycle
    var comptes by remember { mutableStateOf<EtatComptes?>(null) }
    var cartes by remember { mutableStateOf<Cartes?>(null) }
    var erreur by remember { mutableStateOf<String?>(null) }
    var charge by remember { mutableStateOf(false) }
    var actualisation by remember { mutableStateOf(false) }
    var version by remember { mutableStateOf<String?>(null) }
    val ouverts = remember { mutableStateListOf<String>() }   // « Détails » ouverts
    var aBasculer by remember { mutableStateOf<Carte?>(null) }
    var bascule by remember { mutableStateOf<String?>(null) }  // compte en cours de bascule
    val connecte = etat is EtatConnexion.Connecte

    suspend fun charger() {
        charge = true
        try {
            coroutineScope {
                val e = async { client.appeler("accounts.state", EtatComptes.serializer()) }
                val c = async { client.appeler("accounts.cards", Cartes.serializer()) }
                comptes = e.await()
                cartes = c.await()
            }
            erreur = null
        } catch (e: Exception) {
            erreur = "Comptes indisponibles : ${e.texte()}"
        } finally {
            charge = false
        }
        if (version == null) {
            val serveur = identifiants?.serveur ?: modele.adresse.value
            version = runCatching { modele.depot.api.sante(serveur).version }.getOrNull()
        }
    }

    fun basculer(c: Carte) {
        portee.launch {
            bascule = c.name
            try {
                val r = client.appeler("accounts.switch", ResultatBascule.serializer(), buildJsonObject { put("name", c.name) })
                if (!r.ok) throw IllegalStateException("La bascule a échoué.")
                avis.dire("Compte actif : ${c.name}.")
            } catch (e: Exception) {
                avis.dire(e.message ?: "La bascule a échoué.", action = "Réessayer") { basculer(c) }
            } finally {
                bascule = null
            }
            charger()
        }
    }

    fun actualiser() {
        portee.launch {
            actualisation = true
            try {
                client.appeler("accounts.refresh")
            } catch (e: Exception) {
                actualisation = false
                avis.dire(e.texte(), action = "Réessayer") { actualiser() }
                return@launch
            }
            avis.dire("Actualisation demandée : les chiffres arrivent dans quelques secondes.")
            delay(4000)
            charger()
            actualisation = false
            avis.dire("Comptes actualisés.")
        }
    }

    LaunchedEffect(connecte) {
        if (!connecte) return@LaunchedEffect
        cycle.repeatOnLifecycle(Lifecycle.State.STARTED) {
            while (true) {
                charger()
                delay(60_000)
            }
        }
    }

    PullToRefreshBox(
        isRefreshing = charge && cartes != null,
        onRefresh = { portee.launch { charger() } },
        modifier = Modifier.fillMaxSize(),
    ) {
        LazyColumn(
            Modifier.fillMaxSize(),
            contentPadding = PaddingValues(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            val c = cartes
            val e = comptes
            if (c == null || e == null) {
                item { if (erreur != null) EtatErreur(erreur!!) { portee.launch { charger() } } else Chargement("Chargement des comptes…") }
            } else {
                erreur?.let { m -> item { Text(m, color = MaterialTheme.colorScheme.error) } }
                item { LigneEtat(e, c, actualisation) { actualiser() } }
                if (c.cards.isEmpty()) {
                    item { EtatVide("Aucun compte enregistré : ajoute-en un avec « ccs add » dans un terminal.") }
                }
                items(c.cards, key = { it.name }) { carte ->
                    CarteCompte(
                        carte,
                        ouvert = carte.name in ouverts,
                        basculeEnCours = bascule == carte.name,
                        surDetails = { if (carte.name in ouverts) ouverts.remove(carte.name) else ouverts.add(carte.name) },
                        surBasculer = { aBasculer = carte },
                    )
                }
                item { CartePause(modele, e) { portee.launch { charger() } } }
            }
            item { CarteBilan(modele) }
            item {
                Card(Modifier.fillMaxWidth(), colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceContainer)) {
                    ListItem(
                        headlineContent = { Text("Analyse") },
                        supportingContent = { Text("Usage par projet, modèle, compte et heure") },
                        leadingContent = { Icon(Icons.Filled.BarChart, null) },
                        trailingContent = { Icon(Icons.AutoMirrored.Filled.KeyboardArrowRight, null) },
                        colors = ListItemDefaults.colors(containerColor = Color.Transparent),
                        modifier = Modifier.clickable(onClick = ouvrirAnalyse),
                    )
                }
            }
            item {
                Text(
                    "Serveur ${version ?: "…"} · appli ${BuildConfig.VERSION_NAME} · ${identifiants?.utilisateur.orEmpty()}" +
                        if (identifiants?.portier == true) " (Portier)" else "",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.fillMaxWidth().padding(top = 4.dp),
                )
            }
        }
    }

    aBasculer?.let { carte ->
        val n = cartes?.chatsEnCours ?: 0
        Confirmation(
            titre = "Basculer sur « ${carte.name} » ?",
            texte = if (n > 0) "$n chat(s) tournent en ce moment : ils risquent d'être perturbés par le changement de compte."
            else "Les nouveaux chats et le terminal utiliseront ce compte.",
            confirmer = "Basculer",
            surOui = { aBasculer = null; basculer(carte) },
            surNon = { aBasculer = null },
        )
    }
}

/** « Compte actif : X » ; meilleur compte, décision de la bascule automatique, date du relevé. */
@Composable
private fun LigneEtat(e: EtatComptes, c: Cartes, enCours: Boolean, actualiser: () -> Unit) {
    Card(Modifier.fillMaxWidth(), colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceContainer)) {
        Row(Modifier.padding(start = 16.dp, top = 12.dp, bottom = 12.dp, end = 8.dp), verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(2.dp)) {
                Text("Compte actif : ${e.active ?: "aucun"}", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
                val meilleur = c.best.texte("name")?.let { n -> "Meilleur compte : $n" + (c.best.texte("reason")?.let { " ($it)" } ?: "") }
                val decision = c.bascule.texte("decision", "reason")?.let { "Bascule automatique : $it" }
                val maj = c.misAJour.secondes()?.let { "mis à jour ${Format.ilYA(it)}" }
                val sous = listOfNotNull(meilleur, decision, maj).joinToString(" · ")
                if (sous.isNotEmpty()) {
                    Text(sous, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
            if (enCours) {
                CircularProgressIndicator(Modifier.padding(12.dp).size(20.dp), strokeWidth = 2.dp)
            } else {
                TextButton(onClick = actualiser) {
                    Icon(Icons.Filled.Refresh, null, Modifier.size(18.dp))
                    Spacer(Modifier.width(6.dp))
                    Text("Actualiser")
                }
            }
        }
    }
}

@Composable
private fun Badge(texte: String, fond: Color, encre: Color) {
    Surface(color = fond, contentColor = encre, shape = RoundedCornerShape(50)) {
        Text(texte, Modifier.padding(horizontal = 10.dp, vertical = 3.dp), style = MaterialTheme.typography.labelMedium)
    }
}

@Composable
private fun CarteCompte(
    c: Carte,
    ouvert: Boolean,
    basculeEnCours: Boolean,
    surDetails: () -> Unit,
    surBasculer: () -> Unit,
) {
    val teinte = couleurDe(c.color)
    Card(
        Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceContainer),
        border = if (c.active) BorderStroke(2.dp, teinte) else null,
    ) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Pastille(teinte, 12.dp)
                Column(Modifier.weight(1f)) {
                    Text(c.name, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
                    val sous = listOf(c.email, c.org).filter { it.isNotBlank() }.joinToString(" · ")
                    if (sous.isNotEmpty()) {
                        Text(sous, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                }
                if (c.plan.isNotBlank()) Badge(c.plan, MaterialTheme.colorScheme.surfaceContainerHighest, MaterialTheme.colorScheme.onSurface)
                if (c.active) Badge("Actif", teinte, Color.White)
            }
            c.main.forEach { JaugeCompte(it, teinte) }
            if (!c.donnees && c.status == null) {
                Text("Pas encore de relevé pour ce compte.", style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            c.status?.let { s ->
                Text(
                    s.text,
                    color = when (s.kind) {
                        "error" -> MaterialTheme.colorScheme.error
                        "warning" -> Avertissement
                        "success" -> Reussite
                        else -> MaterialTheme.colorScheme.onSurface
                    },
                    style = MaterialTheme.typography.bodyMedium,
                )
            }
            val aDesDetails = c.others.isNotEmpty() || c.details.isNotEmpty() || c.erreur != null
            if (aDesDetails) {
                Row(
                    Modifier.clip(RoundedCornerShape(8.dp)).clickable(onClick = surDetails).padding(vertical = 4.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Icon(if (ouvert) Icons.Filled.ExpandLess else Icons.Filled.ExpandMore, null, tint = MaterialTheme.colorScheme.primary)
                    Text("Détails", color = MaterialTheme.colorScheme.primary, style = MaterialTheme.typography.labelLarge)
                }
                AnimatedVisibility(ouvert) {
                    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        c.others.forEach { JaugeCompte(it, teinte) }
                        c.details.forEach {
                            Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                        c.erreur?.let {
                            Text("Message d'origine : $it", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                    }
                }
            }
            if (!c.active) {
                FilledTonalButton(onClick = surBasculer, enabled = !basculeEnCours, modifier = Modifier.fillMaxWidth()) {
                    if (basculeEnCours) CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp)
                    else Icon(Icons.Filled.SwapHoriz, null, Modifier.size(18.dp))
                    Spacer(Modifier.width(8.dp))
                    Text("Basculer sur ce compte")
                }
            }
        }
    }
}

@Composable
private fun JaugeCompte(j: Jauge, teinte: Color) {
    val pct = Format.pourcent(j.percent)
    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Row {
            Text(j.label, Modifier.weight(1f), style = MaterialTheme.typography.bodyMedium)
            Text("$pct %", style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.Bold)
        }
        LinearProgressIndicator(
            progress = { pct / 100f },
            modifier = Modifier.fillMaxWidth().height(8.dp),
            color = when {
                pct >= 90 -> MaterialTheme.colorScheme.error
                pct >= 70 -> Avertissement
                else -> teinte
            },
            trackColor = MaterialTheme.colorScheme.surfaceContainerHighest,
            gapSize = 0.dp,
            drawStopIndicator = {},
        )
        if (j.reset.isNotBlank()) {
            Text(j.reset, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}

/** Pause de la bascule et de l'orchestrateur (`pause.set`). */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun CartePause(modele: ModeleAppli, e: EtatComptes, relire: () -> Unit) {
    val avis = LocalAvis.current
    val portee = rememberCoroutineScope()
    var occupe by remember { mutableStateOf(false) }
    val choix = e.choix
    var choisi by remember(choix) { mutableStateOf(choix.firstOrNull()) }
    var menu by remember { mutableStateOf(false) }

    fun appliquer(valeur: String, fait: String) {
        portee.launch {
            occupe = true
            try {
                modele.depot.client.appeler("pause.set", buildJsonObject { put("choice", valeur) })
                avis.dire(fait)
            } catch (x: Exception) {
                avis.dire(x.texte())
            }
            occupe = false
            relire()
        }
    }

    Card(Modifier.fillMaxWidth(), colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceContainer)) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            val p = e.pause
            Text(
                if (p != null) "En pause ${p.label}" else "Bascule et orchestrateur actifs",
                style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold,
            )
            if (p != null) {
                FilledTonalButton(onClick = { appliquer("off", "Pause levée.") }, enabled = !occupe) { Text("Reprendre") }
            } else if (choix.isNotEmpty()) {
                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    ExposedDropdownMenuBox(expanded = menu, onExpandedChange = { menu = it }, modifier = Modifier.weight(1f)) {
                        OutlinedTextField(
                            value = choisi?.second.orEmpty(), onValueChange = {}, readOnly = true, singleLine = true,
                            label = { Text("Mettre en pause") },
                            trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(menu) },
                            modifier = Modifier.menuAnchor(MenuAnchorType.PrimaryNotEditable).fillMaxWidth(),
                        )
                        ExposedDropdownMenu(expanded = menu, onDismissRequest = { menu = false }) {
                            choix.forEach { c ->
                                DropdownMenuItem(text = { Text(c.second) }, onClick = { choisi = c; menu = false })
                            }
                        }
                    }
                    FilledTonalButton(
                        onClick = { choisi?.let { appliquer(it.first, "Bascule et orchestrateur en pause.") } },
                        enabled = !occupe && choisi != null,
                    ) { Text("Pause") }
                }
            }
        }
    }
}
