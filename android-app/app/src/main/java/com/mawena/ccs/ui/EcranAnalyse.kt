package com.mawena.ccs.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.SegmentedButton
import androidx.compose.material3.SegmentedButtonDefaults
import androidx.compose.material3.SingleChoiceSegmentedButtonRow
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.mawena.ccs.logique.Format
import com.mawena.ccs.logique.PERIODES
import com.mawena.ccs.reseau.GrosConsommateur
import com.mawena.ccs.reseau.Rapport
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import java.util.Locale

/** Analyse (`analysis.js`) : usage pondéré par projet, modèle, compte et heure. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun EcranAnalyse(modele: ModeleAppli, retour: () -> Unit) {
    var jours by remember { mutableIntStateOf(7) }
    var rapport by remember { mutableStateOf<Rapport?>(null) }
    var erreur by remember { mutableStateOf<String?>(null) }
    var essai by remember { mutableIntStateOf(0) }

    LaunchedEffect(jours, essai) {
        rapport = null
        erreur = null
        try {
            rapport = modele.depot.client.appeler("analysis.report", Rapport.serializer(), buildJsonObject { put("days", jours) })
        } catch (e: Exception) {
            erreur = e.texte()
        }
    }

    Column(Modifier.fillMaxSize()) {
        BarreHaut("Analyse", retour = retour)
        LazyColumn(
            Modifier.fillMaxSize(),
            contentPadding = PaddingValues(start = 16.dp, end = 16.dp, bottom = 16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            item {
                SingleChoiceSegmentedButtonRow(Modifier.fillMaxWidth()) {
                    PERIODES.forEachIndexed { i, (d, libelle) ->
                        SegmentedButton(
                            selected = d == jours, onClick = { jours = d },
                            shape = SegmentedButtonDefaults.itemShape(i, PERIODES.size),
                            icon = {},
                        ) { Text(libelle, maxLines = 1, style = MaterialTheme.typography.labelMedium) }
                    }
                }
            }
            val r = rapport
            when {
                erreur != null -> item { EtatErreur(erreur!!) { essai++ } }
                r == null -> item { Chargement("Lecture des journaux…") }
                r.responses == 0 -> item {
                    EtatVide("Aucune activité sur cette période.") {
                        if (jours != 30) OutlinedButton(onClick = { jours = 30 }) { Text("Essayer 30 jours") }
                    }
                }
                else -> {
                    item {
                        CarteAnalyse {
                            Text(Format.nombreCourt(r.total), fontSize = 40.sp, fontWeight = FontWeight.Bold, color = MaterialTheme.colorScheme.primary)
                            Text("jetons pondérés · ${r.responses} réponses", color = MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                    }
                    if (r.top.isNotEmpty()) item { GrosConsommateurs(r.top) }
                    item { Barres("Par projet", r.parProjet, r.total) }
                    item { Barres("Par modèle", r.parModele, r.total) }
                    item { Barres("Par compte", r.parCompte, r.total) }
                    item { Heures(r.parHeure) }
                }
            }
        }
    }
}

@Composable
private fun CarteAnalyse(contenu: @Composable () -> Unit) {
    Card(Modifier.fillMaxWidth(), colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceContainer)) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) { contenu() }
    }
}

@Composable
private fun Barres(titre: String, donnees: Map<String, Double>, total: Double) {
    val lignes = Format.barres(donnees, total)
    if (lignes.isEmpty()) return
    CarteAnalyse {
        Text(titre, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
        lignes.forEach { (nom, _, part) ->
            Column(verticalArrangement = Arrangement.spacedBy(3.dp)) {
                Row {
                    Text(nom, Modifier.weight(1f), maxLines = 1, overflow = TextOverflow.Ellipsis, style = MaterialTheme.typography.bodyMedium)
                    Text(String.format(Locale.FRANCE, "%.1f %%", part), style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.SemiBold)
                }
                Box(Modifier.fillMaxWidth().height(8.dp).clip(RoundedCornerShape(4.dp)).background(MaterialTheme.colorScheme.surfaceContainerHighest)) {
                    Box(Modifier.fillMaxHeight().fillMaxWidth((part / 100).toFloat().coerceIn(0f, 1f)).background(MaterialTheme.colorScheme.primary))
                }
            }
        }
    }
}

/** Conversations qui pèsent le plus : titre, projet, part de l'usage, causes probables et conseils. */
@Composable
private fun GrosConsommateurs(top: List<GrosConsommateur>) {
    CarteAnalyse {
        Text("Gros consommateurs", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
        top.forEach { c ->
            Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(c.title.ifEmpty { "Sans titre" }, Modifier.weight(1f), maxLines = 1, overflow = TextOverflow.Ellipsis,
                        style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.SemiBold)
                    Text(String.format(Locale.FRANCE, "%.1f %%", c.share), style = MaterialTheme.typography.bodyMedium,
                        fontWeight = FontWeight.SemiBold, color = MaterialTheme.colorScheme.primary)
                }
                Text(
                    listOf(c.project, "${c.answers} réponses", "${com.mawena.ccs.logique.Consommation.jetons(c.contexteMoyen)} relus en moyenne")
                        .filter(String::isNotEmpty).joinToString(" · "),
                    maxLines = 1, overflow = TextOverflow.Ellipsis,
                    style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                c.causes.forEach { cause ->
                    Text("• $cause", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
        }
    }
}

@Composable
private fun Heures(parHeure: List<Double>) {
    if (parHeure.isEmpty()) return
    val pic = parHeure.maxOrNull()?.coerceAtLeast(1.0) ?: 1.0
    CarteAnalyse {
        Text("Par heure", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
        Row(
            Modifier.fillMaxWidth().height(120.dp),
            horizontalArrangement = Arrangement.spacedBy(2.dp),
            verticalAlignment = Alignment.Bottom,
        ) {
            parHeure.forEach { v ->
                Box(
                    Modifier.weight(1f).fillMaxHeight((v / pic).toFloat().coerceIn(0.01f, 1f))
                        .clip(RoundedCornerShape(topStart = 2.dp, topEnd = 2.dp))
                        .background(MaterialTheme.colorScheme.primary),
                )
            }
        }
        Row(Modifier.fillMaxWidth()) {
            listOf("0 h", "6 h", "12 h", "18 h", "23 h").forEachIndexed { i, t ->
                Text(
                    t, Modifier.weight(1f), style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    textAlign = if (i == 4) androidx.compose.ui.text.style.TextAlign.End else androidx.compose.ui.text.style.TextAlign.Start,
                )
            }
        }
    }
}
