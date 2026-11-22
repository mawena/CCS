package com.mawena.ccs.ui.jarvis

import android.Manifest
import android.content.ClipboardManager
import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.gestures.waitForUpOrCancellation
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ContentPaste
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.GraphicEq
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.scale
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.onClick
import androidx.compose.ui.semantics.role
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LifecycleEventEffect
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.mawena.ccs.jarvis.OreilleJarvis
import com.mawena.ccs.logique.CibleAppairage
import com.mawena.ccs.logique.ErreurJarvis
import com.mawena.ccs.logique.Jarvis
import com.mawena.ccs.ui.Accent
import com.mawena.ccs.ui.BarreHaut
import com.mawena.ccs.ui.Confirmation
import com.mawena.ccs.ui.LocalAvis
import com.mawena.ccs.ui.ModeleAppli
import com.mawena.ccs.ui.TitreSection
import com.mawena.ccs.ui.texte
import kotlinx.coroutines.launch

private const val APPUI_LONG_MS = 400L

/**
 * Plus → Parler à Jarvis : l'assistant vocal de la maison, joint par le relais de CCS (comme la page
 * Jarvis de la version web). Appairage une fois (adresse `jarvis://pair?…` de « jarvis pair »,
 * collée ou scannée par l'appareil photo, ou code + empreinte), puis un bouton : maintenir pour
 * parler (fin au relâché), ou toucher une fois (fin au silence).
 */
@Composable
fun EcranJarvis(modele: ModeleAppli, retour: () -> Unit) {
    val oreille = modele.depot.jarvis
    val appairage by oreille.appairage.collectAsStateWithLifecycle()
    var oublier by remember { mutableStateOf(false) }
    DisposableEffect(oreille) { onDispose { oreille.fermer() } }
    LifecycleEventEffect(Lifecycle.Event.ON_STOP) { oreille.fermer() }
    Column(Modifier.fillMaxSize()) {
        BarreHaut(
            appairage?.brainName ?: "Jarvis", sousTitre = if (appairage == null) "Appairage" else "Parler à Jarvis", retour = retour,
            actions = {
                if (appairage != null) IconButton(onClick = { oublier = true }) { Icon(Icons.Filled.Delete, "Oublier l'appairage") }
            },
        )
        if (appairage == null) FormulaireAppairage(oreille) else Parler(oreille)
    }
    if (oublier) {
        Confirmation(
            "Oublier l'appairage ?",
            "Ce téléphone ne pourra plus parler à Jarvis sans un nouvel appairage. Pour le retirer aussi côté Jarvis : « jarvis unpair <nom> ».",
            "Oublier", danger = true,
            surOui = { oublier = false; oreille.oublier() }, surNon = { oublier = false },
        )
    }
}

