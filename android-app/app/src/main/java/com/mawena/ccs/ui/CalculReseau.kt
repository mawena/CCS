package com.mawena.ccs.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Computer
import androidx.compose.material.icons.filled.ContentCopy
import androidx.compose.material.icons.filled.ExpandLess
import androidx.compose.material.icons.filled.ExpandMore
import androidx.compose.material.icons.filled.Memory
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Support
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Card
import androidx.compose.material3.Checkbox
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
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
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.mawena.ccs.logique.Calcul
import com.mawena.ccs.reseau.CcsClient
import com.mawena.ccs.reseau.JournalTravail
import com.mawena.ccs.reseau.Machine
import com.mawena.ccs.reseau.PcAjoute
import com.mawena.ccs.reseau.ReglagesRicochet
import com.mawena.ccs.reseau.TravailDistant
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

// Calcul réparti dans l'onglet Réseau (`calcul.js` du web) : bloc « calcul » d'une fiche, travaux,
// lancer une commande, ajout d'un PC par Ricochet et secours Ricochet. Méthodes `machines.*`,
// toujours traitées par le serveur CCS (même quand on pilote une autre machine).

private val Chaud = Color(0xFFE01B24)

/** Titre d'une section de l'onglet Réseau (icône, texte). */
@Composable
fun TitreSection(icone: androidx.compose.ui.graphics.vector.ImageVector, titre: String, modifier: Modifier = Modifier) {
    Row(verticalAlignment = Alignment.CenterVertically, modifier = modifier) {
        Icon(icone, null)
        Spacer(Modifier.width(8.dp))
        Text(titre, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
    }
}

@Composable
private fun Barre(libelle: String, ratio: Double, valeur: String) {
    val r = ratio.coerceIn(0.0, 1.0).toFloat()
    Row(verticalAlignment = Alignment.CenterVertically) {
        Text(libelle, fontSize = 12.sp, modifier = Modifier.width(70.dp))
        LinearProgressIndicator(
            { r }, Modifier.weight(1f),
            color = if (r >= .9f) Chaud else MaterialTheme.colorScheme.primary,
        )
        Spacer(Modifier.width(8.dp))
        Text(valeur, fontSize = 12.sp, fontFamily = FontFamily.Monospace)
    }
}

/**
 * Bloc « calcul » d'une fiche du réseau : charge, mémoire, outils, places et limite de travaux,
 * et le choix de la machine pilotée (ce qui était la feuille « Machine pilotée »).
 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun BlocCalcul(m: Machine, pilotee: Boolean, piloter: (() -> Unit)?, changerLimite: (Int) -> Unit) {
    Surface(shape = RoundedCornerShape(12.dp), color = MaterialTheme.colorScheme.surfaceContainerHighest) {
        Column(Modifier.fillMaxWidth().padding(10.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(Icons.Filled.Memory, null, Modifier.size(16.dp))
                Spacer(Modifier.width(6.dp))
                Text("Calcul", fontWeight = FontWeight.SemiBold, modifier = Modifier.weight(1f))
                when {
                    pilotee -> Surface(shape = RoundedCornerShape(50), color = MaterialTheme.colorScheme.tertiaryContainer) {
                        Text("Machine pilotée", fontSize = 12.sp, fontWeight = FontWeight.SemiBold,
                            color = MaterialTheme.colorScheme.onTertiaryContainer,
                            modifier = Modifier.padding(horizontal = 8.dp, vertical = 3.dp))
                    }
                    piloter != null -> TextButton(onClick = piloter) {
                        Icon(Icons.Filled.Computer, null, Modifier.size(16.dp)); Spacer(Modifier.width(4.dp)); Text("Piloter")
                    }
                }
            }
            if (m.online && m.cores > 0) Barre("Charge", Calcul.chargeParCoeur(m), Calcul.texteCharge(m))
            if (m.online && m.memTotale > 0) Barre("Mémoire", m.memUtilisee / m.memTotale, Calcul.texteMemoire(m))
            if (m.tools.isEmpty()) {
                Text("outils pas encore inventoriés", fontSize = 12.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
            } else {
                FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    m.tools.forEach { t ->
                        Surface(shape = RoundedCornerShape(8.dp), color = MaterialTheme.colorScheme.surface) {
                            Text(t, fontSize = 11.sp, modifier = Modifier.padding(horizontal = 6.dp, vertical = 2.dp))
                        }
                    }
                }
            }
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(Calcul.places(m), fontSize = 13.sp, modifier = Modifier.weight(1f))
                Choix(
                    "Limite", Calcul.LIMITES.map { "$it" to "$it" }, "${m.limite}",
                    surChoix = { v -> v.toIntOrNull()?.takeIf { it != m.limite }?.let(changerLimite) },
                    modifier = Modifier.width(110.dp),
                )
            }
            if (Calcul.injoignable(m)) {
                Text("Ni réseau maillé ni tunnel SSH Ricochet sur cette machine.", fontSize = 12.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
    }
}

// ---- travaux ------------------------------------------------------------------------------------

@Composable
fun SectionTravaux(travaux: List<TravailDistant>?, erreur: String?, journal: (TravailDistant) -> Unit, arreter: (TravailDistant) -> Unit) {
    Card(Modifier.fillMaxWidth(), shape = RoundedCornerShape(16.dp)) {
        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            TitreSection(Icons.Filled.Memory, "Travaux")
            when {
                erreur != null && travaux == null -> Text(erreur, color = MaterialTheme.colorScheme.error, fontSize = 13.sp)
                travaux == null -> Chargement()
                travaux.isEmpty() -> Text("Aucune commande lancée pour l'instant.", color = MaterialTheme.colorScheme.onSurfaceVariant)
                else -> {
                    val (actifs, finis) = travaux.partition(Calcul::actif)
                    Text("En cours et à venir (${actifs.size})", fontWeight = FontWeight.SemiBold)
                    if (actifs.isEmpty()) Text("Rien en cours.", fontSize = 13.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    actifs.forEach { LigneTravail(it, journal, arreter) }
                    if (finis.isNotEmpty()) {
                        Text("Finis (${finis.size})", fontWeight = FontWeight.SemiBold)
                        finis.forEach { LigneTravail(it, journal, arreter) }
                    }
                }
            }
        }
    }
}

@Composable
private fun LigneTravail(t: TravailDistant, journal: (TravailDistant) -> Unit, arreter: (TravailDistant) -> Unit) {
    val actif = Calcul.actif(t)
    val couleur = when {
        Calcul.enEchec(t) -> MaterialTheme.colorScheme.error
        actif -> MaterialTheme.colorScheme.primary
        else -> MaterialTheme.colorScheme.onSurfaceVariant
    }
    Surface(shape = RoundedCornerShape(12.dp), color = MaterialTheme.colorScheme.surfaceContainerHighest) {
        Column(Modifier.fillMaxWidth().padding(10.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(t.text, fontFamily = FontFamily.Monospace, fontSize = 13.sp, maxLines = 2, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f))
                Spacer(Modifier.width(6.dp))
                Surface(shape = RoundedCornerShape(50), color = couleur.copy(alpha = .15f)) {
                    Text(Calcul.etat(t), color = couleur, fontSize = 12.sp, fontWeight = FontWeight.SemiBold,
                        modifier = Modifier.padding(horizontal = 8.dp, vertical = 2.dp))
                }
            }
            Text(Calcul.ligne(t), fontSize = 12.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
            if (t.why.isNotEmpty()) Text(t.why, fontSize = 12.sp)
            Row {
                TextButton(onClick = { journal(t) }) { Text("Journal") }
                if (actif) TextButton(onClick = { arreter(t) }) { Text("Arrêter", color = MaterialTheme.colorScheme.error) }
            }
        }
    }
}

/** Confirmation avant `machines.stop`. */
@Composable
fun ConfirmerArret(t: TravailDistant, annuler: () -> Unit, confirmer: () -> Unit) {
    val enCours = t.state == "running" || t.state == "sending"
    AlertDialog(
        onDismissRequest = annuler,
        title = { Text("Arrêter ce travail ?") },
        text = { Text(if (enCours) "« ${t.text} » sera arrêtée sur ${t.machine ?: "la machine"}." else "« ${t.text} » ne sera pas lancée.") },
        confirmButton = { TextButton(onClick = confirmer) { Text("Arrêter", color = MaterialTheme.colorScheme.error) } },
        dismissButton = { TextButton(onClick = annuler) { Text("Garder") } },
    )
}

/** Journal d'un travail (`machines.log`), relu toutes les 3 s tant que la feuille est ouverte. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun FeuilleJournal(client: CcsClient, t: TravailDistant, frais: TravailDistant?, fermer: () -> Unit) {
    var texte by remember(t.id) { mutableStateOf("Chargement…") }
    LaunchedEffect(t.id) {
        while (true) {
            texte = runCatching {
                client.appeler("machines.log", JournalTravail.serializer(), buildJsonObject { put("id", t.id); put("tail", 20000) })
            }.fold({ it.text.ifEmpty { "Pas encore de journal." } }, { it.message ?: "Journal illisible." })
            delay(3_000)
        }
    }
    val vu = frais ?: t
    val defile = rememberScrollState()
    LaunchedEffect(texte) { defile.scrollTo(defile.maxValue) }
    ModalBottomSheet(onDismissRequest = fermer, sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)) {
        Column(Modifier.fillMaxWidth().navigationBarsPadding().padding(horizontal = 16.dp, vertical = 8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text(t.text, fontFamily = FontFamily.Monospace, fontWeight = FontWeight.SemiBold)
            Text("${Calcul.etat(vu)} · ${Calcul.ligne(vu)}", fontSize = 12.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
            Surface(shape = RoundedCornerShape(10.dp), color = Color(0xFF1E1E22)) {
                Text(
                    texte, color = Color(0xFFE6E6EA), fontFamily = FontFamily.Monospace, fontSize = 11.sp,
                    modifier = Modifier.fillMaxWidth().heightIn(min = 120.dp, max = 420.dp).verticalScroll(defile).padding(10.dp),
                )
            }
            TextButton(onClick = fermer, modifier = Modifier.align(Alignment.End)) { Text("Fermer") }
        }
    }
}

// ---- lancer une commande ------------------------------------------------------------------------

/**
 * Formulaire « Lancer une commande » (`machines.start`) : commande, dossier (dossier personnel du
 * serveur par défaut), machine (la moins chargée par défaut) et quand. `lancer` rend l'erreur, ou null.
 */
@Composable
fun FormulaireLancer(machines: List<Machine>, maison: String, lancer: suspend (Map<String, String>) -> String?) {
    val portee = rememberCoroutineScope()
    val avis = LocalAvis.current
    var commande by remember { mutableStateOf("") }
    var dossier by remember(maison) { mutableStateOf(maison) }
    var cible by remember { mutableStateOf("") }
    var quand by remember { mutableStateOf("") }
    var heure by remember { mutableStateOf("") }
    var erreur by remember { mutableStateOf<String?>(null) }
    var envoi by remember { mutableStateOf(false) }
    val cibles = listOf("" to "La moins chargée") +
        machines.filter { it.online }.map { it.id to it.nom }
    // machine choisie disparue ou hors ligne : retour à « la moins chargée »
    val cibleVue = if (cibles.any { it.first == cible }) cible else ""
    val sansMajuscule = KeyboardOptions(capitalization = KeyboardCapitalization.None, autoCorrectEnabled = false)
    Card(Modifier.fillMaxWidth(), shape = RoundedCornerShape(16.dp)) {
        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            TitreSection(Icons.Filled.PlayArrow, "Lancer une commande")
            OutlinedTextField(commande, { commande = it }, singleLine = true, label = { Text("Commande") },
                placeholder = { Text("flutter build apk") }, supportingText = { Text("Une ligne de shell, lancée dans le dossier.") },
                textStyle = MaterialTheme.typography.bodyMedium.copy(fontFamily = FontFamily.Monospace),
                keyboardOptions = sansMajuscule, modifier = Modifier.fillMaxWidth())
            OutlinedTextField(dossier, { dossier = it }, singleLine = true, label = { Text("Dossier") },
                placeholder = { Text("~/Work/mon-projet") }, keyboardOptions = sansMajuscule, modifier = Modifier.fillMaxWidth())
            Choix("Machine", cibles, cibleVue, surChoix = { cible = it }, modifier = Modifier.fillMaxWidth())
            Choix("Quand", listOf("" to "Maintenant", "nuit" to "Cette nuit", "heure" to "À une heure…"), quand,
                surChoix = { quand = it }, modifier = Modifier.fillMaxWidth())
            if (quand == "heure") OutlinedTextField(heure, { heure = it.trim() }, singleLine = true, label = { Text("Heure (HH:MM)") },
                placeholder = { Text("22:30") }, isError = heure.isNotEmpty() && !Calcul.heureValide(heure), modifier = Modifier.fillMaxWidth())
            erreur?.let { Text(it, color = MaterialTheme.colorScheme.error, fontSize = 13.sp) }
            FilledTonalButton(enabled = !envoi, onClick = {
                erreur = null
                val texte = commande.trim()
                val cwd = Calcul.dossier(dossier, maison)
                erreur = when {
                    texte.isEmpty() -> "Écris la commande à lancer."
                    cwd.isEmpty() -> "Indique le dossier."
                    quand == "heure" && !Calcul.heureValide(heure) -> "Choisis l'heure (HH:MM)."
                    else -> null
                }
                if (erreur != null) return@FilledTonalButton
                val params = buildMap<String, String> {
                    put("command", texte); put("cwd", cwd)
                    put("when", if (quand == "heure") heure else quand)
                    if (cibleVue.isNotEmpty()) put("machine", cibleVue)
                }
                envoi = true
                portee.launch {
                    val e = lancer(params)
                    envoi = false
                    if (e != null) erreur = e
                    else {
                        commande = ""
                        avis.dire(if (params["when"].isNullOrEmpty()) "Commande lancée." else "Commande programmée.")
                    }
                }
            }) { Icon(Icons.Filled.PlayArrow, null, Modifier.size(16.dp)); Spacer(Modifier.width(6.dp)); Text("Lancer") }
        }
    }
}

