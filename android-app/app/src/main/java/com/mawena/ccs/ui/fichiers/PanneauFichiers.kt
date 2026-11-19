package com.mawena.ccs.ui.fichiers

import android.net.Uri
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.ContentCut
import androidx.compose.material.icons.filled.ContentCopy
import androidx.compose.material.icons.filled.ContentPaste
import androidx.compose.material.icons.filled.CreateNewFolder
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Download
import androidx.compose.material.icons.filled.DriveFileRenameOutline
import androidx.compose.material.icons.filled.FolderOpen
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material.icons.filled.NoteAdd
import androidx.compose.material.icons.filled.PlaylistAdd
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.Share
import androidx.compose.material.icons.filled.Upload
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.ListItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
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
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.mawena.ccs.logique.Fichiers
import com.mawena.ccs.reseau.CheminRendu
import com.mawena.ccs.reseau.EntreeFichier
import com.mawena.ccs.reseau.EtatConnexion
import com.mawena.ccs.reseau.InfoFichier
import com.mawena.ccs.reseau.ListeFichiers
import com.mawena.ccs.reseau.ProjetAjoute
import com.mawena.ccs.reseau.RpcException
import com.mawena.ccs.ui.Chargement
import com.mawena.ccs.ui.Demandes
import com.mawena.ccs.ui.EtatErreur
import com.mawena.ccs.ui.EtatVide
import com.mawena.ccs.ui.LocalAvis
import com.mawena.ccs.ui.ModeleAppli
import com.mawena.ccs.ui.VueDemandes
import com.mawena.ccs.ui.texte
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

