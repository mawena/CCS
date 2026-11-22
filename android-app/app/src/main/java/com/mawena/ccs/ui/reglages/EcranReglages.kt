package com.mawena.ccs.ui.reglages

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowDropDown
import androidx.compose.material.icons.filled.Check
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Switch
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
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.mawena.ccs.BuildConfig
import com.mawena.ccs.donnees.Theme
import com.mawena.ccs.logique.DefReglages
import com.mawena.ccs.reseau.Acces
import com.mawena.ccs.reseau.CanalTelephone
import com.mawena.ccs.reseau.EssaiTelephone
import com.mawena.ccs.reseau.EtatConnexion
import com.mawena.ccs.reseau.QrTelephone
import com.mawena.ccs.reseau.Reglages
import com.mawena.ccs.reseau.Revocation
import com.mawena.ccs.ui.BarreHaut
import com.mawena.ccs.ui.Chargement
import com.mawena.ccs.ui.Demandes
import com.mawena.ccs.ui.DialogueServeur
import com.mawena.ccs.ui.EtatErreur
import com.mawena.ccs.ui.LocalAvis
import com.mawena.ccs.ui.ModeleAppli
import com.mawena.ccs.ui.VueDemandes
import com.mawena.ccs.ui.texte
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import java.text.DateFormat
import java.util.Date
import java.util.Locale

private val GENRES_ACCES = mapOf("session" to "Navigateur", "device" to "Appareil retenu (sans code)", "app" to "Application")

/**
 * Réglages (`web/settings.js`) : ceux de l'appli (thème, serveur, déconnexion), le téléphone
 * (ntfy, `web/pages-phone.js`), tous les réglages du serveur (chacun enregistré seul, validé par le
 * pont) et les appareils connectés, révocables.
 */