// ---- ajouter un PC par Ricochet -----------------------------------------------------------------

/**
 * Onglet « PC Linux » de l'ajout d'appareil quand le relais, son jeton et le jeton opérateur sont
 * réglés (`machines.add`) : un lien à usage unique installe SSH et l'agent Ricochet (secours) et
 * inscrit aussi au réseau maillé.
 */
@Composable
fun AjoutPcRicochet(ajouter: suspend (id: String, compte: String, nom: String, complet: Boolean) -> PcAjoute?) {
    val presse = LocalClipboardManager.current
    val avis = LocalAvis.current
    val portee = rememberCoroutineScope()
    var id by remember { mutableStateOf("") }
    var compte by remember { mutableStateOf("") }
    var nom by remember { mutableStateOf("") }
    var complet by remember { mutableStateOf(false) }
    var resultat by remember { mutableStateOf<PcAjoute?>(null) }
    val sansMajuscule = KeyboardOptions(capitalization = KeyboardCapitalization.None, autoCorrectEnabled = false)
    Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        OutlinedTextField(id, { id = it.trim() }, singleLine = true, label = { Text("Identifiant") },
            placeholder = { Text("pc-salon") }, supportingText = { Text("lettres, chiffres, - et _") },
            isError = id.isNotEmpty() && !Calcul.idPcValide(id), keyboardOptions = sansMajuscule, modifier = Modifier.fillMaxWidth())
        OutlinedTextField(compte, { compte = it.trim() }, singleLine = true, label = { Text("Ton compte sur ce PC") },
            placeholder = { Text("charles") }, supportingText = { Text("terminal, fichiers et travaux tournent sous ce compte") },
            isError = compte.isNotEmpty() && !Calcul.compteValide(compte), keyboardOptions = sansMajuscule, modifier = Modifier.fillMaxWidth())
        OutlinedTextField(nom, { nom = it.take(100) }, singleLine = true, label = { Text("Nom affiché (facultatif)") },
            placeholder = { Text("PC du salon") }, modifier = Modifier.fillMaxWidth())
        Row(Modifier.clickable { complet = !complet }, verticalAlignment = Alignment.CenterVertically) {
            Checkbox(complet, { complet = it })
            Column {
                Text("Installer aussi CCS et Claude Code")
                Text("pour ouvrir des sessions entières sur ce PC", fontSize = 12.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
        FilledTonalButton(enabled = Calcul.idPcValide(id) && Calcul.compteValide(compte), onClick = {
            portee.launch {
                ajouter(id, compte, nom.trim(), complet)?.let { resultat = it; id = ""; nom = "" }
            }
        }) { Icon(Icons.Filled.CheckCircle, null, Modifier.size(16.dp)); Spacer(Modifier.width(6.dp)); Text("Créer le lien") }
        resultat?.let { r ->
            Text("Colle cette commande dans un terminal de « ${r.id} » (Ubuntu ou Debian). Le lien ne sert qu'une fois, pendant ${r.expireS / 60} min.", fontSize = 13.sp)
            Surface(shape = RoundedCornerShape(10.dp), color = Color(0xFF1E1E22)) {
                Row(Modifier.padding(10.dp), verticalAlignment = Alignment.Top) {
                    Text(r.command, color = Color(0xFFE6E6EA), fontFamily = FontFamily.Monospace, fontSize = 11.sp, modifier = Modifier.weight(1f))
                    IconButton(onClick = { presse.setText(AnnotatedString(r.command)); avis.dire("Copié.") }) {
                        Icon(Icons.Filled.ContentCopy, "Copier", tint = Color(0xFFE6E6EA))
                    }
                }
            }
            Text(
                "Elle installe le serveur SSH et l'agent Ricochet (secours), autorise la clé de ce serveur" +
                    (if (r.mesh) " et inscrit la machine au réseau maillé" else "") +
                    (if (r.full) ", puis installe CCS et Claude Code" else "") +
                    " ; elle apparaît ensuite ici, avec sa charge et ses outils.",
                fontSize = 12.sp, color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

// ---- secours Ricochet ---------------------------------------------------------------------------

/**
 * « Secours Ricochet », replié en bas de l'onglet : adresse et jeton du relais (`machines.configure`).
 * `enregistrer` reçoit l'adresse (null si inchangée) et le jeton (null si vide) ; rend true si c'est fait.
 */
@Composable
fun SecoursRicochet(
    reglages: ReglagesRicochet?, erreur: String?, message: String?, configure: Boolean,
    enregistrer: suspend (relais: String?, jeton: String?) -> Boolean,
) {
    val portee = rememberCoroutineScope()
    val avis = LocalAvis.current
    var ouvert by remember { mutableStateOf(false) }
    Card(Modifier.fillMaxWidth(), shape = RoundedCornerShape(16.dp)) {
        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Row(Modifier.fillMaxWidth().clickable { ouvert = !ouvert }, verticalAlignment = Alignment.CenterVertically) {
                TitreSection(Icons.Filled.Support, "Secours Ricochet", Modifier.weight(1f))
                Icon(if (ouvert) Icons.Filled.ExpandLess else Icons.Filled.ExpandMore, if (ouvert) "Replier" else "Déplier")
            }
            if (!ouvert) return@Column
            if (reglages == null) {
                if (erreur != null) Text(erreur, color = MaterialTheme.colorScheme.error, fontSize = 13.sp) else Chargement()
                return@Column
            }
            message?.let {
                Text(it, fontSize = 13.sp, color = if (configure) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSurfaceVariant)
            }
            var adresse by remember(reglages.relay) { mutableStateOf(reglages.relay) }
            var jeton by remember { mutableStateOf("") }
            var faute by remember { mutableStateOf<String?>(null) }
            Text("Le réseau maillé passe d'abord ; Ricochet prend le relais quand il ne joint pas une machine.",
                fontSize = 13.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
            OutlinedTextField(adresse, { adresse = it.trim() }, singleLine = true, label = { Text("Adresse du relais") },
                placeholder = { Text("https://ricochet.exemple") },
                keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.None, autoCorrectEnabled = false),
                modifier = Modifier.fillMaxWidth())
            OutlinedTextField(jeton, { jeton = it }, singleLine = true, label = { Text("Jeton") },
                placeholder = { Text(if (reglages.jetonDefini) "laisser vide pour le garder" else "jeton du relais") },
                supportingText = { Text(if (reglages.jetonDefini) "Jeton enregistré." else "Aucun jeton.") },
                visualTransformation = PasswordVisualTransformation(), modifier = Modifier.fillMaxWidth())
            faute?.let { Text(it, color = MaterialTheme.colorScheme.error, fontSize = 13.sp) }
            Text("Fichier : ${com.mawena.ccs.logique.TachesFond.cheminCourt(reglages.path)} · limite par défaut : ${reglages.limiteParDefaut} travaux à la fois par machine.",
                fontSize = 12.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
            FilledTonalButton(onClick = {
                faute = null
                val relais = adresse.takeIf { it != reglages.relay }
                val j = jeton.ifEmpty { null }
                if (relais == null && j == null) { avis.dire("Rien à changer."); return@FilledTonalButton }
                portee.launch {
                    if (enregistrer(relais, j)) { jeton = ""; avis.dire("Enregistré.") } else faute = "Enregistrement impossible."
                }
            }) { Text("Enregistrer") }
        }
    }
}
