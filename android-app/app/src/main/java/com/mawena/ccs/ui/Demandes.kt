package com.mawena.ccs.ui

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.text.TextRange
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.text.input.TextFieldValue
import kotlinx.coroutines.CompletableDeferred

/**
 * Questions posées au milieu d'une action (confirmation, nom à saisir), attendues par une
 * coroutine : `if (demandes.confirmer(…)) …`. Afficher [VueDemandes] une fois dans l'écran.
 */
class Demandes {
    sealed interface Demande
    class Confirmer(val titre: String, val texte: String, val bouton: String, val danger: Boolean, val r: CompletableDeferred<Boolean>) : Demande
    class Nom(val titre: String, val valeur: String, val bouton: String, val verifier: (String) -> String?, val r: CompletableDeferred<String?>) : Demande

    var courante by mutableStateOf<Demande?>(null)
        private set

    suspend fun confirmer(titre: String, texte: String, bouton: String, danger: Boolean = false): Boolean {
        val r = CompletableDeferred<Boolean>()
        courante = Confirmer(titre, texte, bouton, danger, r)
        return try { r.await() } finally { courante = null }
    }

    suspend fun nom(titre: String, valeur: String = "", bouton: String = "Valider", verifier: (String) -> String? = { null }): String? {
        val r = CompletableDeferred<String?>()
        courante = Nom(titre, valeur, bouton, verifier, r)
        return try { r.await() } finally { courante = null }
    }
}

@Composable
fun VueDemandes(d: Demandes) {
    when (val q = d.courante) {
        null -> Unit
        is Demandes.Confirmer -> Confirmation(q.titre, q.texte, q.bouton, q.danger, surOui = { q.r.complete(true) }, surNon = { q.r.complete(false) })
        is Demandes.Nom -> {
            var champ by remember(q) {
                val point = q.valeur.lastIndexOf('.')
                mutableStateOf(TextFieldValue(q.valeur, TextRange(0, if (point > 0) point else q.valeur.length)))
            }
            val erreur = remember(champ.text) { if (champ.text.isBlank()) null else q.verifier(champ.text.trim()) }
            val focus = remember { FocusRequester() }
            LaunchedEffect(q) { focus.requestFocus() }
            AlertDialog(
                onDismissRequest = { q.r.complete(null) },
                title = { Text(q.titre) },
                text = {
                    Column {
                        OutlinedTextField(
                            champ, { champ = it }, Modifier.fillMaxWidth().focusRequester(focus), singleLine = true,
                            label = { Text("Nom") }, isError = erreur != null,
                            keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.None, autoCorrectEnabled = false),
                        )
                        erreur?.let { Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall) }
                    }
                },
                confirmButton = {
                    Button(onClick = { q.r.complete(champ.text.trim()) }, enabled = champ.text.isNotBlank() && erreur == null) { Text(q.bouton) }
                },
                dismissButton = { TextButton(onClick = { q.r.complete(null) }) { Text("Annuler") } },
            )
        }
    }
}