@Composable
private fun Parler(oreille: OreilleJarvis) {
    val ctx = LocalContext.current
    val avis = LocalAvis.current
    val etat by oreille.etat.collectAsStateWithLifecycle()
    val ecoute by oreille.ecoute.collectAsStateWithLifecycle()
    val journal by oreille.journal.collectAsStateWithLifecycle()
    val demande by oreille.demandeEcoute.collectAsStateWithLifecycle()
    val autorise = { ContextCompat.checkSelfPermission(ctx, Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED }
    val permission = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { ok ->
        if (ok) oreille.commencer(auto = true)
        else avis.dire("Micro refusé : autorise-le pour CCS dans les réglages d'Android.", long = true)
    }
    // raccourci « Parler à Jarvis » : écoute tout de suite (fin au silence)
    LaunchedEffect(demande) {
        if (!demande) return@LaunchedEffect
        oreille.demandeEcoute.value = false
        if (oreille.ecoute.value) return@LaunchedEffect
        if (autorise()) oreille.commencer(auto = true) else permission.launch(Manifest.permission.RECORD_AUDIO)
    }
    // appui : commence (ou arrête si on écoutait) ; rend l'heure de début si une écoute a commencé
    val appui by rememberUpdatedState {
        when {
            oreille.ecoute.value -> { oreille.finir(); null }
            !autorise() -> { permission.launch(Manifest.permission.RECORD_AUDIO); null }
            else -> { oreille.commencer(auto = false); System.currentTimeMillis() }
        }
    }
    val echelle by animateFloatAsState(if (ecoute) 1.06f else 1f, label = "bouton")
    val couleur = if (ecoute) MaterialTheme.colorScheme.error else Accent
    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(16.dp)) {
        item {
            Column(Modifier.fillMaxWidth().padding(vertical = 16.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                Box(
                    Modifier
                        .size(140.dp)
                        .scale(echelle)
                        .clip(CircleShape)
                        .background(couleur)
                        .semantics {
                            role = Role.Button
                            contentDescription = if (ecoute) "Arrêter l'écoute" else "Parler à Jarvis"
                            onClick {
                                if (oreille.ecoute.value) oreille.finir()
                                else if (autorise()) oreille.commencer(auto = true)
                                else permission.launch(Manifest.permission.RECORD_AUDIO)
                                true
                            }
                        }
                        // appui long : on parle tant que le doigt est posé ; appui court : fin au silence ; second appui : fin
                        .pointerInput(Unit) {
                            awaitEachGesture {
                                awaitFirstDown(requireUnconsumed = false)
                                val debut = appui()
                                waitForUpOrCancellation()
                                if (debut != null && oreille.ecoute.value) {
                                    if (System.currentTimeMillis() - debut >= APPUI_LONG_MS) oreille.finir() else oreille.passerEnAuto()
                                }
                            }
                        },
                    contentAlignment = Alignment.Center,
                ) {
                    Column(horizontalAlignment = Alignment.CenterHorizontally) {
                        Icon(if (ecoute) Icons.Filled.GraphicEq else Icons.Filled.Mic, null, Modifier.size(44.dp), tint = Color.White)
                        Text("Parler à Jarvis", color = Color.White, style = MaterialTheme.typography.labelMedium, fontWeight = FontWeight.SemiBold)
                    }
                }
                Spacer(Modifier.height(14.dp))
                Text(
                    etat.ifEmpty { if (ecoute) "Écoute…" else "Prêt." },
                    style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant,
                    textAlign = TextAlign.Center,
                )
                Spacer(Modifier.height(8.dp))
                Text(
                    "Maintiens le bouton pendant que tu parles, ou touche-le une fois : l'écoute s'arrête quand tu te tais.",
                    style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
                    textAlign = TextAlign.Center,
                )
            }
        }
        if (journal.isNotEmpty()) item { TitreSection("Conversation") }
        items(journal, key = { it.id }) { l ->
            when (l.genre) {
                OreilleJarvis.Genre.Erreur -> Row(Modifier.padding(vertical = 6.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Icon(Icons.Filled.Warning, null, tint = MaterialTheme.colorScheme.error, modifier = Modifier.size(18.dp))
                    Text(l.texte, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodyMedium)
                }
                else -> Column(Modifier.padding(vertical = 6.dp)) {
                    Text(
                        l.qui, style = MaterialTheme.typography.labelMedium, fontWeight = FontWeight.SemiBold,
                        color = if (l.genre == OreilleJarvis.Genre.Moi) MaterialTheme.colorScheme.onSurfaceVariant else Accent,
                    )
                    SelectionContainer { Text(l.texte, style = MaterialTheme.typography.bodyLarge) }
                }
            }
        }
    }
}

@Composable
private fun FormulaireAppairage(oreille: OreilleJarvis) {
    val ctx = LocalContext.current
    val portee = rememberCoroutineScope()
    val recue by oreille.adresseRecue.collectAsStateWithLifecycle()
    var adresse by remember { mutableStateOf("") }
    var code by remember { mutableStateOf("") }
    var empreinte by remember { mutableStateOf("") }
    var nom by remember { mutableStateOf("CCS Android (${Build.MODEL})".take(60)) }
    var aLaMain by remember { mutableStateOf(false) }
    var erreur by remember { mutableStateOf<String?>(null) }
    var enCours by remember { mutableStateOf(false) }
    LaunchedEffect(recue) {
        recue?.let { adresse = Jarvis.nettoyer(it); oreille.adresseRecue.value = null }
    }
    LaunchedEffect(Unit) { oreille.demandeEcoute.value = false }      // rien à écouter avant l'appairage

    fun appairer() {
        erreur = null
        val cible = try {
            if (adresse.isNotBlank()) {
                Jarvis.lireAdresse(adresse)
            } else {
                if (!Jarvis.codeValide(code.trim())) throw ErreurJarvis("Code d'appairage : 6 chiffres.")
                if (!Jarvis.empreinteValide(empreinte.trim())) throw ErreurJarvis("Empreinte invalide : 43 caractères (lettres, chiffres, - et _).")
                CibleAppairage(code.trim(), empreinte.trim())
            }
        } catch (e: ErreurJarvis) {
            erreur = e.texte()
            return
        }
        enCours = true
        portee.launch {
            try {
                oreille.appairer(cible, nom.trim().ifEmpty { "CCS Android" })
            } catch (e: Exception) {
                erreur = e.texte()
            } finally {
                enCours = false
            }
        }
    }

    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Text("Appairer ce téléphone", style = MaterialTheme.typography.titleMedium)
        Text(
            "Sur la machine de Jarvis, lance « jarvis pair » : scanne le QR code avec l'appareil photo (il ouvre CCS), " +
                "ou colle ici l'adresse affichée dessous (valable quelques minutes).",
            style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        OutlinedTextField(
            adresse, { adresse = it }, Modifier.fillMaxWidth(), label = { Text("Adresse d'appairage") },
            placeholder = { Text("jarvis://pair?v=1&…") }, singleLine = true,
            textStyle = MaterialTheme.typography.bodyMedium.copy(fontFamily = FontFamily.Monospace),
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri, autoCorrectEnabled = false),
            trailingIcon = {
                IconButton(onClick = {
                    val presse = ctx.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
                    presse.primaryClip?.takeIf { it.itemCount > 0 }?.getItemAt(0)?.coerceToText(ctx)?.let { adresse = Jarvis.nettoyer(it.toString()) }
                }) { Icon(Icons.Filled.ContentPaste, "Coller") }
            },
        )
        TextButton(onClick = { aLaMain = !aLaMain }) { Text(if (aLaMain) "Masquer la saisie à la main" else "Saisir le code et l'empreinte à la main") }
        if (aLaMain) {
            OutlinedTextField(
                code, { code = it.filter(Char::isDigit).take(6) }, Modifier.fillMaxWidth(), label = { Text("Code à 6 chiffres") },
                singleLine = true, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.NumberPassword),
            )
            OutlinedTextField(
                empreinte, { empreinte = it.trim().take(43) }, Modifier.fillMaxWidth(), label = { Text("Empreinte du cerveau") },
                supportingText = { Text("43 caractères, dans l'adresse après « fp= »") }, singleLine = true,
                textStyle = MaterialTheme.typography.bodySmall.copy(fontFamily = FontFamily.Monospace),
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Ascii, autoCorrectEnabled = false),
            )
        }
        OutlinedTextField(
            nom, { nom = it.take(60) }, Modifier.fillMaxWidth(), label = { Text("Nom de cet appareil") },
            supportingText = { Text("Affiché par « jarvis ears ».") }, singleLine = true,
        )
        erreur?.let { Text(it, color = MaterialTheme.colorScheme.error) }
        Button(onClick = ::appairer, enabled = !enCours) {
            if (enCours) {
                CircularProgressIndicator(Modifier.size(16.dp), strokeWidth = 2.dp, color = MaterialTheme.colorScheme.onPrimary)
                Spacer(Modifier.size(8.dp))
                Text("Appairage…")
            } else {
                Text("Appairer")
            }
        }
    }
}
