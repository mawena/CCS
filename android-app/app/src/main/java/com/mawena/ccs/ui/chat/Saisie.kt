package com.mawena.ccs.ui.chat

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.net.Uri
import android.provider.OpenableColumns
import android.util.Base64
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Image
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Reply
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material.icons.filled.AttachFile
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Stop
import androidx.compose.material.icons.filled.Tune
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilledIconButton
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Surface
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
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.TextRange
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.text.input.TextFieldValue
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.foundation.text.KeyboardOptions
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.mawena.ccs.logique.Citation
import com.mawena.ccs.logique.Envoi
import com.mawena.ccs.reseau.OptionsChat
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.ByteArrayOutputStream

val DROITS = listOf("manual" to "Demander", "acceptEdits" to "Modifications acceptées", "plan" to "Plan", "bypassPermissions" to "Tout autoriser")
val EFFORTS = listOf("" to "Par défaut", "low" to "Faible", "medium" to "Moyen", "high" to "Élevé", "xhigh" to "Très élevé", "max" to "Max")

fun resumeOptions(r: ReglagesChat): String {
    val o = r.options
    val modele = o.model?.let { m -> r.modeles.firstOrNull { it.valeur == m }?.libelle ?: m }
    val effort = o.effort?.takeIf { it.isNotEmpty() }?.let { e -> EFFORTS.firstOrNull { it.first == e }?.second ?: e }
    val droits = DROITS.firstOrNull { it.first == o.rights }?.second ?: o.rights
    return listOfNotNull(modele, effort, droits).joinToString(" · ")
}

/** État de Claude au-dessus de la saisie (au travail, démarrage, réflexion, attente). */
@Composable
fun BandeauEtat(vue: VueChat) {
    val texte = when {
        vue.etat == "permission" -> "Attend ta réponse"
        vue.etat == "starting" && vue.pret -> "Démarrage…"
        vue.etat == "busy" -> if (vue.reflechit) "Claude réfléchit…" else "Claude travaille…"
        vue.etat == "suspended" -> "En veille"
        else -> return
    }
    Row(Modifier.fillMaxWidth().padding(horizontal = 14.dp, vertical = 4.dp), verticalAlignment = Alignment.CenterVertically) {
        if (vue.etat != "suspended" && vue.etat != "permission") CircularProgressIndicator(Modifier.size(14.dp), strokeWidth = 2.dp)
        Text(texte, Modifier.padding(start = 8.dp), style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.primary)
    }
}