/**
 * Volet Fichiers (`web/files.js`, `files-manage.js`) : un dossier à la fois sous `base` (retour :
 * dossier parent), marques git, recherche par nom, créer, envoyer depuis le sélecteur d'Android,
 * télécharger, partager, renommer, supprimer (confirmé), copier / couper / coller.
 * `protege` : dossier à ne jamais renommer ni supprimer d'ici (le projet), passé au pont en `root`.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun PanneauFichiers(
    modele: ModeleAppli,
    base: String,
    ouvrirFichier: (String) -> Unit,
    modifier: Modifier = Modifier,
    home: String = "",
    protege: String? = base,
    entete: @Composable () -> Unit = {},
) {
    val client = modele.depot.client
    val etat by modele.etat.collectAsStateWithLifecycle()
    val connecte = etat is EtatConnexion.Connecte
    val avis = LocalAvis.current
    val contexte = LocalContext.current
    val portee = rememberCoroutineScope()
    val demandes = remember { Demandes() }

    var dossier by rememberSaveable(base) { mutableStateOf(base) }
    var liste by remember(base) { mutableStateOf<ListeFichiers?>(null) }
    var erreur by remember { mutableStateOf<String?>(null) }
    var charge by remember { mutableStateOf(false) }
    var recherche by rememberSaveable { mutableStateOf<String?>(null) }
    var trouves by remember { mutableStateOf<ListeFichiers?>(null) }
    var menuDossier by remember { mutableStateOf(false) }
    var choisie by remember { mutableStateOf<EntreeFichier?>(null) }   // chemin `path` absolu
    var travail by remember { mutableStateOf<String?>(null) }
    var progres by remember { mutableStateOf<Float?>(null) }

    BackHandler(enabled = recherche != null) { recherche = null }
    BackHandler(enabled = recherche == null && dossier != base && Fichiers.sous(dossier, base)) { dossier = Fichiers.parent(dossier) }

    suspend fun charger() {
        charge = true
        try {
            liste = client.appeler("files.list", ListeFichiers.serializer(), buildJsonObject {
                put("root", base); put("rel", Fichiers.relatif(dossier, base).orEmpty())
            })
            erreur = null
        } catch (e: Exception) {
            erreur = e.texte()
        }
        charge = false
    }

    LaunchedEffect(connecte, dossier, base) {
        if (connecte) { liste = null; charger() }
    }

    val q = recherche?.trim().orEmpty()
    LaunchedEffect(q, dossier, connecte) {
        trouves = null
        if (q.isEmpty() || !connecte) return@LaunchedEffect
        delay(300)
        trouves = runCatching {
            client.appeler("files.search", ListeFichiers.serializer(), buildJsonObject { put("root", dossier); put("query", q) })
        }.getOrElse { avis.dire(it.texte()); ListeFichiers() }
    }

    /** Lance une action (une à la fois) ; recharge le dossier si `recharger`. */
    fun agir(libelle: String, recharger: Boolean = true, action: suspend () -> Unit) {
        if (travail != null) return
        portee.launch {
            travail = libelle
            progres = null
            try {
                action()
            } catch (e: Exception) {
                avis.dire(e.texte())
            } finally {
                travail = null
                progres = null
            }
            if (recharger) charger()
        }
    }

    fun progresDe(recu: Long, total: Long) { progres = if (total > 0) (recu.toFloat() / total).coerceIn(0f, 1f) else null }

    fun creer(dossierCible: String, repertoire: Boolean) = agir(if (repertoire) "Création du dossier…" else "Création du fichier…") {
        val nom = demandes.nom(if (repertoire) "Nouveau dossier" else "Nouveau fichier", bouton = "Créer", verifier = Fichiers::nomRefuse)
            ?: return@agir
        val r = client.appeler(if (repertoire) "files.mkdir" else "files.create", CheminRendu.serializer(), buildJsonObject {
            put("dir", dossierCible); put("name", nom)
        })
        if (!repertoire) ouvrirFichier(r.path)
    }

    val choisir = rememberLauncherForActivityResult(ActivityResultContracts.OpenMultipleDocuments()) { uris: List<Uri> ->
        if (uris.isEmpty()) return@rememberLauncherForActivityResult
        val cible = dossier
        agir("Envoi…") {
            for (uri in uris) {
                val f = Transferts.decrire(contexte, uri)
                travail = "Envoi de « ${f.nom} »…"
                try {
                    Transferts.envoyer(contexte, client, cible, f, false, ::progresDe)
                } catch (e: RpcException) {
                    if (e.code != "existe") throw e
                    if (!demandes.confirmer("Remplacer « ${f.nom} » ?", "Un fichier de ce nom existe déjà dans ce dossier.", "Remplacer", danger = true)) continue
                    Transferts.envoyer(contexte, client, cible, f, true, ::progresDe)
                }
                avis.dire("« ${f.nom} » envoyé" + (if (f.taille >= 0) " (${Fichiers.taille(f.taille)})." else "."))
            }
        }
    }

    fun coller(cible: String) {
        val t = Presse.tenu ?: return
        agir(if (t.deplacer) "Déplacement…" else "Copie…") {
            client.appeler("files.paste", buildJsonObject {
                put("path", t.chemin); put("dir", cible); put("mode", if (t.deplacer) "move" else "copy")
                protege?.let { put("root", it) }
            }, delaiMs = 300_000)
            if (t.deplacer) Presse.tenu = null
            avis.dire("« ${t.nom} » ${if (t.deplacer) "déplacé" else "copié"}.")
        }
    }

    fun telecharger(chemin: String) = agir("Téléchargement de « ${Fichiers.nom(chemin)} »…", recharger = false) {
        val nom = Transferts.versTelechargements(contexte, client, chemin, ::progresDe)
        avis.dire("« $nom » enregistré dans Téléchargements.")
    }

    fun partager(chemin: String) = agir("Préparation du partage…", recharger = false) {
        Transferts.partager(contexte, client, chemin, ::progresDe)
    }

    fun renommer(e: EntreeFichier) = agir("Renommage…") {
        val nom = demandes.nom("Renommer « ${e.name} »", e.name, "Renommer", Fichiers::nomRefuse) ?: return@agir
        if (nom == e.name) return@agir
        client.appeler("files.rename", buildJsonObject { put("path", e.path); put("name", nom); protege?.let { put("root", it) } })
    }

    fun supprimer(e: EntreeFichier) = agir("Suppression…") {
        val info = client.appeler("files.info", InfoFichier.serializer(), buildJsonObject { put("path", e.path) })
        if (!demandes.confirmer("Supprimer « ${e.name} » ?", Fichiers.texteSuppression(info.dir, info.count, info.size), "Supprimer", danger = true)) return@agir
        client.appeler("files.delete", buildJsonObject { put("path", e.path); protege?.let { put("root", it) } }, delaiMs = 120_000)
        avis.dire("« ${e.name} » supprimé.")
    }

    fun ajouterProjet(chemin: String) = agir("Ajout aux projets…", recharger = false) {
        val r = client.appeler("projects.add", ProjetAjoute.serializer(), buildJsonObject { put("cwd", chemin) })
        avis.dire("« ${Fichiers.nom(r.cwd.ifEmpty { chemin })} » ajouté aux projets.")
    }

    Column(modifier.fillMaxSize()) {
        entete()
        // fil d'Ariane et actions du dossier
        Row(Modifier.fillMaxWidth().padding(start = 8.dp), verticalAlignment = Alignment.CenterVertically) {
            val defile = rememberScrollState()
            LaunchedEffect(dossier) { defile.scrollTo(defile.maxValue) }
            Row(Modifier.weight(1f).horizontalScroll(defile), verticalAlignment = Alignment.CenterVertically) {
                val fil = Fichiers.ariane(dossier, base, home)
                fil.forEachIndexed { i, (nom, chemin) ->
                    if (i > 0) Icon(Icons.AutoMirrored.Filled.KeyboardArrowRight, null, Modifier.size(16.dp), tint = MaterialTheme.colorScheme.onSurfaceVariant)
                    if (i == fil.size - 1) Text(nom, Modifier.padding(horizontal = 6.dp), fontWeight = FontWeight.SemiBold, maxLines = 1)
                    else TextButton(onClick = { dossier = chemin }) { Text(if (i == 0 && nom.length > 24) Fichiers.nom(nom) else nom, maxLines = 1) }
                }
            }
            IconButton(onClick = { recherche = if (recherche == null) "" else null }) {
                Icon(if (recherche == null) Icons.Filled.Search else Icons.Filled.Close, "Chercher un fichier")
            }
            Box {
                IconButton(onClick = { menuDossier = true }) { Icon(Icons.Filled.MoreVert, "Actions sur ce dossier") }
                DropdownMenu(menuDossier, { menuDossier = false }) {
                    fun item(t: String, i: ImageVector, f: () -> Unit) = @Composable {
                        DropdownMenuItem(text = { Text(t) }, leadingIcon = { Icon(i, null) }, onClick = { menuDossier = false; f() })
                    }
                    item("Nouveau fichier", Icons.Filled.NoteAdd) { creer(dossier, false) }()
                    item("Nouveau dossier", Icons.Filled.CreateNewFolder) { creer(dossier, true) }()
                    item("Envoyer des fichiers ici", Icons.Filled.Upload) { choisir.launch(arrayOf("*/*")) }()
                    Presse.tenu?.let { t -> item("Coller « ${t.nom} »", Icons.Filled.ContentPaste) { coller(dossier) }() }
                    item("Ajouter aux projets", Icons.Filled.PlaylistAdd) { ajouterProjet(dossier) }()
                    item("Actualiser", Icons.Filled.Refresh) { portee.launch { charger() } }()
                }
            }
        }
        recherche?.let { r ->
            OutlinedTextField(
                r, { recherche = it }, Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 4.dp),
                singleLine = true, placeholder = { Text("Chercher par nom dans ${Fichiers.nom(dossier)}") },
                leadingIcon = { Icon(Icons.Filled.Search, null) },
            )
        }
        travail?.let { t ->
            Column(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 4.dp)) {
                Text(t, style = MaterialTheme.typography.bodySmall)
                val p = progres
                if (p != null) LinearProgressIndicator(progress = { p }, Modifier.fillMaxWidth()) else LinearProgressIndicator(Modifier.fillMaxWidth())
            }
        }
        HorizontalDivider()

        if (q.isNotEmpty()) {
            val t = trouves
            LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(bottom = 24.dp)) {
                when {
                    t == null -> item { Chargement("Recherche…") }
                    t.entries.isEmpty() -> item { EtatVide("Aucun fichier nommé « $q ».") }
                    else -> {
                        items(t.entries, key = { "t:" + it.path }) { e ->
                            val abs = Fichiers.joindre(dossier, e.path)
                            LigneEntree(e.copy(path = abs), sousTitre = Fichiers.parent(e.path).takeIf { '/' in e.path },
                                surToucher = { if (e.dir) { recherche = null; dossier = abs } else ouvrirFichier(abs) },
                                surMenu = { choisie = e.copy(path = abs) })
                        }
                        if (t.truncated) item { EtatVide("Trop de résultats : précise ta recherche.") }
                    }
                }
            }
        } else {
            PullToRefreshBox(isRefreshing = charge && liste != null, onRefresh = { portee.launch { charger() } }, modifier = Modifier.fillMaxSize()) {
                val l = liste
                LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(bottom = 24.dp)) {
                    when {
                        l == null && erreur != null -> item { EtatErreur(erreur!!) { portee.launch { charger() } } }
                        l == null -> item { Chargement() }
                        l.entries.isEmpty() -> item {
                            EtatVide("Ce dossier est vide.") {
                                TextButton(onClick = { menuDossier = true }) { Text("Créer ou envoyer un fichier") }
                            }
                        }
                        else -> {
                            items(l.entries, key = { it.path }) { e ->
                                val abs = Fichiers.joindre(base, e.path)
                                LigneEntree(e.copy(path = abs),
                                    surToucher = { if (e.dir) dossier = abs else ouvrirFichier(abs) },
                                    surMenu = { choisie = e.copy(path = abs) })
                            }
                            if (l.truncated) item { EtatVide("(dossier trop long : liste coupée)") }
                        }
                    }
                }
            }
        }
    }

    choisie?.let { e ->
        ModalBottomSheet(onDismissRequest = { choisie = null }) {
            Text(e.name, Modifier.padding(horizontal = 24.dp, vertical = 8.dp), style = MaterialTheme.typography.titleMedium,
                maxLines = 2, overflow = TextOverflow.Ellipsis)
            fun action(t: String, i: ImageVector, danger: Boolean = false, f: () -> Unit) = @Composable {
                ListItem(
                    headlineContent = { Text(t, color = if (danger) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSurface) },
                    leadingContent = { Icon(i, null, tint = if (danger) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSurfaceVariant) },
                    modifier = Modifier.clickable { choisie = null; f() },
                )
            }
            Column(Modifier.padding(bottom = 24.dp)) {
                if (e.dir) {
                    action("Ouvrir", Icons.Filled.FolderOpen) { recherche = null; dossier = e.path }()
                    Presse.tenu?.let { t -> action("Coller « ${t.nom} » ici", Icons.Filled.ContentPaste) { coller(e.path) }() }
                    action("Ajouter aux projets", Icons.Filled.PlaylistAdd) { ajouterProjet(e.path) }()
                } else {
                    action("Ouvrir", Icons.Filled.FolderOpen) { ouvrirFichier(e.path) }()
                    action("Télécharger", Icons.Filled.Download) { telecharger(e.path) }()
                    action("Partager", Icons.Filled.Share) { partager(e.path) }()
                }
                action("Copier", Icons.Filled.ContentCopy) {
                    Presse.tenu = Presse.Tenu(e.path, e.name, false)
                    avis.dire("« ${e.name} » copié : « Coller » dans le menu d'un dossier.")
                }()
                action("Couper", Icons.Filled.ContentCut) {
                    Presse.tenu = Presse.Tenu(e.path, e.name, true)
                    avis.dire("« ${e.name} » coupé : « Coller » dans le menu d'un dossier.")
                }()
                action("Renommer", Icons.Filled.DriveFileRenameOutline) { renommer(e) }()
                action("Supprimer", Icons.Filled.Delete, danger = true) { supprimer(e) }()
            }
        }
    }
    VueDemandes(demandes)
}

@Composable
private fun LigneEntree(e: EntreeFichier, sousTitre: String? = null, surToucher: () -> Unit, surMenu: () -> Unit) {
    val g = Fichiers.genre(e.name, e.dir)
    ListItem(
        headlineContent = { Text(e.name, maxLines = 1, overflow = TextOverflow.Ellipsis) },
        supportingContent = sousTitre?.let { { Text(it, maxLines = 1, overflow = TextOverflow.Ellipsis) } },
        leadingContent = { Icon(icone(g), null, tint = teinte(g)) },
        trailingContent = {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                if (e.mark.isNotEmpty()) Text(e.mark, color = couleurMarque(e.mark), fontWeight = FontWeight.Bold,
                    style = MaterialTheme.typography.labelLarge)
                IconButton(onClick = surMenu) { Icon(Icons.Filled.MoreVert, "Actions sur ${e.name}") }
            }
        },
        modifier = Modifier.clickable(onClick = surToucher),
    )
}
