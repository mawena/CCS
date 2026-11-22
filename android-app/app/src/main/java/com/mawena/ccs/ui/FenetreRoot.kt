package com.mawena.ccs.ui

import android.view.View
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Key
import androidx.compose.material.icons.filled.Lock
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.DialogProperties
import androidx.compose.ui.window.SecureFlagPolicy
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.mawena.ccs.logique.Root
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

/** Heure du téléphone, relue toutes les `pasMs` (comptes à rebours). */
@Composable
private fun horloge(pasMs: Long): Long {
    var t by remember { mutableLongStateOf(System.currentTimeMillis()) }
    LaunchedEffect(pasMs) {
        while (true) {
            t = System.currentTimeMillis()
            delay(pasMs)
        }
    }
    return t
}

/**
 * Fenêtre au premier plan quand la machine pilotée demande le mot de passe root (`root.ask`).
 * Fermée par `root.resolved`, un refus, ou l'échéance de la demande.
 *
 * Le mot de passe : `remember` (jamais `rememberSaveable`, donc absent de tout Bundle), masqué
 * (Compose interdit alors copier et couper), clavier « mot de passe » sans apprentissage, hors
 * autoremplissage, fenêtre protégée des captures ; le champ est vidé dès l'envoi.
 */
@Composable
fun FenetreRoot(modele: ModeleAppli) {
    val suivi = modele.depot.root
    val etat by suivi.etat.collectAsStateWithLifecycle()
    val d = etat.demande ?: return
    var mdp by remember(d.id) { mutableStateOf("") }
    val maintenant = horloge(1_000)
    val focus = remember { FocusRequester() }
    LaunchedEffect(d.id) { runCatching { focus.requestFocus() } }
    val envoyer = {
        if (mdp.isNotEmpty() && !etat.envoi) {
            val p = mdp
            mdp = ""
            // portée de l'appli : la réponse aboutit même si la fenêtre se recompose ou se ferme
            modele.depot.portee.launch { suivi.repondre(d.id, p) }
        }
    }
    val erreur = etat.avis ?: d.erreur
    AlertDialog(
        onDismissRequest = {},
        properties = DialogProperties(
            dismissOnBackPress = false, dismissOnClickOutside = false, securePolicy = SecureFlagPolicy.SecureOn,
        ),
        icon = { Icon(Icons.Filled.Key, null) },
        title = { Text("${d.machine} demande le mot de passe root") },
        text = {
            // pas d'autoremplissage (ni proposé, ni enregistré) dans cette fenêtre
            val vue = LocalView.current
            DisposableEffect(vue) {
                val racine = vue.rootView
                val avant = racine.importantForAutofill
                racine.importantForAutofill = View.IMPORTANT_FOR_AUTOFILL_NO_EXCLUDE_DESCENDANTS
                onDispose { racine.importantForAutofill = avant }
            }
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                if (d.commande.isNotBlank()) {
                    Surface(color = MaterialTheme.colorScheme.surfaceVariant, shape = MaterialTheme.shapes.small) {
                        Text(
                            d.commande, Modifier.fillMaxWidth().padding(8.dp),
                            fontFamily = FontFamily.Monospace, style = MaterialTheme.typography.bodySmall, maxLines = 6,
                        )
                    }
                }
                OutlinedTextField(
                    mdp, { mdp = it }, Modifier.fillMaxWidth().focusRequester(focus),
                    label = { Text("Mot de passe") }, singleLine = true, enabled = !etat.envoi,
                    isError = erreur != null,
                    visualTransformation = PasswordVisualTransformation(),
                    keyboardOptions = KeyboardOptions(
                        capitalization = KeyboardCapitalization.None, autoCorrectEnabled = false,
                        keyboardType = KeyboardType.Password, imeAction = ImeAction.Send,
                    ),
                    keyboardActions = KeyboardActions(onSend = { envoyer() }),
                )
                erreur?.let { Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall) }
                val bas = listOf(
                    Root.texteEssais(d.essais),
                    "Expire dans ${Root.minutes(d.echeanceMs - maintenant)} min.",
                ).filter { it.isNotEmpty() }.joinToString(" ")
                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    if (etat.envoi) CircularProgressIndicator(Modifier.size(14.dp), strokeWidth = 2.dp)
                    Text(
                        if (etat.envoi) "Vérification…" else bas,
                        style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
        },
        confirmButton = { Button(onClick = envoyer, enabled = mdp.isNotEmpty() && !etat.envoi) { Text("Envoyer") } },
        dismissButton = {
            TextButton(onClick = { mdp = ""; modele.depot.portee.launch { suivi.refuser(d.id) } }, enabled = !etat.envoi) { Text("Refuser") }
        },
    )
}

/** Bandeau discret tant que la machine pilotée garde le mot de passe root, avec « Oublier ». */
@Composable
fun BandeauRoot(modele: ModeleAppli) {
    val suivi = modele.depot.root
    val etat by suivi.etat.collectAsStateWithLifecycle()
    val g = etat.garde ?: return
    val maintenant = horloge(15_000)
    if (maintenant >= g.finMs) return
    val portee = rememberCoroutineScope()
    val avis = LocalAvis.current
    Surface(color = MaterialTheme.colorScheme.errorContainer, contentColor = MaterialTheme.colorScheme.onErrorContainer, modifier = Modifier.fillMaxWidth()) {
        Row(
            Modifier.padding(start = 16.dp, end = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Icon(Icons.Filled.Lock, null, Modifier.size(18.dp))
            Text(Root.texteGarde(g, maintenant), Modifier.weight(1f), style = MaterialTheme.typography.bodyMedium)
            TextButton(onClick = {
                portee.launch {
                    try {
                        suivi.oublier()
                        avis.dire("Mot de passe root effacé.")
                    } catch (e: Exception) {
                        avis.dire("Impossible d'effacer : ${e.texte()}")
                    }
                }
            }) { Text("Oublier") }
        }
    }
}
