package com.mawena.ccs.ui

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.IntrinsicSize
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Bolt
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.ContentCopy
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Computer
import androidx.compose.material.icons.filled.Dns
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.Hub
import androidx.compose.material.icons.filled.Key
import androidx.compose.material.icons.filled.Language
import androidx.compose.material.icons.filled.Laptop
import androidx.compose.material.icons.filled.NetworkPing
import androidx.compose.material.icons.filled.PhoneAndroid
import androidx.compose.material.icons.filled.PhoneIphone
import androidx.compose.material.icons.filled.Router
import androidx.compose.material.icons.filled.SwapHoriz
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.SegmentedButton
import androidx.compose.material3.SegmentedButtonDefaults
import androidx.compose.material3.SingleChoiceSegmentedButtonRow
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.mawena.ccs.logique.Calcul
import com.mawena.ccs.logique.Reseau
import com.mawena.ccs.logique.Reseau.Chemin
import com.mawena.ccs.reseau.Appareil
import com.mawena.ccs.reseau.AppareilValide
import com.mawena.ccs.reseau.CleReseau
import com.mawena.ccs.reseau.EtatReseau
import com.mawena.ccs.reseau.ListeMachines
import com.mawena.ccs.reseau.ListeTravaux
import com.mawena.ccs.reseau.Machine
import com.mawena.ccs.reseau.PcAjoute
import com.mawena.ccs.reseau.Ping
import com.mawena.ccs.reseau.ReglagesRicochet
import com.mawena.ccs.reseau.TravailDistant
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.sin

// Couleurs des chemins, les mêmes que la version web.
private val CouleurLan = Color(0xFF2EC27E)
private val CouleurDirect = Color(0xFF3584E4)
private val CouleurRelais = Color(0xFFE5A50A)
private val CouleurHors = Color(0xFF9A9AA2)
private val CouleurIci = Color(0xFF9141AC)

private fun couleur(c: Chemin) = when (c) {
    Chemin.Lan -> CouleurLan
    Chemin.Direct -> CouleurDirect
    Chemin.Relais -> CouleurRelais
    Chemin.Ici -> CouleurIci
    else -> CouleurHors
}

private fun iconeChemin(c: Chemin): ImageVector = when (c) {
    Chemin.Lan -> Icons.Filled.Home
    Chemin.Direct -> Icons.Filled.Bolt
    Chemin.Relais -> Icons.Filled.Router
    Chemin.Ici -> Icons.Filled.CheckCircle
    Chemin.Ricochet -> Icons.Filled.SwapHoriz
    else -> Icons.Filled.NetworkPing
}

private fun iconeAppareil(a: Appareil): ImageVector = when (Reseau.genre(a)) {
    Reseau.Genre.Serveur -> Icons.Filled.Dns
    Reseau.Genre.Portable -> Icons.Filled.Laptop
    Reseau.Genre.Android -> Icons.Filled.PhoneAndroid
    Reseau.Genre.IPhone -> Icons.Filled.PhoneIphone
    Reseau.Genre.Bureau -> Icons.Filled.Computer
}

/**
 * Onglet « Réseau » : le réseau maillé de tous les appareils (méthodes `network.*`) et, sur la fiche
 * de chaque machine de calcul, sa charge, ses outils, ses places et le choix de la machine pilotée ;
 * puis les travaux, « Lancer une commande », l'ajout d'un appareil et, replié, le secours Ricochet
 * (méthodes `machines.*`, comme `reseau.js` et `calcul.js` du web). Tout ce qui touchait aux
 * machines est ici : il n'y a plus d'écran « Machines » à part.
 */
