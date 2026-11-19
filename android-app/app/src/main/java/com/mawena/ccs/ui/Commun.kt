package com.mawena.ccs.ui

import androidx.compose.foundation.background
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.SnackbarDuration
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.SnackbarResult
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.launch

/** Couleurs d'état, les mêmes que la version web (avertissement, réussite). */
val Avertissement = Color(0xFFE5A50A)
val Reussite = Color(0xFF33D17A)

/** Messages courts en bas de l'écran (les « toasts » de la version web), avec action facultative. */
class Avis(private val hote: SnackbarHostState, private val portee: CoroutineScope) {
    fun dire(texte: String, action: String? = null, long: Boolean = false, quandAction: (() -> Unit)? = null) {
        portee.launch {
            hote.currentSnackbarData?.dismiss()
            val r = hote.showSnackbar(
                texte, actionLabel = action, withDismissAction = action == null,
                duration = if (action != null || long) SnackbarDuration.Long else SnackbarDuration.Short,
            )
            if (r == SnackbarResult.ActionPerformed) quandAction?.invoke()
        }
    }
}

val LocalAvis = staticCompositionLocalOf<Avis> { error("Avis non fourni") }

@Composable
fun Chargement(texte: String? = null, modifier: Modifier = Modifier) {
    Row(
        modifier.fillMaxWidth().padding(16.dp),
        horizontalArrangement = Arrangement.spacedBy(12.dp, Alignment.CenterHorizontally),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        CircularProgressIndicator(Modifier.size(20.dp), strokeWidth = 2.dp)
        if (texte != null) Text(texte, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

@Composable
fun EtatErreur(message: String, reessayer: (() -> Unit)? = null) {
    Column(
        Modifier.fillMaxWidth().padding(16.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Text(message, color = MaterialTheme.colorScheme.error, textAlign = TextAlign.Center)
        if (reessayer != null) OutlinedButton(onClick = reessayer) { Text("Réessayer") }
    }
}

@Composable
fun EtatVide(message: String, action: (@Composable () -> Unit)? = null) {
    Column(
        Modifier.fillMaxWidth().padding(24.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text(message, color = MaterialTheme.colorScheme.onSurfaceVariant, textAlign = TextAlign.Center)
        action?.invoke()
    }
}

@Composable
fun Pastille(couleur: Color, taille: Dp = 10.dp) {
    Box(Modifier.size(taille).background(couleur, CircleShape))
}

/** Couleur d'un compte (`#rrggbb` du serveur), ou l'accent si elle est illisible. */
fun couleurDe(texte: String?, defaut: Color = Accent): Color =
    runCatching { Color(android.graphics.Color.parseColor(texte)) }.getOrDefault(defaut)

/** Confirmation (la `confirmSheet` de la version web). */
@Composable
fun Confirmation(
    titre: String,
    texte: String,
    confirmer: String,
    danger: Boolean = false,
    surOui: () -> Unit,
    surNon: () -> Unit,
) {
    AlertDialog(
        onDismissRequest = surNon,
        title = { Text(titre) },
        text = { Text(texte) },
        confirmButton = {
            Button(
                onClick = surOui,
                colors = if (danger) ButtonDefaults.buttonColors(
                    containerColor = MaterialTheme.colorScheme.error, contentColor = MaterialTheme.colorScheme.onError,
                ) else ButtonDefaults.buttonColors(),
            ) { Text(confirmer) }
        },
        dismissButton = { TextButton(onClick = surNon) { Text("Annuler") } },
    )
}

/** Message d'une exception pour l'utilisateur. */
fun Throwable.texte(): String = message?.takeIf { it.isNotBlank() } ?: "Erreur inattendue."

/** Barre du haut d'un écran secondaire (sans marge de barre d'état : le Scaffold la compte déjà). */
@OptIn(androidx.compose.material3.ExperimentalMaterial3Api::class)
@Composable
fun BarreHaut(
    titre: String,
    sousTitre: String? = null,
    retour: (() -> Unit)? = null,
    actions: @Composable androidx.compose.foundation.layout.RowScope.() -> Unit = {},
) {
    androidx.compose.material3.TopAppBar(
        title = {
            Column {
                Text(titre, maxLines = 1, overflow = androidx.compose.ui.text.style.TextOverflow.Ellipsis)
                if (!sousTitre.isNullOrBlank()) {
                    Text(
                        sousTitre, maxLines = 1, overflow = androidx.compose.ui.text.style.TextOverflow.Ellipsis,
                        style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
        },
        navigationIcon = {
            if (retour != null) {
                androidx.compose.material3.IconButton(onClick = retour) {
                    androidx.compose.material3.Icon(androidx.compose.material.icons.Icons.AutoMirrored.Filled.ArrowBack, "Retour")
                }
            }
        },
        actions = actions,
        windowInsets = androidx.compose.foundation.layout.WindowInsets(0),
    )
}

/** Titre de section d'une liste. */
@Composable
fun TitreSection(texte: String, modifier: Modifier = Modifier, action: (@Composable () -> Unit)? = null) {
    Row(modifier.fillMaxWidth().padding(top = 8.dp), verticalAlignment = Alignment.CenterVertically) {
        Text(
            texte, Modifier.weight(1f), style = MaterialTheme.typography.titleSmall,
            color = MaterialTheme.colorScheme.primary, fontWeight = androidx.compose.ui.text.font.FontWeight.SemiBold,
        )
        action?.invoke()
    }
}
