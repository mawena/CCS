package com.mawena.ccs.ui.chat

import androidx.compose.animation.animateContentSize
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Label
import androidx.compose.material.icons.filled.Build
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Done
import androidx.compose.material.icons.filled.ExpandLess
import androidx.compose.material.icons.filled.ExpandMore
import androidx.compose.material.icons.filled.SmartToy
import androidx.compose.material.icons.filled.Stop
import androidx.compose.material.icons.filled.Terminal
import androidx.compose.material3.AssistChip
import androidx.compose.material3.Button
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.Stable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.mawena.ccs.logique.ActionNote
import com.mawena.ccs.logique.Citation
import com.mawena.ccs.logique.Diff
import com.mawena.ccs.logique.ElementFil
import com.mawena.ccs.logique.LigneFil
import com.mawena.ccs.logique.Outils
import com.mawena.ccs.logique.StatutAgent
import com.mawena.ccs.ui.Avertissement
import com.mawena.ccs.ui.Reussite

/** Ce que le fil peut demander à l'écran. Créé une fois : les éléments inchangés ne se redessinent pas. */
@Stable
class ActionsFil(
    val menuMessage: (ElementFil) -> Unit,
    val voirAgent: (String) -> Unit,
    val repondre: (requestId: String, decision: String, motif: String) -> Unit,
    val questions: (requestId: String, reponses: Map<String, Any>) -> Unit,
    val arreterShell: (String) -> Unit,
    val reprendre: () -> Unit,
    val compacter: () -> Unit,
    val voirEtiquette: (String) -> Unit,
)

/** Une ligne du fil. `etiquettes` : celles du message montré (s'il en a). */
@Composable
fun LigneVue(l: LigneFil, etiquettes: List<String>?, surligne: Boolean, actions: ActionsFil) {
    Column(Modifier.fillMaxWidth().alpha(if (l.grise) 0.55f else 1f)) {
        when (l) {
            is LigneFil.Groupe -> Groupe(l.outils, surligne)
            is LigneFil.Seul -> when (val e = l.element) {
                is ElementFil.MsgToi -> MessageToi(e, etiquettes, surligne, actions)
                is ElementFil.MsgClaude -> MessageClaude(e, etiquettes, surligne, actions)
                is ElementFil.Outil -> CarteOutil(e, surligne)
                is ElementFil.Agent -> CarteAgent(e, surligne, actions)
                is ElementFil.Note -> NoteVue(e, actions)
                is ElementFil.Separateur -> SeparateurVue(e)
                is ElementFil.Demande -> CarteDemande(e, actions)
                is ElementFil.Questions -> CarteQuestions(e, actions)
                is ElementFil.Commande -> CarteCommande(e, surligne, actions)
                is ElementFil.Arrete -> CarteArret(e, actions)
            }
        }
    }
}

