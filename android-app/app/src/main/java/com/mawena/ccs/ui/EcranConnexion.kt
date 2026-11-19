package com.mawena.ccs.ui

import android.content.ActivityNotFoundException
import android.content.Intent
import android.net.Uri
import android.os.Build
import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Visibility
import androidx.compose.material.icons.filled.VisibilityOff
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.mawena.ccs.R
import com.mawena.ccs.donnees.Identifiants
import com.mawena.ccs.reseau.InfoPortier
import com.mawena.ccs.reseau.ReponseConnexion
import kotlinx.coroutines.launch
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull
import kotlin.math.ceil

/**
 * Connexion : appairage de l'appareil (identifiant et mot de passe Ubuntu, puis code TOTP ; à la
 * première connexion, secret à ajouter dans l'appli d'authentification), ou connexion par Portier
 * si le serveur l'a activée. L'appairage rend un jeton d'appareil, gardé chiffré.
 */
@Composable
fun EcranConnexion(modele: ModeleAppli) {
    val adresse by modele.adresse.collectAsStateWithLifecycle()
    val avis by modele.avis.collectAsStateWithLifecycle()
    val portee = rememberCoroutineScope()
    val contexte = LocalContext.current

    var utilisateur by rememberSaveable { mutableStateOf("") }
    var motDePasse by rememberSaveable { mutableStateOf("") }
    var code by rememberSaveable { mutableStateOf("") }
    var voirMotDePasse by rememberSaveable { mutableStateOf(false) }
    var codeDemande by rememberSaveable { mutableStateOf(false) }
    var enAttente by rememberSaveable { mutableStateOf<String?>(null) }
    var secret by rememberSaveable { mutableStateOf<String?>(null) }
    var message by remember { mutableStateOf<String?>(null) }
    var occupe by remember { mutableStateOf(false) }
    var portier by remember { mutableStateOf<InfoPortier?>(null) }
    var vuePortier by rememberSaveable { mutableStateOf(false) }
    var changerServeur by remember { mutableStateOf(false) }

    LaunchedEffect(adresse) {
        portier = runCatching { modele.depot.api.portier(adresse) }.getOrNull()
    }
    LaunchedEffect(avis) {
        if (avis != null) {
            message = avis
            modele.avisLu()
        }
    }

    if (vuePortier && portier?.actif == true) {
        EcranPortier(
            adresse = adresse,
            connexion = portier!!.connexion,
            fermer = { vuePortier = false },
            reussi = { cookies ->
                vuePortier = false
                occupe = true
                portee.launch {
                    val i = Identifiants(adresse, "", cookies = cookies)
                    val s = runCatching { modele.depot.api.session(i) }
                    occupe = false
                    when {
                        s.isFailure -> message = "Serveur injoignable."
                        s.getOrNull() == null -> message = "Portier n'a pas ouvert CCS pour ce compte."
                        else -> {
                            // jeton d'appareil durable si le serveur sait le donner, sinon les cookies
                            val jeton = modele.depot.api.jetonAppli(i, nomModele())
                            modele.connecte(i.copy(utilisateur = s.getOrNull()!!.user, jeton = jeton))
                        }
                    }
                }
            },
        )
        return
    }

    fun traiter(r: ReponseConnexion) {
        when (r.status) {
            "ok" -> if (r.token != null) {
                motDePasse = ""
                modele.connecte(Identifiants(adresse, r.user ?: utilisateur, jeton = r.token))
            } else {
                message = "Le serveur n'a pas remis de jeton d'appareil."
            }
            "code" -> {
                codeDemande = true
                message = "Saisis le code de ton appli d'authentification."
            }
            "enroll" -> {
                enAttente = r.pending
                secret = r.secret
                code = ""
                message = null
            }
            "blocked" -> message = "Trop d'essais : réessaie dans ${ceil((r.retryAfter ?: 60.0) / 60).toInt().coerceAtLeast(1)} min."
            else -> message = r.message ?: "Connexion impossible."
        }
    }

    fun valider() {
        if (occupe) return
        message = null
        occupe = true
        portee.launch {
            val r = if (enAttente != null) {
                modele.depot.api.inscrire(adresse, enAttente!!, code.trim())
            } else {
                modele.depot.api.appairer(adresse, utilisateur.trim(), motDePasse, code.trim(), nomAppareil())
            }
            occupe = false
            if (enAttente != null && r.status != "ok" && r.message?.contains("expir") == true) {
                enAttente = null
                secret = null
            }
            traiter(r)
        }
    }

    Surface(Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.background) {
        Column(
            Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .imePadding()
                .padding(24.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Spacer(Modifier.height(32.dp))
            Image(
                painterResource(R.drawable.logo_ccs), contentDescription = null,
                modifier = Modifier.size(96.dp).clip(RoundedCornerShape(22.dp)),
            )
            Spacer(Modifier.height(12.dp))
            Text("CCS", style = MaterialTheme.typography.headlineMedium)
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    adresse.removePrefix("https://"),
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                TextButton(onClick = { changerServeur = true }, enabled = !occupe) { Text("Changer") }
            }
            Spacer(Modifier.height(16.dp))

            Column(Modifier.widthIn(max = 420.dp).fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                if (enAttente == null) {
                    OutlinedTextField(
                        utilisateur, { utilisateur = it }, Modifier.fillMaxWidth(),
                        label = { Text("Identifiant Ubuntu") }, singleLine = true, enabled = !occupe,
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Ascii, imeAction = ImeAction.Next, autoCorrectEnabled = false),
                    )
                    OutlinedTextField(
                        motDePasse, { motDePasse = it }, Modifier.fillMaxWidth(),
                        label = { Text("Mot de passe") }, singleLine = true, enabled = !occupe,
                        visualTransformation = if (voirMotDePasse) VisualTransformation.None else PasswordVisualTransformation(),
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password, imeAction = ImeAction.Next),
                        trailingIcon = {
                            IconButton(onClick = { voirMotDePasse = !voirMotDePasse }) {
                                Icon(
                                    if (voirMotDePasse) Icons.Filled.VisibilityOff else Icons.Filled.Visibility,
                                    contentDescription = if (voirMotDePasse) "Masquer" else "Afficher",
                                )
                            }
                        },
                    )
                } else {
                    Text("Première connexion : ajoute ce secret dans ton appli d'authentification, puis saisis le premier code.")
                    val presse = LocalClipboardManager.current
                    Surface(color = MaterialTheme.colorScheme.surfaceContainerHigh, shape = RoundedCornerShape(8.dp)) {
                        SelectionContainer {
                            Text(
                                secret.orEmpty(), Modifier.padding(12.dp).fillMaxWidth(),
                                fontFamily = FontFamily.Monospace,
                            )
                        }
                    }
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        OutlinedButton(onClick = { presse.setText(AnnotatedString(secret.orEmpty())) }) { Text("Copier") }
                        OutlinedButton(onClick = {
                            val hote = adresse.toHttpUrlOrNull()?.host ?: "ccs"
                            val uri = Uri.parse("otpauth://totp/CCS:${Uri.encode("$utilisateur@$hote")}?secret=$secret&issuer=CCS")
                            try {
                                contexte.startActivity(Intent(Intent.ACTION_VIEW, uri))
                            } catch (_: ActivityNotFoundException) {
                                message = "Aucune appli d'authentification ne prend ce lien : copie le secret."
                            }
                        }) { Text("Ouvrir l'appli") }
                    }
                }
                if (codeDemande || enAttente != null) {
                    OutlinedTextField(
                        code, { code = it.filter(Char::isDigit).take(8) }, Modifier.fillMaxWidth(),
                        label = { Text("Code à 6 chiffres") }, singleLine = true, enabled = !occupe,
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.NumberPassword, imeAction = ImeAction.Done),
                        keyboardActions = KeyboardActions(onDone = { valider() }),
                    )
                }
                message?.let { Text(it, color = MaterialTheme.colorScheme.error) }
                Button(
                    onClick = { valider() }, Modifier.fillMaxWidth(),
                    enabled = !occupe && (enAttente != null || (utilisateur.isNotBlank() && motDePasse.isNotEmpty())),
                ) {
                    if (occupe) CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp)
                    else Text(if (enAttente != null) "Valider le code" else "Appairer cet appareil")
                }
                if (enAttente != null) {
                    TextButton(onClick = { enAttente = null; secret = null; code = "" }, Modifier.fillMaxWidth()) {
                        Text("Annuler")
                    }
                }
                if (portier?.actif == true && enAttente == null) {
                    HorizontalDivider(Modifier.padding(vertical = 8.dp))
                    OutlinedButton(onClick = { vuePortier = true }, Modifier.fillMaxWidth(), enabled = !occupe) {
                        Text("Se connecter via Portier")
                    }
                }
                Text(
                    "L'appareil reçoit un jeton propre, gardé chiffré sur le téléphone, que tu peux révoquer depuis la version web.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }

    if (changerServeur) {
        DialogueServeur(
            actuel = adresse,
            fermer = { changerServeur = false },
            enregistrer = { texte ->
                if (modele.changerAdresse(texte)) {
                    changerServeur = false
                    enAttente = null
                    secret = null
                    codeDemande = false
                    message = null
                    true
                } else {
                    false
                }
            },
        )
    }
}