@Composable
fun EcranReglages(modele: ModeleAppli, retour: () -> Unit) {
    val client = modele.depot.client
    val etat by modele.etat.collectAsStateWithLifecycle()
    val theme by modele.theme.collectAsStateWithLifecycle()
    val identifiants by modele.identifiants.collectAsStateWithLifecycle()
    val avis = LocalAvis.current
    val portee = rememberCoroutineScope()
    val demandes = remember { Demandes() }
    var reglages by remember { mutableStateOf<JsonObject?>(null) }
    var erreur by remember { mutableStateOf<String?>(null) }
    var serveur by remember { mutableStateOf(false) }

    suspend fun charger() {
        try {
            reglages = client.appeler("settings.get", Reglages.serializer()).settings
            erreur = null
        } catch (e: Exception) {
            erreur = e.texte()
        }
    }
    LaunchedEffect(etat is EtatConnexion.Connecte) { if (etat is EtatConnexion.Connecte) charger() }

    /** Enregistre une valeur ; rend l'erreur à afficher sous le champ, ou null. */
    suspend fun enregistrer(chemin: String, valeur: JsonElement): String? = try {
        client.appeler("settings.set", buildJsonObject { put("path", chemin); put("value", valeur) })
        reglages = reglages?.let { DefReglages.ecrire(it, chemin, valeur) }
        avis.dire("Enregistré.")
        null
    } catch (e: Exception) {
        e.texte()
    }

    Column(Modifier.fillMaxSize()) {
        BarreHaut("Réglages", retour = retour)
        LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(12.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            item {
                Groupe("Apparence", "Propre à ce téléphone.") {
                    Theme.entries.forEach { t ->
                        Row(Modifier.fillMaxWidth().clickable { modele.changerTheme(t) }, verticalAlignment = Alignment.CenterVertically) {
                            RadioButton(theme == t, { modele.changerTheme(t) })
                            Text(t.libelle)
                        }
                    }
                }
            }
            item { GroupeNotifications(modele, reglages) }
            item { GroupeVocal(modele) }
            item {
                Groupe("Connexion") {
                    val i = identifiants
                    Text("Serveur : ${i?.serveur.orEmpty()}")
                    Text(
                        "Compte : ${i?.utilisateur.orEmpty()} · " + when {
                            i?.portier == true -> "connexion Portier (cookies)"
                            i?.viaPortier == true -> "Portier, puis jeton d'appareil"
                            else -> "jeton d'appareil"
                        },
                        style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    Text("Appli ${BuildConfig.VERSION_NAME}", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    FlowRow8 {
                        OutlinedButton(onClick = { serveur = true }) { Text("Changer de serveur") }
                        OutlinedButton(onClick = {
                            portee.launch {
                                if (demandes.confirmer("Se déconnecter ?", "Il faudra se reconnecter sur ce téléphone (le jeton reste révocable depuis la liste des appareils).", "Se déconnecter", danger = true)) {
                                    modele.deconnecter()
                                }
                            }
                        }) { Text("Se déconnecter", color = MaterialTheme.colorScheme.error) }
                    }
                }
            }
            val r = reglages
            when {
                r == null && erreur != null -> item { EtatErreur(erreur!!) { portee.launch { charger() } } }
                r == null -> item { Chargement("Chargement des réglages…") }
                else -> {
                    item { GroupeTelephone(modele, r, demandes, recharger = { portee.launch { charger() } }) { c, v -> enregistrer(c, v) } }
                    DefReglages.GROUPES.forEach { g ->
                        item(key = g.titre) {
                            Groupe(g.titre) { g.reglages.forEach { d -> LigneReglage(d, DefReglages.lire(r, d.chemin)) { v -> enregistrer(d.chemin, v) } } }
                        }
                    }
                }
            }
            item { GroupeAppareils(modele, demandes) }
        }
    }
    VueDemandes(demandes)
    if (serveur) {
        DialogueServeur(identifiants?.serveur ?: modele.adresse.value, fermer = { serveur = false }) { t ->
            val avant = modele.adresse.value
            if (!modele.changerAdresse(t)) return@DialogueServeur false
            serveur = false
            if (modele.adresse.value != avant) modele.deconnecter()
            true
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun FlowRow8(contenu: @Composable () -> Unit) {
    FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) { contenu() }
}

@Composable
private fun Groupe(titre: String, texte: String = "", contenu: @Composable () -> Unit) {
    Card(Modifier.fillMaxWidth(), colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceContainer)) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text(titre, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
            if (texte.isNotEmpty()) Text(texte, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            contenu()
        }
    }
}

/** Un réglage : interrupteur, liste de choix ou champ (nombre, heure, texte) enregistré par ✓ ou Entrée. */
@Composable
fun LigneReglage(d: DefReglages.Def, valeur: JsonElement?, enregistrer: suspend (JsonElement) -> String?) {
    val portee = rememberCoroutineScope()
    var erreur by remember(d.chemin) { mutableStateOf<String?>(null) }
    var occupe by remember(d.chemin) { mutableStateOf(false) }
    fun envoyer(v: JsonElement) {
        occupe = true
        portee.launch { erreur = enregistrer(v); occupe = false }
    }
    Column {
        when (val g = d.genre) {
            DefReglages.Genre.Booleen -> {
                val actif = DefReglages.booleen(valeur)
                Row(Modifier.fillMaxWidth().clickable(enabled = !occupe) { envoyer(JsonPrimitive(!actif)) }, verticalAlignment = Alignment.CenterVertically) {
                    Text(d.libelle, Modifier.weight(1f).padding(end = 8.dp))
                    Switch(actif, { envoyer(JsonPrimitive(it)) }, enabled = !occupe)
                }
            }
            is DefReglages.Genre.Choix -> {
                var ouvert by remember { mutableStateOf(false) }
                val actuel = DefReglages.texte(valeur)
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(d.libelle, Modifier.weight(1f).padding(end = 8.dp))
                    Box {
                        TextButton(onClick = { ouvert = true }, enabled = !occupe) {
                            Text(g.options.firstOrNull { it.first == actuel }?.second ?: actuel)
                            Icon(Icons.Filled.ArrowDropDown, null)
                        }
                        DropdownMenu(ouvert, { ouvert = false }) {
                            g.options.forEach { (v, t) ->
                                DropdownMenuItem({ Text(t) }, onClick = { ouvert = false; if (v != actuel) envoyer(JsonPrimitive(v)) })
                            }
                        }
                    }
                }
            }
            else -> {
                val initial = DefReglages.texte(valeur)
                var champ by remember(d.chemin, initial) { mutableStateOf(initial) }
                val change = champ != initial
                fun valider() {
                    when (g) {
                        is DefReglages.Genre.Nombre -> {
                            val (n, e) = DefReglages.nombre(champ, g)
                            if (n == null) erreur = e else envoyer(JsonPrimitive(n))
                        }
                        DefReglages.Genre.Heure -> {
                            val h = DefReglages.heure(champ)
                            if (h == null) erreur = "Heure attendue (HH:MM)." else envoyer(JsonPrimitive(h))
                        }
                        else -> envoyer(JsonPrimitive(champ.trim()))
                    }
                }
                OutlinedTextField(
                    champ, { champ = it; erreur = null }, Modifier.fillMaxWidth(), singleLine = true,
                    label = { Text(d.libelle) }, isError = erreur != null, enabled = !occupe,
                    keyboardOptions = KeyboardOptions(
                        keyboardType = when (g) {
                            is DefReglages.Genre.Nombre -> KeyboardType.Decimal
                            DefReglages.Genre.Heure -> KeyboardType.Number
                            else -> KeyboardType.Uri
                        },
                        capitalization = KeyboardCapitalization.None, autoCorrectEnabled = false, imeAction = ImeAction.Done,
                    ),
                    keyboardActions = KeyboardActions(onDone = { if (change) valider() }),
                    trailingIcon = { if (change) IconButton(onClick = { valider() }) { Icon(Icons.Filled.Check, "Enregistrer") } },
                    placeholder = { if (g == DefReglages.Genre.Heure) Text("HH:MM") },
                )
            }
        }
        if (d.aide.isNotEmpty()) Text(d.aide, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        erreur?.let { Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.error) }
    }
}

/**
 * Notifications de l'appli (service de fond) : actives par défaut. Si ntfy est aussi configuré
 * sur le serveur (page Téléphone), on le dit : les deux préviendraient pour les mêmes attentes.
 */
@Composable
private fun GroupeNotifications(modele: ModeleAppli, r: JsonObject?) {
    val ctx = LocalContext.current
    val actives by modele.notifications.collectAsStateWithLifecycle()
    val cycle = androidx.lifecycle.compose.LocalLifecycleOwner.current
    var permises by remember { mutableStateOf(com.mawena.ccs.notif.Notifs.permises(ctx)) }
    // retour des réglages d'Android : relire la permission
    androidx.compose.runtime.DisposableEffect(cycle) {
        val o = androidx.lifecycle.LifecycleEventObserver { _, e ->
            if (e == androidx.lifecycle.Lifecycle.Event.ON_RESUME) permises = com.mawena.ccs.notif.Notifs.permises(ctx)
        }
        cycle.lifecycle.addObserver(o)
        onDispose { cycle.lifecycle.removeObserver(o) }
    }
    val lanceur = androidx.activity.compose.rememberLauncherForActivityResult(
        androidx.activity.result.contract.ActivityResultContracts.RequestPermission(),
    ) { ok ->
        permises = com.mawena.ccs.notif.Notifs.permises(ctx)
        if (!ok) com.mawena.ccs.ui.ouvrirReglagesNotifications(ctx)
        com.mawena.ccs.notif.ServiceVeille.appliquer(ctx)
    }
    fun demander() {
        if (android.os.Build.VERSION.SDK_INT >= 33) lanceur.launch(android.Manifest.permission.POST_NOTIFICATIONS)
        else com.mawena.ccs.ui.ouvrirReglagesNotifications(ctx)
    }
    fun changer(v: Boolean) {
        modele.changerNotifications(v)
        if (v && !permises) demander()
    }
    val ntfy = r != null && (DefReglages.lire(r, "phone.enabled") as? JsonPrimitive)?.booleanOrNull == true &&
        (DefReglages.lire(r, "phone.topic") as? JsonPrimitive)?.contentOrNull.orEmpty().isNotEmpty()
    Groupe(
        "Notifications",
        "Propre à ce téléphone. Fin de tour, autorisation ou question en attente (Autoriser / Refuser depuis la " +
            "notification), rappel unique si la réponse se fait attendre (réglage « Rappel d'attente » du serveur). " +
            "Rien pour le chat affiché à l'écran.",
    ) {
        Row(Modifier.fillMaxWidth().clickable { changer(!actives) }, verticalAlignment = Alignment.CenterVertically) {
            Text("Notifications de l'appli", Modifier.weight(1f))
            Switch(actives, { changer(it) })
        }
        Text(
            "L'appli reste connectée en arrière-plan : une notification discrète « CCS connecté » le signale " +
                "(masquable dans les réglages d'Android, canal « Connexion en arrière-plan »). Couper ce réglage " +
                "coupe aussi cette connexion.",
            style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        if (actives && !permises) {
            Text("Les notifications de CCS sont bloquées par Android.", color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall)
            OutlinedButton(onClick = { demander() }) { Text("Autoriser les notifications") }
        }
        Text(
            if (ntfy) {
                "ntfy est aussi actif sur le serveur (Téléphone, plus bas) : tu risques d'être prévenu deux fois. " +
                    "Garde l'un des deux : coupe ce réglage, ou l'alerte « attente » de ntfy."
            } else {
                "ntfy (Téléphone, plus bas) fait la même chose sans l'appli ; inutile d'activer les deux."
            },
            style = MaterialTheme.typography.bodySmall,
            color = if (ntfy) MaterialTheme.colorScheme.tertiary else MaterialTheme.colorScheme.onSurfaceVariant,
        )
        TextButton(onClick = { com.mawena.ccs.ui.ouvrirReglagesNotifications(ctx) }) { Text("Réglages des notifications d'Android") }
    }
}

/** Vocal (propre à ce téléphone) : lecture automatique des réponses de Claude. */
@Composable
private fun GroupeVocal(modele: ModeleAppli) {
    val actif by modele.lireReponses.collectAsStateWithLifecycle()
    Groupe(
        "Vocal",
        "Propre à ce téléphone. Micro de la saisie : dictée par la reconnaissance vocale du téléphone (le texte " +
            "s'ajoute, tu relis puis tu envoies). Appui long sur une réponse de Claude : « Lire à voix haute ».",
    ) {
        Row(Modifier.fillMaxWidth().clickable { modele.changerLireReponses(!actif) }, verticalAlignment = Alignment.CenterVertically) {
            Text("Lire les réponses à voix haute", Modifier.weight(1f))
            Switch(actif, { modele.changerLireReponses(it) })
        }
        Text(
            "Chaque réponse terminée du chat affiché est lue, avec la voix française du téléphone (réglages " +
                "d'Android, Synthèse vocale).",
            style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

/** Téléphone (ntfy) : réglages, nouveau canal, lien d'abonnement (à ouvrir dans ntfy), essai. */
@Composable
private fun GroupeTelephone(
    modele: ModeleAppli, r: JsonObject, demandes: Demandes, recharger: () -> Unit,
    enregistrer: suspend (String, JsonElement) -> String?,
) {
    val client = modele.depot.client
    val avis = LocalAvis.current
    val ctx = LocalContext.current
    val portee = rememberCoroutineScope()
    var resultat by remember { mutableStateOf<String?>(null) }
    var lien by remember { mutableStateOf<String?>(null) }
    var occupe by remember { mutableStateOf(false) }
    fun faire(bloc: suspend () -> Unit) {
        occupe = true
        resultat = null
        portee.launch { try { bloc() } catch (e: Exception) { resultat = e.texte() } finally { occupe = false } }
    }
    val g = DefReglages.TELEPHONE
    Groupe(g.titre, g.texte) {
        g.reglages.forEach { d -> LigneReglage(d, DefReglages.lire(r, d.chemin)) { v -> enregistrer(d.chemin, v) } }
        FlowRow8 {
            OutlinedButton(onClick = {
                portee.launch {
                    if (!demandes.confirmer("Créer un nouveau canal ?", "L'ancien canal ne recevra plus rien : il faudra se réabonner au nouveau (QR code) sur chaque téléphone.", "Créer le canal")) return@launch
                    faire {
                        client.appeler("phone.renew", CanalTelephone.serializer())
                        avis.dire("Nouveau canal créé.")
                        recharger()
                    }
                }
            }, enabled = !occupe) { Text("Créer un nouveau canal") }
            OutlinedButton(onClick = { faire { lien = client.appeler("phone.qr", QrTelephone.serializer()).url } }, enabled = !occupe) {
                Text("Lien d'abonnement")
            }
            Button(onClick = {
                faire {
                    val e = client.appeler("phone.test", EssaiTelephone.serializer())
                    if (e.ok) avis.dire(e.message) else resultat = e.message
                }
            }, enabled = !occupe) { Text("Envoyer un essai") }
        }
        resultat?.let { Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall) }
        lien?.let { u ->
            Text("Ouvre ce lien dans l'application ntfy (ou scanne le QR code de la version web) :", style = MaterialTheme.typography.bodySmall)
            Text(u, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.primary)
            FlowRow8 {
                TextButton(onClick = {
                    ctx.getSystemService(ClipboardManager::class.java)?.setPrimaryClip(ClipData.newPlainText("ntfy", u))
                    avis.dire("Lien copié.")
                }) { Text("Copier") }
                TextButton(onClick = {
                    runCatching { ctx.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(u.replaceFirst(Regex("^https?://"), "ntfy://")))) }
                        .onFailure { runCatching { ctx.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(u))) } }
                }) { Text("Ouvrir dans ntfy") }
            }
        }
    }
}

/** Appareils connectés (`/api/tokens`), révocables (`/api/revoke`). */
@Composable
private fun GroupeAppareils(modele: ModeleAppli, demandes: Demandes) {
    val identifiants by modele.identifiants.collectAsStateWithLifecycle()
    val avis = LocalAvis.current
    val portee = rememberCoroutineScope()
    var liste by remember { mutableStateOf<List<Acces>?>(null) }
    var erreur by remember { mutableStateOf<String?>(null) }

    suspend fun charger() {
        val i = identifiants ?: return
        try {
            val l = modele.depot.api.acces(i)
            if (l == null) {
                erreur = "Liste indisponible avec cette connexion : le serveur ne la donne qu'à une session de navigateur ou Portier. Ouvre la version web."
            } else {
                liste = l.tokens.sortedByDescending { it.dernierUsage ?: 0.0 }
                erreur = null
            }
        } catch (e: Exception) {
            erreur = "Liste indisponible : ${e.texte()}"
        }
    }
    LaunchedEffect(identifiants) { charger() }

    Groupe("Appareils", "Navigateurs, appareils retenus et applications connectés à ton compte.") {
        erreur?.let { Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant) }
        val l = liste
        if (l == null && erreur == null) Chargement()
        l?.forEach { t ->
            Row(verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text(t.name.ifEmpty { GENRES_ACCES[t.kind] ?: t.kind.orEmpty() }, fontWeight = FontWeight.SemiBold)
                    Text(
                        (GENRES_ACCES[t.kind] ?: t.kind.orEmpty()) + (t.dernierUsage?.let { " · utilisé le " + date(it) } ?: ""),
                        style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                TextButton(onClick = {
                    portee.launch {
                        if (!demandes.confirmer("Révoquer cet accès ?", "L'appareil devra se reconnecter (si c'est ce téléphone : il faudra se reconnecter ici).", "Révoquer", danger = true)) return@launch
                        val i = identifiants ?: return@launch
                        when (val r = modele.depot.api.revoquer(i, t.id)) {
                            Revocation.Faite -> { avis.dire("Accès révoqué."); charger() }
                            is Revocation.Refusee -> avis.dire(r.message)
                        }
                    }
                }) { Text("Révoquer", color = MaterialTheme.colorScheme.error) }
            }
        }
    }
}

private fun date(s: Double): String =
    DateFormat.getDateTimeInstance(DateFormat.SHORT, DateFormat.SHORT, Locale.FRANCE).format(Date((s * 1000).toLong()))