@Composable
fun EcranReseau(modele: ModeleAppli) {
    val avis = LocalAvis.current
    val portee = rememberCoroutineScope()
    val client = modele.depot.client
    var etat by remember { mutableStateOf<EtatReseau?>(null) }
    var erreur by remember { mutableStateOf<String?>(null) }
    val pings = remember { mutableStateMapOf<String, Ping>() }
    var aRenommer by remember { mutableStateOf<Appareil?>(null) }
    var aRetirer by remember { mutableStateOf<Appareil?>(null) }
    // calcul réparti
    val courante by modele.machine.collectAsStateWithLifecycle()
    var liste by remember { mutableStateOf<ListeMachines?>(null) }
    var travaux by remember { mutableStateOf<List<TravailDistant>?>(null) }
    var erreurTravaux by remember { mutableStateOf<String?>(null) }
    var reglages by remember { mutableStateOf<ReglagesRicochet?>(null) }
    var erreurReglages by remember { mutableStateOf<String?>(null) }
    var journal by remember { mutableStateOf<TravailDistant?>(null) }
    var aArreter by remember { mutableStateOf<TravailDistant?>(null) }

    suspend fun recharger() {
        runCatching { client.appeler("network.status", EtatReseau.serializer()) }
            .onSuccess { etat = it; erreur = null }
            .onFailure { erreur = it.message ?: "Réseau injoignable." }
    }
    LaunchedEffect(Unit) {
        while (true) {
            recharger()
            delay(10_000)
        }
    }

    suspend fun rechargerCalcul() {
        modele.rafraichirMachines()?.let { liste = it }
        runCatching { client.appeler("machines.jobs", ListeTravaux.serializer()) }
            .onSuccess { travaux = it.jobs; erreurTravaux = null }
            .onFailure { erreurTravaux = it.message ?: "Travaux injoignables." }
    }
    suspend fun rechargerReglages() {
        runCatching { client.appeler("machines.settings", ReglagesRicochet.serializer()) }
            .onSuccess { reglages = it; erreurReglages = null }
            .onFailure { erreurReglages = it.message ?: "Réglages illisibles." }
    }
    LaunchedEffect(Unit) {
        while (true) {
            if (reglages == null) rechargerReglages()      // relu jusqu'à la première réponse
            rechargerCalcul()
            delay(5_000)
        }
    }
    val machines = liste?.machines.orEmpty()

    val e = etat
    LazyColumn(
        Modifier.fillMaxWidth(),
        contentPadding = androidx.compose.foundation.layout.PaddingValues(12.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        item { Entete(e, erreur) }
        if (e == null) {
            item { Chargement() }
            return@LazyColumn
        }
        if (e.ici != null || e.peers.isNotEmpty()) item { Carte(e) }
        item {
            Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(top = 4.dp)) {
                Icon(Icons.Filled.Hub, null)
                Spacer(Modifier.width(8.dp))
                Text("Appareils", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
            }
        }
        items(Reseau.fiches(e, machines), key = { if (it.sansMaille) "ricochet:${it.machine?.id}" else it.appareil.name }) { f ->
            val a = f.appareil
            val m = f.machine
            FicheAppareil(
                a, f.ici, e, pings[a.name], f.sansMaille, m?.nom,
                calcul = when {
                    m != null -> ({
                        val pilotee = if (m.local) courante.isEmpty() else m.id == courante
                        BlocCalcul(
                            m, pilotee,
                            piloter = when {
                                pilotee -> null
                                m.local -> ({ modele.choisirMachine("", "") })
                                m.choisissable -> ({ modele.choisirMachine(m.id, m.nom) })
                                else -> null
                            },
                            changerLimite = { n ->
                                portee.launch {
                                    runCatching {
                                        client.appeler("machines.limit", buildJsonObject { put("machine", m.id); put("limit", n) })
                                    }.onSuccess { avis.dire("Limite enregistrée."); rechargerCalcul() }
                                        .onFailure { avis.dire(it.message ?: "Limite non enregistrée.") }
                                }
                            },
                        )
                    })
                    // serveur absent de machines.list : de quoi y revenir quand on pilote une autre machine
                    f.ici && courante.isNotEmpty() -> ({
                        TextButton(onClick = { modele.choisirMachine("", "") }) {
                            Icon(Icons.Filled.Computer, null, Modifier.size(16.dp)); Spacer(Modifier.width(4.dp)); Text("Piloter ce serveur")
                        }
                    })
                    else -> null
                },
                lancerPing = {
                    portee.launch {
                        pings[a.name] = runCatching {
                            client.appeler("network.ping", Ping.serializer(), buildJsonObject { put("name", a.name) })
                        }.getOrElse { Ping(ok = false, error = it.message) }
                    }
                },
                renommer = { aRenommer = a },
                retirer = { aRetirer = a },
            )
        }
        item {
            SectionTravaux(travaux, erreurTravaux, journal = { journal = it }, arreter = { aArreter = it })
        }
        item {
            FormulaireLancer(machines, Calcul.maison(reglages?.path.orEmpty())) { params ->
                runCatching {
                    client.appeler("machines.start", buildJsonObject { params.forEach { (k, v) -> put(k, v) } })
                }.fold({ rechargerCalcul(); null }, { it.message ?: "Lancement impossible." })
            }
        }
        if (e.server) item {
            AjoutAppareil(e,
                ricochet = Calcul.peutAjouterPc(reglages),
                ajouterPc = { id, compte, nom, complet ->
                    runCatching {
                        client.appeler("machines.add", PcAjoute.serializer(), buildJsonObject {
                            put("machine", id); put("user", compte)
                            if (nom.isNotEmpty()) put("name", nom)
                            if (complet) put("full", true)
                        })
                    }.onSuccess { rechargerCalcul() }.onFailure { avis.dire(it.message ?: "Ajout impossible.") }.getOrNull()
                },
                creerCle = { nom ->
                    runCatching {
                        client.appeler("network.key", CleReseau.serializer(),
                            buildJsonObject { if (nom.isNotEmpty()) put("name", nom) })
                    }.onFailure { avis.dire(it.message ?: "Clé impossible.") }.getOrNull()
                },
                valider = { cle ->
                    runCatching {
                        client.appeler("network.register", AppareilValide.serializer(), buildJsonObject { put("key", cle) })
                    }.onSuccess { avis.dire("${it.name} ajouté au réseau."); recharger() }
                        .onFailure { avis.dire(it.message ?: "Validation impossible.") }.isSuccess
                },
            )
        }
        item {
            SecoursRicochet(
                reglages, erreurReglages, liste?.message?.ifBlank { null }, liste?.configured != false,
                enregistrer = { relais, jeton ->
                    runCatching {
                        client.appeler("machines.configure", buildJsonObject {
                            relais?.let { put("relay", it) }
                            jeton?.let { put("token", it) }
                        })
                    }.onFailure { avis.dire(it.message ?: "Enregistrement impossible.") }.isSuccess
                        .also { if (it) { rechargerReglages(); rechargerCalcul() } }
                },
            )
        }
    }

    journal?.let { t ->
        FeuilleJournal(client, t, travaux?.firstOrNull { it.id == t.id }, fermer = { journal = null })
    }
    aArreter?.let { t ->
        ConfirmerArret(t, annuler = { aArreter = null }) {
            aArreter = null
            portee.launch {
                runCatching { client.appeler("machines.stop", buildJsonObject { put("id", t.id) }) }
                    .onSuccess { avis.dire("Travail arrêté."); rechargerCalcul() }
                    .onFailure { avis.dire(it.message ?: "Arrêt impossible.") }
            }
        }
    }

    aRenommer?.let { a ->
        var nom by remember(a.name) { mutableStateOf(a.name) }
        AlertDialog(
            onDismissRequest = { aRenommer = null },
            title = { Text("Renommer ${a.name}") },
            text = {
                OutlinedTextField(nom, { nom = it.trim().lowercase() }, singleLine = true, label = { Text("Nouveau nom") },
                    isError = !Reseau.nomValide(nom),
                    supportingText = { Text("Lettres minuscules, chiffres et tirets.") })
            },
            confirmButton = {
                TextButton(enabled = Reseau.nomValide(nom) && nom != a.name, onClick = {
                    aRenommer = null
                    portee.launch {
                        runCatching {
                            client.appeler("network.rename", buildJsonObject { put("name", a.name); put("new", nom) })
                        }.onSuccess { avis.dire("Renommé."); recharger() }.onFailure { avis.dire(it.message ?: "Renommage impossible.") }
                    }
                }) { Text("Renommer") }
            },
            dismissButton = { TextButton(onClick = { aRenommer = null }) { Text("Annuler") } },
        )
    }
    aRetirer?.let { a ->
        AlertDialog(
            onDismissRequest = { aRetirer = null },
            title = { Text("Retirer ${a.name} du réseau ?") },
            text = { Text("L'appareil perd l'accès au réseau. Il faudra l'inscrire à nouveau.") },
            confirmButton = {
                TextButton(onClick = {
                    aRetirer = null
                    portee.launch {
                        runCatching { client.appeler("network.remove", buildJsonObject { put("name", a.name) }) }
                            .onSuccess { avis.dire("Retiré."); recharger() }.onFailure { avis.dire(it.message ?: "Retrait impossible.") }
                    }
                }) { Text("Retirer", color = MaterialTheme.colorScheme.error) }
            },
            dismissButton = { TextButton(onClick = { aRetirer = null }) { Text("Annuler") } },
        )
    }
}

@Composable
private fun Entete(e: EtatReseau?, erreur: String?) {
    val degrade = Brush.linearGradient(listOf(Color(0xFF1C71D8), Color(0xFF613583), Color(0xFF26A269)))
    Box(Modifier.fillMaxWidth().clip(RoundedCornerShape(18.dp)).background(degrade).padding(16.dp)) {
        Column(verticalArrangement = Arrangement.spacedBy(14.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Box(Modifier.size(52.dp).clip(RoundedCornerShape(15.dp)).background(Color.White.copy(alpha = .16f)), contentAlignment = Alignment.Center) {
                    Icon(Icons.Filled.Language, null, tint = Color.White, modifier = Modifier.size(30.dp))
                }
                Spacer(Modifier.width(12.dp))
                Column(Modifier.weight(1f)) {
                    Text("Réseau", color = Color.White, fontSize = 24.sp, fontWeight = FontWeight.Bold)
                    Text(e?.url?.removePrefix("https://") ?: "network.mawena.cloud", color = Color.White.copy(alpha = .85f), fontSize = 13.sp)
                }
                val connecte = e?.state == "Running"
                Surface(shape = RoundedCornerShape(50), color = Color.Black.copy(alpha = .22f)) {
                    Row(Modifier.padding(horizontal = 10.dp, vertical = 5.dp), verticalAlignment = Alignment.CenterVertically) {
                        Box(Modifier.size(8.dp).clip(CircleShape).background(if (connecte) Color(0xFF57E389) else Color(0xFFFF7B7B)))
                        Spacer(Modifier.width(6.dp))
                        Text(
                            when { e == null -> "…"; !e.installed -> "Hors réseau"; connecte -> "Connecté"; else -> e.state.ifEmpty { "Arrêté" } },
                            color = Color.White, fontSize = 13.sp, fontWeight = FontWeight.SemiBold,
                        )
                    }
                }
            }
            if (e != null) {
                val b = Reseau.bilan(e)
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Chiffre(Icons.Filled.Hub, "${b.enLigne}/${b.total}", "en ligne", Modifier.weight(1f))
                    Chiffre(Icons.Filled.Home, "${b.lan}", "en local", Modifier.weight(1f))
                    Chiffre(Icons.Filled.Bolt, "${b.direct}", "en direct", Modifier.weight(1f))
                    Chiffre(Icons.Filled.Router, "${b.relais}", "relais", Modifier.weight(1f))
                }
            }
            (erreur ?: e?.error)?.let {
                Surface(shape = RoundedCornerShape(10.dp), color = Color.Black.copy(alpha = .25f)) {
                    Text(it, color = Color.White, modifier = Modifier.padding(10.dp), fontSize = 13.sp)
                }
            }
        }
    }
}