@Composable
private fun cadre(surligne: Boolean) = if (surligne) BorderStroke(2.dp, Avertissement) else null

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun Pastilles(etiquettes: List<String>?, actions: ActionsFil, fin: Boolean) {
    if (etiquettes.isNullOrEmpty()) return
    FlowRow(
        Modifier.fillMaxWidth().padding(top = 2.dp),
        horizontalArrangement = Arrangement.spacedBy(4.dp, if (fin) Alignment.End else Alignment.Start),
    ) {
        etiquettes.forEach { t ->
            AssistChip(
                onClick = { actions.voirEtiquette(t) },
                label = { Text(t, style = MaterialTheme.typography.labelSmall) },
                leadingIcon = { Icon(Icons.AutoMirrored.Filled.Label, null, Modifier.size(14.dp)) },
                modifier = Modifier.heightIn(max = 28.dp),
            )
        }
    }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun MessageToi(e: ElementFil.MsgToi, etiquettes: List<String>?, surligne: Boolean, actions: ActionsFil) {
    val d = remember(e.texte) { Citation.decouper(e.texte) }
    Column(Modifier.fillMaxWidth(), horizontalAlignment = Alignment.End) {
        Surface(
            color = MaterialTheme.colorScheme.primaryContainer,
            contentColor = MaterialTheme.colorScheme.onPrimaryContainer,
            shape = RoundedCornerShape(16.dp, 16.dp, 4.dp, 16.dp),
            border = cadre(surligne),
            modifier = Modifier.widthIn(max = 340.dp).combinedClickable(onClick = {}, onLongClick = { actions.menuMessage(e) }),
        ) {
            Column(Modifier.padding(horizontal = 12.dp, vertical = 8.dp)) {
                if (d != null) BlocCite(d.auteur, d.texte)
                Text((d?.corps ?: e.texte), style = MaterialTheme.typography.bodyMedium)
                if (e.images > 0) {
                    Text("${e.images} image(s) jointe(s)", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
        }
        Pastilles(etiquettes, actions, fin = true)
    }
}

/** Citation dans une bulle : l'auteur et le passage, replié sur trois lignes (toucher le déplie). */
@Composable
fun BlocCite(auteur: Citation.Auteur, texte: String) {
    var ouvert by remember { mutableStateOf(false) }
    Surface(
        color = MaterialTheme.colorScheme.surface.copy(alpha = 0.5f),
        shape = RoundedCornerShape(8.dp),
        modifier = Modifier.fillMaxWidth().padding(bottom = 6.dp).clickable { ouvert = !ouvert },
    ) {
        Column(Modifier.padding(8.dp).animateContentSize()) {
            Text(auteur.affiche, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.primary, fontWeight = FontWeight.SemiBold)
            if (auteur == Citation.Auteur.Claude && ouvert) MarkdownVue(texte)
            else Text(texte, maxLines = if (ouvert) Int.MAX_VALUE else 3, overflow = TextOverflow.Ellipsis, style = MaterialTheme.typography.bodySmall)
        }
    }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun MessageClaude(e: ElementFil.MsgClaude, etiquettes: List<String>?, surligne: Boolean, actions: ActionsFil) {
    Column(Modifier.fillMaxWidth()) {
        Surface(
            color = MaterialTheme.colorScheme.surfaceContainer,
            shape = RoundedCornerShape(16.dp, 16.dp, 16.dp, 4.dp),
            border = cadre(surligne),
            modifier = Modifier.fillMaxWidth().combinedClickable(onClick = {}, onLongClick = { actions.menuMessage(e) }),
        ) {
            MarkdownVue(e.texte, Modifier.padding(horizontal = 12.dp, vertical = 10.dp))
        }
        Pastilles(etiquettes, actions, fin = false)
    }
}

@Composable
private fun Marque(fini: Boolean, erreur: Boolean) {
    when {
        !fini -> CircularProgressIndicator(Modifier.size(14.dp), strokeWidth = 2.dp)
        erreur -> Icon(Icons.Filled.Close, "erreur", Modifier.size(16.dp), tint = MaterialTheme.colorScheme.error)
        else -> Icon(Icons.Filled.Done, "fini", Modifier.size(16.dp), tint = Reussite)
    }
}

@Composable
private fun Statistiques(d: Diff.Fichier) {
    Text("+${d.ajouts}", style = MaterialTheme.typography.labelSmall, color = Color(0xFF2EA043), modifier = Modifier.padding(start = 6.dp))
    Text("−${d.retraits}", style = MaterialTheme.typography.labelSmall, color = Color(0xFFE5534B), modifier = Modifier.padding(start = 4.dp))
}

/** Carte d'un outil : repliée sur une ligne (nom, cible, état), dépliée : diff ou paramètres, puis résultat. */
@Composable
fun CarteOutil(e: ElementFil.Outil, surligne: Boolean = false) {
    var ouvert by rememberSaveable(e.cle) { mutableStateOf(false) }
    Surface(
        color = MaterialTheme.colorScheme.surfaceContainerLow,
        shape = RoundedCornerShape(10.dp),
        border = cadre(surligne) ?: BorderStroke(1.dp, if (e.erreur) MaterialTheme.colorScheme.error.copy(alpha = 0.5f) else MaterialTheme.colorScheme.outlineVariant),
        modifier = Modifier.fillMaxWidth().padding(start = if (e.imbrique) 16.dp else 0.dp),
    ) {
        Column(Modifier.animateContentSize()) {
            Row(
                Modifier.fillMaxWidth().clickable { ouvert = !ouvert }.padding(horizontal = 10.dp, vertical = 8.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Icon(if (e.nom == "Bash") Icons.Filled.Terminal else Icons.Filled.Build, null, Modifier.size(16.dp), tint = MaterialTheme.colorScheme.onSurfaceVariant)
                Text(Outils.libelle(e.nom), Modifier.padding(start = 6.dp), style = MaterialTheme.typography.labelLarge, fontWeight = FontWeight.SemiBold)
                Text(
                    e.cible, Modifier.weight(1f).padding(start = 6.dp), maxLines = 1, overflow = TextOverflow.Ellipsis,
                    style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
                    fontFamily = if (e.nom == "Bash") FontFamily.Monospace else null,
                )
                e.diff?.let { Statistiques(it) }
                Spacer(Modifier.width(6.dp))
                Marque(e.fini, e.erreur)
            }
            if (ouvert) {
                HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                Column(Modifier.padding(8.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    when {
                        e.diff != null -> VueDiff(e.diff)
                        e.details.isNotEmpty() -> TexteMono(e.details, 30)
                    }
                    e.resultat?.let { TexteMono(it.ifEmpty { "(aucune sortie)" }, 40, erreur = e.erreur) }
                }
            }
        }
    }
}

/** Texte à chasse fixe, coupé à `lignes` lignes avec « Tout afficher ». */
@Composable
fun TexteMono(t: String, lignes: Int, erreur: Boolean = false) {
    var tout by remember { mutableStateOf(false) }
    val long = remember(t) { t.count { it == '\n' } >= lignes || t.length > 4000 }
    val montre = remember(t, tout) { if (!long || tout) t else t.lineSequence().take(lignes).joinToString("\n").take(4000) }
    val cc = couleursCode()
    Surface(color = cc.fond, shape = RoundedCornerShape(6.dp), modifier = Modifier.fillMaxWidth()) {
        Column {
            Text(
                montre,
                Modifier.horizontalScroll(rememberScrollState()).padding(8.dp),
                fontFamily = FontFamily.Monospace, fontSize = 12.sp, lineHeight = 16.sp, softWrap = false,
                color = if (erreur) MaterialTheme.colorScheme.error else cc.texte,
            )
            if (long) TextButton(onClick = { tout = !tout }) { Text(if (tout) "Réduire" else "Tout afficher") }
        }
    }
}

@Composable
fun VueDiff(d: Diff.Fichier) {
    val ouvre = LocalOuvreFichier.current
    Column {
        Text(
            d.chemin,
            if (ouvre != null) Modifier.clickable { ouvre.ouvrir(d.chemin, null) } else Modifier,
            style = MaterialTheme.typography.labelSmall,
            color = if (ouvre != null) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurfaceVariant,
            textDecoration = if (ouvre != null) androidx.compose.ui.text.style.TextDecoration.Underline else null,
            maxLines = 2, overflow = TextOverflow.Ellipsis,
        )
        CorpsDiff(d.lignes, Modifier.padding(top = 4.dp))
    }
}

/**
 * Lignes d'un diff (chat, Git) : ajouts en vert, retraits en rouge, séparateurs de morceaux ;
 * numéros de ligne quand ils sont connus (git). Au-delà de `max` lignes : « Tout afficher ».
 */
@Composable
fun CorpsDiff(lignesDiff: List<Diff.Ligne>, modifier: Modifier = Modifier, max: Int = 80) {
    val cc = couleursCode()
    var tout by remember { mutableStateOf(false) }
    val lignes = if (tout || lignesDiff.size <= max) lignesDiff else lignesDiff.take(max)
    val numeros = remember(lignesDiff) { lignesDiff.any { it.ancien != null || it.nouveau != null } }
    val chiffres = remember(lignesDiff) { (lignesDiff.maxOfOrNull { maxOf(it.ancien ?: 0, it.nouveau ?: 0) } ?: 0).toString().length }
    Column(modifier) {
        Surface(color = cc.fond, shape = RoundedCornerShape(6.dp), modifier = Modifier.fillMaxWidth()) {
            Column(Modifier.horizontalScroll(rememberScrollState()).padding(vertical = 6.dp)) {
                lignes.forEach { l ->
                    val (signe, fond, encre) = when (l.genre) {
                        Diff.Genre.Ajout -> Triple("+", cc.ajout.copy(alpha = 0.14f), cc.ajout)
                        Diff.Genre.Retrait -> Triple("−", cc.retrait.copy(alpha = 0.14f), cc.retrait)
                        Diff.Genre.Morceau -> Triple("", Color.Transparent, cc.titre)
                        Diff.Genre.Contexte -> Triple(" ", Color.Transparent, cc.texte)
                    }
                    val no = if (numeros && l.genre != Diff.Genre.Morceau) {
                        (l.ancien?.toString() ?: "").padStart(chiffres) + " " + (l.nouveau?.toString() ?: "").padStart(chiffres) + " "
                    } else ""
                    Text(
                        "$no$signe ${l.texte}",
                        Modifier.background(fond).padding(horizontal = 8.dp),
                        fontFamily = FontFamily.Monospace, fontSize = 12.sp, lineHeight = 16.sp, softWrap = false, color = encre,
                    )
                }
            }
        }
        if (lignesDiff.size > max) TextButton(onClick = { tout = !tout }) { Text(if (tout) "Réduire" else "Tout afficher (${lignesDiff.size} lignes)") }
    }
}

@Composable
private fun Groupe(outils: List<ElementFil.Outil>, surligne: Boolean) {
    var ouvert by rememberSaveable(outils.first().cle) { mutableStateOf(false) }
    val dernier = outils.last()
    val enCours = outils.any { !it.fini }
    Surface(
        color = MaterialTheme.colorScheme.surfaceContainerLow, shape = RoundedCornerShape(10.dp),
        border = cadre(surligne) ?: BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(Modifier.animateContentSize()) {
            Row(
                Modifier.fillMaxWidth().clickable { ouvert = !ouvert }.padding(horizontal = 10.dp, vertical = 8.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Icon(if (ouvert) Icons.Filled.ExpandLess else Icons.Filled.ExpandMore, null, Modifier.size(18.dp))
                Text("${outils.size} actions", Modifier.padding(start = 4.dp), style = MaterialTheme.typography.labelLarge, fontWeight = FontWeight.SemiBold)
                Text(
                    "· ${Outils.libelle(dernier.nom)} ${dernier.cible}", Modifier.weight(1f).padding(start = 6.dp),
                    maxLines = 1, overflow = TextOverflow.Ellipsis, style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Marque(!enCours, outils.any { it.erreur })
            }
            if (ouvert) Column(Modifier.padding(6.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                outils.forEach { key(it.cle) { CarteOutil(it) } }
            }
        }
    }
}

@Composable
private fun CarteAgent(e: ElementFil.Agent, surligne: Boolean, actions: ActionsFil) {
    var ouvert by rememberSaveable(e.cle) { mutableStateOf(false) }
    Surface(
        color = MaterialTheme.colorScheme.secondaryContainer.copy(alpha = 0.5f), shape = RoundedCornerShape(10.dp),
        border = cadre(surligne), modifier = Modifier.fillMaxWidth(),
    ) {
        Column(Modifier.padding(horizontal = 10.dp, vertical = 6.dp).animateContentSize()) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(Icons.Filled.SmartToy, null, Modifier.size(18.dp), tint = MaterialTheme.colorScheme.primary)
                Column(Modifier.weight(1f).padding(start = 8.dp)) {
                    Text("Sous-agent · ${e.nom}", style = MaterialTheme.typography.labelLarge, fontWeight = FontWeight.SemiBold, maxLines = 2, overflow = TextOverflow.Ellipsis)
                    Text(
                        when (e.statut) {
                            StatutAgent.Travaille -> if (e.arrierePlan) "en arrière-plan…" else "au travail…"
                            StatutAgent.Fini -> "✓ terminé"
                            StatutAgent.Arrete -> "arrêté"
                        },
                        style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                FilledTonalButton(onClick = { actions.voirAgent(e.cle) }) { Text("Voir") }
            }
            TextButton(onClick = { ouvert = !ouvert }) { Text(if (ouvert) "Masquer la consigne" else "Consigne et résultat") }
            if (ouvert) {
                TexteMono(e.consigne, 20)
                e.resultat?.let { Spacer(Modifier.size(6.dp)); MarkdownVue(it) }
            }
        }
    }
}

@Composable
private fun NoteVue(e: ElementFil.Note, actions: ActionsFil) {
    val (fond, encre) = when (e.genre) {
        "error" -> MaterialTheme.colorScheme.error.copy(alpha = 0.12f) to MaterialTheme.colorScheme.error
        "warning" -> Avertissement.copy(alpha = 0.15f) to MaterialTheme.colorScheme.onSurface
        else -> MaterialTheme.colorScheme.surfaceContainerHigh to MaterialTheme.colorScheme.onSurfaceVariant
    }
    Surface(color = fond, shape = RoundedCornerShape(8.dp), modifier = Modifier.fillMaxWidth()) {
        Row(Modifier.padding(horizontal = 10.dp, vertical = 6.dp), verticalAlignment = Alignment.CenterVertically) {
            Text(e.texte, Modifier.weight(1f), style = MaterialTheme.typography.bodySmall, color = encre)
            if (e.action == ActionNote.Compacter) OutlinedButton(onClick = actions.compacter) { Text("Compacter") }
        }
    }
}

@Composable
private fun SeparateurVue(e: ElementFil.Separateur) {
    Row(Modifier.fillMaxWidth().padding(vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
        HorizontalDivider(Modifier.weight(0.15f), color = MaterialTheme.colorScheme.primary)
        Text(
            if (e.auto) "Sujet terminé : Claude a effacé la conversation — il ne voit plus les messages au-dessus"
            else "Nouvelle conversation — Claude ne voit plus les messages au-dessus",
            Modifier.weight(0.7f).padding(horizontal = 8.dp), textAlign = TextAlign.Center,
            style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.primary,
        )
        HorizontalDivider(Modifier.weight(0.15f), color = MaterialTheme.colorScheme.primary)
    }
}

@Composable
private fun CarteDemande(e: ElementFil.Demande, actions: ActionsFil) {
    var motif by rememberSaveable(e.cle) { mutableStateOf("") }
    var details by remember { mutableStateOf(false) }
    Surface(
        color = MaterialTheme.colorScheme.surfaceContainerHigh, shape = RoundedCornerShape(12.dp),
        border = BorderStroke(2.dp, Avertissement), modifier = Modifier.fillMaxWidth(),
    ) {
        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("Claude demande : ${e.outil}", style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold)
            TexteMono(e.cible.ifEmpty { e.details }, 12)
            if (e.description.isNotEmpty()) Text(e.description, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            if (e.cible.isNotEmpty()) {
                TextButton(onClick = { details = !details }) { Text(if (details) "Masquer les détails" else "Détails") }
                if (details) TexteMono(e.details, 30)
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = { actions.repondre(e.cle, "allow", motif) }) { Text("Autoriser") }
                OutlinedButton(onClick = { actions.repondre(e.cle, "always", motif) }) { Text("Toujours") }
                OutlinedButton(onClick = { actions.repondre(e.cle, "deny", motif) }) { Text("Refuser", color = MaterialTheme.colorScheme.error) }
            }
            OutlinedTextField(motif, { motif = it }, Modifier.fillMaxWidth(), placeholder = { Text("Motif du refus (facultatif)") }, singleLine = true)
        }
    }
}

@Composable
private fun CarteQuestions(e: ElementFil.Questions, actions: ActionsFil) {
    val choix = remember(e.cle) { mutableStateMapOf<Int, Set<String>>() }
    val autres = remember(e.cle) { mutableStateMapOf<Int, String>() }
    Surface(
        color = MaterialTheme.colorScheme.surfaceContainerHigh, shape = RoundedCornerShape(12.dp),
        border = BorderStroke(2.dp, MaterialTheme.colorScheme.primary), modifier = Modifier.fillMaxWidth(),
    ) {
        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text("Claude te pose une question", style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold)
            e.questions.forEachIndexed { qi, q ->
                if (q.entete.isNotEmpty()) Text(q.entete, style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.primary)
                Text(q.question, style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.Medium)
                q.options.forEach { o ->
                    val pris = choix[qi].orEmpty().contains(o.libelle)
                    val basculer = {
                        val avant = choix[qi].orEmpty()
                        choix[qi] = if (q.plusieurs) (if (pris) avant - o.libelle else avant + o.libelle) else setOf(o.libelle)
                    }
                    Row(Modifier.fillMaxWidth().clickable(onClick = basculer), verticalAlignment = Alignment.CenterVertically) {
                        if (q.plusieurs) Checkbox(pris, { basculer() }) else RadioButton(pris, basculer)
                        Column(Modifier.weight(1f)) {
                            Text(o.libelle, style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.SemiBold)
                            if (o.description.isNotEmpty()) Text(o.description, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                    }
                }
                OutlinedTextField(
                    autres[qi].orEmpty(), { autres[qi] = it }, Modifier.fillMaxWidth(),
                    placeholder = { Text("Autre réponse (facultatif)") },
                )
                if (qi < e.questions.size - 1) HorizontalDivider(Modifier.padding(vertical = 4.dp))
            }
            Button(onClick = {
                val reponses = LinkedHashMap<String, Any>()
                e.questions.forEachIndexed { qi, q ->
                    val libre = autres[qi].orEmpty().trim()
                    val pris = q.options.map { it.libelle }.filter { it in choix[qi].orEmpty() }
                    reponses[q.question] = if (libre.isNotEmpty()) libre else if (q.plusieurs) pris else pris.firstOrNull().orEmpty()
                }
                actions.questions(e.cle, reponses)
            }) { Text("Répondre") }
        }
    }
}

@Composable
private fun CarteCommande(e: ElementFil.Commande, surligne: Boolean, actions: ActionsFil) {
    Surface(
        color = MaterialTheme.colorScheme.surfaceContainerLow, shape = RoundedCornerShape(10.dp),
        border = cadre(surligne) ?: BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant), modifier = Modifier.fillMaxWidth(),
    ) {
        Column(Modifier.padding(10.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(Icons.Filled.Terminal, null, Modifier.size(16.dp))
                Text("Commande", Modifier.padding(start = 6.dp), style = MaterialTheme.typography.labelLarge, fontWeight = FontWeight.SemiBold)
                Text("$ ${e.commande}", Modifier.weight(1f).padding(start = 6.dp), fontFamily = FontFamily.Monospace,
                    style = MaterialTheme.typography.bodySmall, maxLines = 2, overflow = TextOverflow.Ellipsis)
                Text(
                    when (e.code) { null -> "en cours…"; 0 -> "terminé"; else -> "code ${e.code}" },
                    style = MaterialTheme.typography.labelSmall,
                    color = if (e.code != null && e.code != 0) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            e.sortie?.let { TexteMono(it, 30, erreur = e.code != 0) }
            if (!e.finie && e.runId != null) {
                OutlinedButton(onClick = { actions.arreterShell(e.runId) }) {
                    Icon(Icons.Filled.Stop, null, Modifier.size(16.dp)); Text(" Arrêter")
                }
            }
        }
    }
}

@Composable
private fun CarteArret(e: ElementFil.Arrete, actions: ActionsFil) {
    Surface(color = Avertissement.copy(alpha = 0.15f), shape = RoundedCornerShape(12.dp), modifier = Modifier.fillMaxWidth()) {
        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text("Ce chat s'est arrêté", style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold)
            Text(
                if (e.reprenable) "Le pont a redémarré : Claude n'est plus lancé pour cette conversation."
                else "Le pont a redémarré et on ne retrouve pas sa conversation.",
                style = MaterialTheme.typography.bodySmall,
            )
            if (e.reprenable) Button(onClick = actions.reprendre) { Text("Reprendre la conversation") }
        }
    }
}

/** Liste des tâches de Claude, épinglée au-dessus de la saisie (repliable). */
@Composable
fun VueTaches(taches: List<com.mawena.ccs.logique.Tache>) {
    if (taches.isEmpty()) return
    var ouvert by rememberSaveable { mutableStateOf(true) }
    val faites = taches.count { it.statut == "completed" }
    val enCours = taches.firstOrNull { it.statut == "in_progress" }
    Surface(color = MaterialTheme.colorScheme.surfaceContainerHigh, modifier = Modifier.fillMaxWidth()) {
        Column(Modifier.padding(horizontal = 12.dp, vertical = 4.dp).animateContentSize()) {
            Row(Modifier.fillMaxWidth().clickable { ouvert = !ouvert }.padding(vertical = 2.dp), verticalAlignment = Alignment.CenterVertically) {
                Text("Tâches $faites/${taches.size}", style = MaterialTheme.typography.labelMedium, fontWeight = FontWeight.SemiBold)
                Text(
                    enCours?.let { " · ${it.texte}" }.orEmpty(), Modifier.weight(1f), maxLines = 1, overflow = TextOverflow.Ellipsis,
                    style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Icon(if (ouvert) Icons.Filled.ExpandMore else Icons.Filled.ExpandLess, null, Modifier.size(18.dp))
            }
            if (ouvert) Column(Modifier.heightIn(max = 160.dp).verticalScroll(rememberScrollState())) {
                taches.forEach { t ->
                    val (marque, couleur) = when (t.statut) {
                        "completed" -> "✓" to MaterialTheme.colorScheme.onSurfaceVariant
                        "in_progress" -> "▸" to MaterialTheme.colorScheme.primary
                        else -> "○" to MaterialTheme.colorScheme.onSurface
                    }
                    Text("$marque ${t.texte}", style = MaterialTheme.typography.bodySmall, color = couleur)
                }
            }
        }
    }
}