/** Zone de saisie : citation, images, commandes `/`, texte multi-ligne, envoi ; pied : options, contexte, coût, Arrêter. */
@Composable
fun Saisie(modele: ModeleChat, vue: VueChat) {
    val saisie by modele.saisie.collectAsStateWithLifecycle()
    val citation by modele.citation.collectAsStateWithLifecycle()
    val images by modele.images.collectAsStateWithLifecycle()
    val commandes by modele.commandes.collectAsStateWithLifecycle()
    val envoi by modele.envoiEnCours.collectAsStateWithLifecycle()
    val reglages by modele.reglages.collectAsStateWithLifecycle()
    var champ by remember { mutableStateOf(TextFieldValue(saisie, TextRange(saisie.length))) }
    LaunchedEffect(saisie) { if (saisie != champ.text) champ = TextFieldValue(saisie, TextRange(saisie.length)) }
    var options by remember { mutableStateOf(false) }
    val ctx = LocalContext.current
    val portee = rememberCoroutineScope()
    val choisir = rememberLauncherForActivityResult(ActivityResultContracts.PickMultipleVisualMedia(ModeleChat.MAX_IMAGES)) { uris ->
        portee.launch {
            for (u in uris.take(ModeleChat.MAX_IMAGES - modele.images.value.size)) {
                val p = lireImage(ctx, u)
                if (p == null) modele.dire("Image illisible ou trop lourde (5 Mo au plus).") else modele.joindre(p)
            }
        }
    }
    val travaille = vue.etat in setOf("busy", "permission", "starting") && vue.pret
    val proposees = remember(champ.text, commandes) { Envoi.completer(champ.text, commandes) }

    Surface(color = MaterialTheme.colorScheme.surfaceContainerLow, tonalElevation = 2.dp) {
        Column(Modifier.fillMaxWidth().navigationBarsPadding()) {
            if (proposees.isNotEmpty()) {
                Column(Modifier.heightIn(max = 220.dp).verticalScroll(rememberScrollState())) {
                    proposees.forEach { c ->
                        Row(
                            Modifier.fillMaxWidth().clickable { modele.saisir("/${c.nom} ") }.padding(horizontal = 14.dp, vertical = 6.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Text("/${c.nom}", fontFamily = FontFamily.Monospace, style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.SemiBold)
                            Text(
                                (if (c.indice.isNotEmpty()) " ${c.indice} " else " ") + c.description, Modifier.weight(1f).padding(start = 6.dp),
                                maxLines = 1, overflow = TextOverflow.Ellipsis, style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                    }
                }
                HorizontalDivider()
            }
            citation?.let { c ->
                Row(Modifier.fillMaxWidth().padding(start = 12.dp, top = 6.dp), verticalAlignment = Alignment.CenterVertically) {
                    Icon(Icons.AutoMirrored.Filled.Reply, null, Modifier.size(16.dp), tint = MaterialTheme.colorScheme.primary)
                    Column(Modifier.weight(1f).padding(start = 6.dp)) {
                        Text(if (c.auteur == Citation.Auteur.Claude) "Réponse à Claude" else "Réponse à ton message",
                            style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.primary)
                        Text(Citation.uneLigne(c.texte, 200), maxLines = 2, overflow = TextOverflow.Ellipsis, style = MaterialTheme.typography.bodySmall)
                    }
                    IconButton(onClick = { modele.citer(null) }) { Icon(Icons.Filled.Close, "Annuler la citation") }
                }
            }
            if (images.isNotEmpty()) {
                Row(Modifier.horizontalScroll(rememberScrollState()).padding(horizontal = 12.dp, vertical = 4.dp), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    images.forEach { p ->
                        Box {
                            p.apercu?.let {
                                Image(it.asImageBitmap(), p.nom, Modifier.size(64.dp).clip(RoundedCornerShape(8.dp)), contentScale = ContentScale.Crop)
                            } ?: Surface(Modifier.size(64.dp), shape = RoundedCornerShape(8.dp)) { Text(p.nom, maxLines = 3) }
                            Surface(
                                shape = RoundedCornerShape(50), color = MaterialTheme.colorScheme.surface.copy(alpha = 0.8f),
                                modifier = Modifier.align(Alignment.TopEnd).size(22.dp).clickable { modele.retirerImage(p) },
                            ) { Icon(Icons.Filled.Close, "Retirer l'image", Modifier.padding(3.dp)) }
                        }
                    }
                }
            }
            Row(Modifier.fillMaxWidth().padding(start = 4.dp, end = 8.dp, top = 4.dp), verticalAlignment = Alignment.Bottom) {
                IconButton(onClick = { choisir.launch(PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly)) }, enabled = images.size < ModeleChat.MAX_IMAGES) {
                    Icon(Icons.Filled.AttachFile, "Joindre une image")
                }
                OutlinedTextField(
                    champ,
                    { champ = it; modele.saisir(it.text) },
                    Modifier.weight(1f).heightIn(min = 48.dp, max = 200.dp),
                    placeholder = { Text("Écris à Claude…") },
                    maxLines = 8,
                    shape = RoundedCornerShape(20.dp),
                    keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.Sentences),
                )
                FilledIconButton(
                    onClick = { modele.envoyer() },
                    enabled = !envoi && (champ.text.isNotBlank() || images.isNotEmpty()),
                    modifier = Modifier.padding(start = 6.dp, bottom = 4.dp),
                ) {
                    if (envoi) CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp)
                    else Icon(Icons.AutoMirrored.Filled.Send, "Envoyer")
                }
            }
            Row(Modifier.fillMaxWidth().padding(horizontal = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                TextButton(onClick = { options = true }, enabled = reglages.pretes) {
                    Icon(Icons.Filled.Tune, null, Modifier.size(16.dp))
                    Text(" " + resumeOptions(reglages), maxLines = 1, overflow = TextOverflow.Ellipsis, style = MaterialTheme.typography.labelMedium)
                }
                Text(
                    listOf(vue.contexte, vue.cout).filter(String::isNotEmpty).joinToString(" · "),
                    Modifier.weight(1f), maxLines = 1, overflow = TextOverflow.Ellipsis,
                    style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                if (travaille) {
                    OutlinedButton(onClick = { modele.interrompre() }) {
                        Icon(Icons.Filled.Stop, null, Modifier.size(16.dp), tint = MaterialTheme.colorScheme.error)
                        Text(" Arrêter", color = MaterialTheme.colorScheme.error)
                    }
                }
            }
        }
    }
    if (options) FeuilleOptions(reglages, fermer = { options = false }) { modele.changerOptions(it) }
}

/** Options du chat : modèle, effort, droits (« Tout autoriser » demande confirmation). */
@OptIn(ExperimentalMaterial3Api::class, androidx.compose.foundation.layout.ExperimentalLayoutApi::class)
@Composable
fun FeuilleOptions(r: ReglagesChat, fermer: () -> Unit, changer: (OptionsChat) -> Unit) {
    var confirmer by remember { mutableStateOf(false) }
    val o = r.options
    ModalBottomSheet(onDismissRequest = fermer) {
        Column(Modifier.fillMaxWidth().verticalScroll(rememberScrollState()).padding(horizontal = 20.dp).padding(bottom = 24.dp)) {
            Text("Modèle", style = MaterialTheme.typography.titleSmall, color = MaterialTheme.colorScheme.primary)
            val modeles = listOf("" to "Modèle par défaut") + r.modeles.map { it.valeur to it.libelle } +
                (o.model?.takeIf { m -> m.isNotEmpty() && r.modeles.none { it.valeur == m } }?.let { listOf(it to it) } ?: emptyList())
            modeles.forEach { (v, t) ->
                val pris = (o.model ?: "") == v
                Row(Modifier.fillMaxWidth().clickable { changer(o.copy(model = v.ifEmpty { null })) }, verticalAlignment = Alignment.CenterVertically) {
                    RadioButton(pris, { changer(o.copy(model = v.ifEmpty { null })) })
                    Text(t)
                }
            }
            if (r.modeles.isEmpty()) Text("La liste des modèles arrive quand Claude a démarré.", style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant)
            Text("Effort", Modifier.padding(top = 12.dp), style = MaterialTheme.typography.titleSmall, color = MaterialTheme.colorScheme.primary)
            androidx.compose.foundation.layout.FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                EFFORTS.forEach { (v, t) ->
                    FilterChip((o.effort ?: "") == v, { changer(o.copy(effort = v.ifEmpty { null })) }, { Text(t) })
                }
            }
            Text("Droits", Modifier.padding(top = 12.dp), style = MaterialTheme.typography.titleSmall, color = MaterialTheme.colorScheme.primary)
            DROITS.forEach { (v, t) ->
                val faire = { if (v == "bypassPermissions" && o.rights != v) confirmer = true else changer(o.copy(rights = v)) }
                Row(Modifier.fillMaxWidth().clickable(onClick = faire), verticalAlignment = Alignment.CenterVertically) {
                    RadioButton(o.rights == v, faire)
                    Text(t)
                }
            }
        }
    }
    if (confirmer) {
        AlertDialog(
            onDismissRequest = { confirmer = false },
            title = { Text("Tout autoriser ?") },
            text = { Text("Claude pourra lancer des commandes et modifier des fichiers sans te demander.") },
            confirmButton = { TextButton(onClick = { confirmer = false; changer(o.copy(rights = "bypassPermissions")) }) { Text("Tout autoriser") } },
            dismissButton = { TextButton(onClick = { confirmer = false }) { Text("Annuler") } },
        )
    }
}

private const val MAX_OCTETS = 5 * 1024 * 1024
private const val GARDER_TEL_QUEL = 3_500_000
private const val COTE_MAX = 2000

/** Image choisie : lue, réduite si elle est trop lourde (JPEG, 2000 px de côté), avec un aperçu. */
suspend fun lireImage(ctx: Context, uri: Uri): PieceJointe? = withContext(Dispatchers.IO) {
    runCatching {
        val cr = ctx.contentResolver
        val nom = cr.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use { c ->
            if (c.moveToFirst()) c.getString(0) else null
        } ?: "image"
        var type = cr.getType(uri) ?: "image/jpeg"
        var octets = cr.openInputStream(uri)?.use { it.readBytes() } ?: return@runCatching null
        val bornes = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeByteArray(octets, 0, octets.size, bornes)
        val cote = maxOf(bornes.outWidth, bornes.outHeight)
        if (cote <= 0) return@runCatching null
        if (octets.size > GARDER_TEL_QUEL || cote > COTE_MAX * 2 || type !in setOf("image/jpeg", "image/png", "image/gif", "image/webp")) {
            var echantillon = 1
            while (cote / (echantillon * 2) >= COTE_MAX) echantillon *= 2
            val b = BitmapFactory.decodeByteArray(octets, 0, octets.size, BitmapFactory.Options().apply { inSampleSize = echantillon })
                ?: return@runCatching null
            val k = minOf(1f, COTE_MAX.toFloat() / maxOf(b.width, b.height))
            val r = if (k < 1f) Bitmap.createScaledBitmap(b, (b.width * k).toInt(), (b.height * k).toInt(), true) else b
            octets = ByteArrayOutputStream().use { s -> r.compress(Bitmap.CompressFormat.JPEG, 85, s); s.toByteArray() }
            type = "image/jpeg"
        }
        if (octets.size > MAX_OCTETS) return@runCatching null
        var petit = 1
        while (cote / (petit * 2) >= 160) petit *= 2
        val apercu = BitmapFactory.decodeByteArray(octets, 0, octets.size, BitmapFactory.Options().apply { inSampleSize = petit })
        PieceJointe(type, Base64.encodeToString(octets, Base64.NO_WRAP), apercu, nom)
    }.getOrNull()
}