@Composable
private fun Chiffre(icone: ImageVector, valeur: String, libelle: String, modifier: Modifier) {
    Column(modifier.clip(RoundedCornerShape(12.dp)).background(Color.White.copy(alpha = .13f)).padding(10.dp)) {
        Icon(icone, null, tint = Color.White, modifier = Modifier.size(18.dp))
        Text(valeur, color = Color.White, fontSize = 20.sp, fontWeight = FontWeight.Bold)
        Text(libelle, color = Color.White.copy(alpha = .85f), fontSize = 11.sp, maxLines = 1)
    }
}

/** Carte du réseau : le serveur CCS au centre, un trait par liaison coloré selon le chemin. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun Carte(e: EtatReseau) {
    Card(Modifier.fillMaxWidth(), shape = RoundedCornerShape(16.dp)) {
        BoxWithConstraints(Modifier.fillMaxWidth().height(250.dp).padding(8.dp)) {
            val densite = LocalDensity.current
            val l = with(densite) { maxWidth.toPx() }
            val h = with(densite) { maxHeight.toPx() }
            val centre = Offset(l / 2, h / 2 - 10f)
            val n = e.peers.size.coerceAtLeast(1)
            val rx = (l / 2 - with(densite) { 48.dp.toPx() }).coerceAtLeast(60f)
            val ry = h / 2 - with(densite) { 46.dp.toPx() }
            val points = e.peers.mapIndexed { i, a ->
                val ang = -PI / 2 + 2 * PI * i / n
                a to Offset(centre.x + (rx * cos(ang)).toFloat(), centre.y + (ry * sin(ang)).toFloat())
            }
            val tirets = PathEffect.dashPathEffect(floatArrayOf(18f, 12f))
            val points2 = PathEffect.dashPathEffect(floatArrayOf(4f, 14f))
            Canvas(Modifier.matchParentSize()) {
                points.forEach { (a, p) ->
                    val c = Chemin.de(a.path)
                    drawLine(
                        couleur(c), centre, p, strokeWidth = 6f, cap = StrokeCap.Round,
                        pathEffect = when (c) { Chemin.Relais -> tirets; Chemin.Lan, Chemin.Direct -> null; else -> points2 },
                        alpha = if (c == Chemin.HorsLigne || c == Chemin.Veille) .5f else .9f,
                    )
                }
            }
            @Composable
            fun Noeud(a: Appareil, p: Offset, principal: Boolean) {
                val taille = if (principal) 56.dp else 42.dp
                val tx = with(densite) { p.x.toDp() } - 50.dp
                val ty = with(densite) { p.y.toDp() } - taille / 2
                Column(
                    Modifier.offset(tx, ty).width(100.dp).alpha(if (a.online || principal) 1f else .45f),
                    horizontalAlignment = Alignment.CenterHorizontally,
                ) {
                    Surface(
                        shape = CircleShape, shadowElevation = 3.dp,
                        color = if (principal) CouleurIci else MaterialTheme.colorScheme.surface,
                        border = if (principal) null else BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant),
                        modifier = Modifier.size(taille),
                    ) {
                        Box(contentAlignment = Alignment.Center) {
                            Icon(iconeAppareil(a), null, tint = if (principal) Color.White else MaterialTheme.colorScheme.onSurface,
                                modifier = Modifier.size(if (principal) 28.dp else 22.dp))
                        }
                    }
                    Text(a.name, fontSize = 12.sp, fontWeight = FontWeight.SemiBold, maxLines = 1, overflow = TextOverflow.Ellipsis)
                }
            }
            points.forEach { (a, p) -> Noeud(a, p, false) }
            e.ici?.let { Noeud(it, centre, true) }
        }
        FlowRow(Modifier.fillMaxWidth().padding(start = 12.dp, end = 12.dp, bottom = 12.dp), horizontalArrangement = Arrangement.spacedBy(12.dp, Alignment.CenterHorizontally)) {
            listOf(Chemin.Lan, Chemin.Direct, Chemin.Relais, Chemin.HorsLigne).forEach { c ->
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Box(Modifier.width(16.dp).height(3.dp).clip(RoundedCornerShape(2.dp)).background(couleur(c)))
                    Spacer(Modifier.width(5.dp))
                    Text(c.libelle, fontSize = 12.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
        }
    }
}

@Composable
private fun Pastille(c: Chemin) {
    val coul = couleur(c)
    Surface(shape = RoundedCornerShape(50), color = coul.copy(alpha = .15f)) {
        Row(Modifier.padding(horizontal = 8.dp, vertical = 3.dp), verticalAlignment = Alignment.CenterVertically) {
            Icon(iconeChemin(c), null, tint = coul, modifier = Modifier.size(13.dp))
            Spacer(Modifier.width(4.dp))
            Text(c.libelle, fontSize = 12.sp, fontWeight = FontWeight.SemiBold, color = coul)
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun FicheAppareil(
    a: Appareil, ici: Boolean, e: EtatReseau, ping: Ping?,
    /** Machine joignable seulement par Ricochet : ni IP, ni ping, ni renommer/retirer. */
    sansMaille: Boolean, nomMachine: String?,
    calcul: (@Composable () -> Unit)?,
    lancerPing: () -> Unit, renommer: () -> Unit, retirer: () -> Unit,
) {
    val presse = LocalClipboardManager.current
    val avis = LocalAvis.current
    val c = Chemin.de(a.path)
    val coul = couleur(c)
    Card(
        Modifier.fillMaxWidth().alpha(if (a.online || ici) 1f else .7f),
        shape = RoundedCornerShape(16.dp),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceContainerLow),
    ) {
        Row(Modifier.height(IntrinsicSize.Min)) {
            Box(Modifier.width(4.dp).fillMaxHeight().background(coul))
            Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Box(
                        Modifier.size(44.dp).clip(RoundedCornerShape(13.dp))
                            .background(Brush.linearGradient(listOf(coul.copy(alpha = .85f), coul))),
                        contentAlignment = Alignment.Center,
                    ) { Icon(iconeAppareil(a), null, tint = Color.White) }
                    Spacer(Modifier.width(12.dp))
                    Column(Modifier.weight(1f)) {
                        Text(a.name, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold, maxLines = 1, overflow = TextOverflow.Ellipsis)
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Pastille(c)
                            val detail = listOfNotNull(
                                a.os.ifEmpty { null },
                                a.host.takeIf { it.isNotEmpty() && it != a.name && !sansMaille },
                                nomMachine?.takeIf { it != a.name },
                            ).joinToString(" · ")
                            if (detail.isNotEmpty()) {
                                Spacer(Modifier.width(6.dp))
                                Text(detail, fontSize = 12.sp, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1, overflow = TextOverflow.Ellipsis)
                            }
                        }
                    }
                }
                val ip = a.ips.firstOrNull().orEmpty()
                if (!sansMaille) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(ip.ifEmpty { "—" }, fontFamily = FontFamily.Monospace, fontWeight = FontWeight.SemiBold)
                        if (ip.isNotEmpty()) IconButton(onClick = { presse.setText(AnnotatedString(ip)); avis.dire("Copié.") }, modifier = Modifier.size(32.dp)) {
                            Icon(Icons.Filled.ContentCopy, "Copier l'adresse", modifier = Modifier.size(16.dp))
                        }
                    }
                    Text("${a.name}.${e.domain}", fontFamily = FontFamily.Monospace, fontSize = 11.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                if (a.endpoint.isNotEmpty() && !ici) Row(verticalAlignment = Alignment.CenterVertically) {
                    Icon(Icons.Filled.SwapHoriz, null, modifier = Modifier.size(14.dp), tint = MaterialTheme.colorScheme.onSurfaceVariant)
                    Spacer(Modifier.width(4.dp))
                    Text(a.endpoint, fontSize = 12.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                val adresses = Reseau.adressesPubliees(a)
                if (adresses.isNotEmpty()) FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    adresses.forEach { ad ->
                        val ca = when (ad.sorte) { Reseau.SorteAdresse.Locale -> CouleurLan; Reseau.SorteAdresse.Publique -> CouleurDirect; else -> CouleurIci }
                        Surface(shape = RoundedCornerShape(8.dp), color = MaterialTheme.colorScheme.surfaceContainerHighest) {
                            Row(Modifier.padding(end = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                                Surface(shape = RoundedCornerShape(6.dp), color = ca, modifier = Modifier.padding(2.dp)) {
                                    Text(ad.sorte.libelle, color = Color.White, fontSize = 10.sp, fontWeight = FontWeight.Bold, modifier = Modifier.padding(horizontal = 5.dp, vertical = 1.dp))
                                }
                                Spacer(Modifier.width(4.dp))
                                Text(ad.ip, fontFamily = FontFamily.Monospace, fontSize = 11.sp)
                            }
                        }
                    }
                }
                if (a.rx > 0 || a.tx > 0) Text("↓ ${Reseau.octets(a.rx)} · ↑ ${Reseau.octets(a.tx)}", fontSize = 12.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
                ping?.let { p ->
                    val cp = if (p.ok) couleur(Chemin.de(p.path)) else MaterialTheme.colorScheme.error
                    Surface(shape = RoundedCornerShape(10.dp), color = MaterialTheme.colorScheme.surfaceContainerHighest) {
                        Row(Modifier.padding(horizontal = 10.dp, vertical = 6.dp), verticalAlignment = Alignment.CenterVertically) {
                            Icon(Icons.Filled.NetworkPing, null, tint = cp, modifier = Modifier.size(15.dp))
                            Spacer(Modifier.width(6.dp))
                            Text(
                                if (p.ok) "${"%.0f".format(p.ms)} ms · ${Chemin.de(p.path).libelle} · ${p.via}" else p.error ?: "pas de réponse",
                                fontSize = 12.sp,
                            )
                        }
                    }
                }
                calcul?.invoke()
                if (!sansMaille) Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                    if (!ici && a.online) TextButton(onClick = lancerPing) { Icon(Icons.Filled.NetworkPing, null, Modifier.size(16.dp)); Spacer(Modifier.width(4.dp)); Text("Ping") }
                    if (e.server) {
                        TextButton(onClick = renommer) { Icon(Icons.Filled.Edit, null, Modifier.size(16.dp)); Spacer(Modifier.width(4.dp)); Text("Renommer") }
                        if (!ici) TextButton(onClick = retirer) {
                            Icon(Icons.Filled.Delete, null, Modifier.size(16.dp), tint = MaterialTheme.colorScheme.error)
                            Spacer(Modifier.width(4.dp))
                            Text("Retirer", color = MaterialTheme.colorScheme.error)
                        }
                    }
                }
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun AjoutAppareil(
    e: EtatReseau,
    /** Relais, jeton et jeton opérateur Ricochet réglés : le PC s'ajoute par `machines.add`. */
    ricochet: Boolean,
    ajouterPc: suspend (id: String, compte: String, nom: String, complet: Boolean) -> PcAjoute?,
    creerCle: suspend (String) -> CleReseau?, valider: suspend (String) -> Boolean,
) {
    val presse = LocalClipboardManager.current
    val avis = LocalAvis.current
    val portee = rememberCoroutineScope()
    var onglet by remember { mutableStateOf(0) }
    Card(Modifier.fillMaxWidth(), shape = RoundedCornerShape(16.dp)) {
        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(Icons.Filled.Add, null)
                Spacer(Modifier.width(8.dp))
                Text("Ajouter un appareil", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
            }
            val choix = listOf("PC Linux" to Icons.Filled.Computer, "Android" to Icons.Filled.PhoneAndroid, "iPhone" to Icons.Filled.PhoneIphone)
            SingleChoiceSegmentedButtonRow(Modifier.fillMaxWidth()) {
                choix.forEachIndexed { i, (nom, ic) ->
                    SegmentedButton(
                        selected = onglet == i, onClick = { onglet = i },
                        shape = SegmentedButtonDefaults.itemShape(i, choix.size),
                        icon = { Icon(ic, null, Modifier.size(16.dp)) },
                    ) { Text(nom, maxLines = 1) }
                }
            }
            if (onglet == 0 && ricochet) {
                AjoutPcRicochet(ajouterPc)
            } else if (onglet == 0) {
                var nom by remember { mutableStateOf("") }
                var ligne by remember { mutableStateOf<String?>(null) }
                Etapes(listOf("Choisis un nom pour la machine, puis crée la ligne.", "Colle-la dans un terminal du PC : elle installe le client et l'inscrit.", "Il apparaît ici en quelques secondes."))
                OutlinedTextField(nom, { nom = it.trim().lowercase() }, singleLine = true, label = { Text("Nom (facultatif)") },
                    placeholder = { Text("lp-home") }, isError = nom.isNotEmpty() && !Reseau.nomValide(nom),
                    keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.None), modifier = Modifier.fillMaxWidth())
                FilledTonalButton(enabled = nom.isEmpty() || Reseau.nomValide(nom), onClick = {
                    portee.launch { creerCle(nom)?.let { ligne = Reseau.ligneLinux(it.linux) } }
                }) { Icon(Icons.Filled.Key, null, Modifier.size(16.dp)); Spacer(Modifier.width(6.dp)); Text("Créer la ligne d'inscription") }
                ligne?.let { l ->
                    Text("Clé valable 15 min, pour une seule machine :", fontSize = 12.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    Surface(shape = RoundedCornerShape(10.dp), color = Color(0xFF1E1E22)) {
                        Row(Modifier.padding(10.dp), verticalAlignment = Alignment.Top) {
                            Text(l, color = Color(0xFFE6E6EA), fontFamily = FontFamily.Monospace, fontSize = 11.sp, modifier = Modifier.weight(1f))
                            IconButton(onClick = { presse.setText(AnnotatedString(l)); avis.dire("Copié.") }) {
                                Icon(Icons.Filled.ContentCopy, "Copier", tint = Color(0xFFE6E6EA))
                            }
                        }
                    }
                }
            } else {
                val iphone = onglet == 2
                var cle by remember { mutableStateOf("") }
                Etapes(listOf(
                    "Installe l'appli Tailscale (${if (iphone) "App Store" else "Play Store"}).",
                    if (iphone) "Réglages de l'appli → Comptes → « Utiliser un serveur personnalisé » : ${e.url}"
                    else "Écran de connexion → menu ⋮ → « Changer de serveur » : ${e.url}",
                    "Connecte-toi : une page affiche une clé « hskey-authreq-… ». Colle-la ici.",
                ))
                TextButton(onClick = { presse.setText(AnnotatedString(e.url)); avis.dire("Adresse du serveur copiée.") }) {
                    Icon(Icons.Filled.ContentCopy, null, Modifier.size(16.dp)); Spacer(Modifier.width(6.dp)); Text(e.url, fontFamily = FontFamily.Monospace)
                }
                OutlinedTextField(cle, { cle = it.trim() }, singleLine = true, label = { Text("Clé ou lien affiché") },
                    keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.None), modifier = Modifier.fillMaxWidth())
                FilledTonalButton(enabled = cle.length >= 8, onClick = { portee.launch { if (valider(cle)) cle = "" } }) {
                    Icon(Icons.Filled.CheckCircle, null, Modifier.size(16.dp)); Spacer(Modifier.width(6.dp)); Text("Valider l'appareil")
                }
            }
        }
    }
}

@Composable
private fun Etapes(lignes: List<String>) {
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        lignes.forEachIndexed { i, t ->
            Row(verticalAlignment = Alignment.CenterVertically) {
                Box(Modifier.size(24.dp).clip(CircleShape).background(MaterialTheme.colorScheme.primary), contentAlignment = Alignment.Center) {
                    Text("${i + 1}", color = MaterialTheme.colorScheme.onPrimary, fontSize = 12.sp, fontWeight = FontWeight.Bold)
                }
                Spacer(Modifier.width(10.dp))
                Text(t, fontSize = 14.sp)
            }
        }
    }
}
