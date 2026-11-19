package com.mawena.ccs.ui.git

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.AccountTree
import androidx.compose.material3.Icon
import androidx.compose.material3.ListItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.mawena.ccs.logique.Format
import com.mawena.ccs.logique.GitVue
import com.mawena.ccs.reseau.DetailCommit
import com.mawena.ccs.reseau.EtatConnexion
import com.mawena.ccs.reseau.ListeProjets
import com.mawena.ccs.ui.BarreHaut
import com.mawena.ccs.ui.Chargement
import com.mawena.ccs.ui.EtatErreur
import com.mawena.ccs.ui.EtatVide
import com.mawena.ccs.ui.ModeleAppli
import com.mawena.ccs.ui.TitreSection
import com.mawena.ccs.ui.chat.CorpsDiff
import com.mawena.ccs.ui.texte
import kotlinx.coroutines.launch
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

/** Onglet Git : choisir un projet de CCS, puis son dépôt. */
@Composable
fun EcranGitOnglet(modele: ModeleAppli, ouvrirGit: (String) -> Unit) {
    val etat by modele.etat.collectAsStateWithLifecycle()
    val connecte = etat is EtatConnexion.Connecte
    val portee = rememberCoroutineScope()
    var liste by remember { mutableStateOf<ListeProjets?>(null) }
    var erreur by remember { mutableStateOf<String?>(null) }
    suspend fun charger() {
        try {
            liste = modele.depot.client.appeler("projects.list", ListeProjets.serializer())
            erreur = null
        } catch (e: Exception) {
            erreur = e.texte()
        }
    }
    LaunchedEffect(connecte) { if (connecte) charger() }
    Column(Modifier.fillMaxSize()) {
        BarreHaut("Git", "Choisis un projet")
        val l = liste
        when {
            l == null && erreur != null -> EtatErreur(erreur!!) { portee.launch { charger() } }
            l == null -> Chargement()
            l.projets.isEmpty() -> EtatVide("Aucun projet : ajoute-en un depuis Sessions ou Fichiers.")
            else -> LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(bottom = 24.dp)) {
                items(l.projets.filter { it.exists }, key = { it.cwd!! }) { p ->
                    ListItem(
                        headlineContent = { Text(p.name.ifBlank { Format.base(p.cwd) }) },
                        supportingContent = { Text(p.cwd!!, maxLines = 1, overflow = TextOverflow.Ellipsis) },
                        leadingContent = { Icon(Icons.Filled.AccountTree, null, tint = MaterialTheme.colorScheme.primary) },
                        modifier = Modifier.clickable { ouvrirGit(p.cwd!!) },
                    )
                }
            }
        }
    }
}

/** Git d'un projet en plein écran (depuis l'onglet Git ou le chat). */
@Composable
fun EcranGitProjet(modele: ModeleAppli, cwd: String, retour: () -> Unit, ouvrirCommit: (String) -> Unit) {
    Column(Modifier.fillMaxSize()) {
        BarreHaut("Git", Format.base(cwd), retour = retour)
        PanneauGit(modele, cwd, ouvrirCommit)
    }
}

/** Détail d'un commit (`git.show`) : message entier, auteur, date, diff de chaque fichier. */
@Composable
fun EcranCommit(modele: ModeleAppli, cwd: String, id: String, retour: () -> Unit) {
    val etat by modele.etat.collectAsStateWithLifecycle()
    val connecte = etat is EtatConnexion.Connecte
    val portee = rememberCoroutineScope()
    var detail by remember { mutableStateOf<DetailCommit?>(null) }
    var erreur by remember { mutableStateOf<String?>(null) }
    var ouverts by remember { mutableStateOf<Set<String>>(emptySet()) }
    suspend fun charger() {
        try {
            val d = modele.depot.client.appeler("git.show", DetailCommit.serializer(), buildJsonObject { put("cwd", cwd); put("id", id) })
            detail = d
            if (d.files.size <= 3) ouverts = d.files.map { it.path }.toSet()
            erreur = null
        } catch (e: Exception) {
            erreur = e.texte()
        }
    }
    LaunchedEffect(connecte) { if (connecte && detail == null) charger() }
    Column(Modifier.fillMaxSize()) {
        BarreHaut(detail?.commit?.subject ?: "Commit", id.take(8), retour = retour)
        val d = detail
        when {
            d == null && erreur != null -> EtatErreur(erreur!!) { portee.launch { charger() } }
            d == null -> Chargement()
            else -> LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(bottom = 24.dp)) {
                item {
                    SelectionContainer {
                        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                            Text(d.commit.subject, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
                            if (d.commit.body.isNotBlank()) Text(d.commit.body.trim(), style = MaterialTheme.typography.bodyMedium)
                            Text("${d.commit.author} <${d.commit.email}> · ${Format.ilYA(d.commit.time.toDouble())}",
                                style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                            Text(d.commit.id, fontFamily = FontFamily.Monospace, style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                    }
                }
                item { TitreSection("Fichiers (${d.files.size})", Modifier.padding(horizontal = 16.dp)) }
                items(d.files, key = { it.path }) { f ->
                    val fichier = remember(f) { GitVue.fichier(f) }
                    Column(Modifier.fillMaxWidth()) {
                        Row(
                            Modifier.fillMaxWidth().clickable { ouverts = if (f.path in ouverts) ouverts - f.path else ouverts + f.path }
                                .padding(horizontal = 16.dp, vertical = 8.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Column(Modifier.weight(1f)) {
                                Text(f.path, maxLines = 2, overflow = TextOverflow.Ellipsis)
                                Text(GitVue.etatFichier(f), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                            }
                            Text("+${fichier.ajouts} −${fichier.retraits}", style = MaterialTheme.typography.labelMedium, fontFamily = FontFamily.Monospace)
                        }
                        if (f.path in ouverts) {
                            val vide = GitVue.sansDiff(f)
                            Column(Modifier.padding(horizontal = 12.dp)) {
                                if (vide != null) Text(vide, style = MaterialTheme.typography.bodySmall)
                                else CorpsDiff(fichier.lignes, max = 200)
                                if (f.truncated) Text("Diff tronqué.", style = MaterialTheme.typography.bodySmall)
                            }
                        }
                    }
                }
                if (d.truncated) item { EtatVide("Trop de fichiers : seuls les premiers sont montrés.") }
            }
        }
    }
}