/** Nom du modèle du téléphone (« Pixel 4 XL »), pour le jeton demandé après Portier. */
fun nomModele(): String = Build.MODEL.orEmpty().ifBlank { "Appli Android" }.take(60)

private fun nomAppareil(): String {
    val modele = Build.MODEL.orEmpty()
    val marque = Build.MANUFACTURER.orEmpty().replaceFirstChar { it.uppercase() }
    val nom = if (modele.startsWith(marque, ignoreCase = true)) modele else "$marque $modele"
    return "Appli Android ($nom)".take(60)
}

@Composable
fun DialogueServeur(actuel: String, fermer: () -> Unit, enregistrer: (String) -> Boolean) {
    var texte by rememberSaveable { mutableStateOf(actuel) }
    var erreur by remember { mutableStateOf(false) }
    AlertDialog(
        onDismissRequest = fermer,
        title = { Text("Serveur") },
        text = {
            Column {
                Text("Adresse du serveur CCS.")
                Spacer(Modifier.height(12.dp))
                OutlinedTextField(
                    texte, { texte = it; erreur = false }, singleLine = true,
                    label = { Text("Adresse") },
                    isError = erreur,
                    supportingText = { if (erreur) Text("Adresse invalide (exemple : https://ccs.mawena.cloud)") },
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri, autoCorrectEnabled = false),
                )
                TextButton(onClick = { texte = com.mawena.ccs.donnees.Adresse.PAR_DEFAUT; erreur = false }) {
                    Text("Par défaut")
                }
            }
        },
        confirmButton = { TextButton(onClick = { erreur = !enregistrer(texte) }) { Text("Enregistrer") } },
        dismissButton = { TextButton(onClick = fermer) { Text("Annuler") } },
    )
}
