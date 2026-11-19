package com.mawena.ccs.ui

import android.net.Uri
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.AddComment
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.ListItem
import androidx.compose.material3.ListItemDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.mawena.ccs.Remise
import com.mawena.ccs.logique.AnalysePartage
import com.mawena.ccs.logique.EtatChat
import com.mawena.ccs.logique.Format
import com.mawena.ccs.logique.Partage
import com.mawena.ccs.reseau.ChatOuvert
import com.mawena.ccs.reseau.EtatConnexion
import com.mawena.ccs.reseau.ListeChats
import com.mawena.ccs.reseau.ListeProjets
import com.mawena.ccs.reseau.RpcException
import com.mawena.ccs.ui.chat.lireImage
import com.mawena.ccs.ui.fichiers.Transferts
import kotlinx.coroutines.launch
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

/**
 * Partage Android vers CCS : choisir un chat en cours ou un nouveau chat (dossier). Les autres
 * fichiers partent d'abord dans le dossier du projet (`files.upload`, sans rien écraser), puis le
 * chat s'ouvre avec le texte et les fichiers cités dans la saisie, les images en pièces jointes.
 * Rien n'est envoyé à Claude : on relit et on envoie soi-même.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun FeuillePartage(modele: ModeleAppli, p: Partage, fermer: () -> Unit, ouvrir: (DestChat) -> Unit) {
    val client = modele.depot.client
    val ctx = LocalContext.current
    val avis = LocalAvis.current
    val portee = rememberCoroutineScope()
    val etat by modele.etat.collectAsStateWithLifecycle()
    val feuille = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    var chats by remember { mutableStateOf<List<ChatOuvert>?>(null) }
    var connus by remember { mutableStateOf<List<String>>(emptyList()) }
    var erreur by remember { mutableStateOf<String?>(null) }
    var progres by remember { mutableStateOf<String?>(null) }
    var nouvelle by remember { mutableStateOf(false) }
    val connecte = etat is EtatConnexion.Connecte

    LaunchedEffect(connecte) {
        if (!connecte) return@LaunchedEffect
        try {
            chats = client.appeler("chat.list", ListeChats.serializer()).chats
            erreur = null
        } catch (e: Exception) {
            erreur = e.texte()
        }
        runCatching { client.appeler("projects.list", ListeProjets.serializer(), buildJsonObject { put("query", "") }) }
            .onSuccess { l -> connus = l.projets.filter { it.exists }.mapNotNull { it.cwd } }
    }

    /** Envoie le fichier dans `dossier` sans rien écraser : « nom (2).ext » si le nom est pris ; rend le nom gardé. */
    suspend fun envoyerSansEcraser(f: Transferts.Choisi, dossier: String): String {
        for (essai in 1..MAX_ESSAIS_NOM) {
            val nom = AnalysePartage.nomLibre(f.nom, essai)
            try {
                Transferts.envoyer(ctx, client, dossier, f.copy(nom = nom), remplacer = false)
                return nom
            } catch (e: RpcException) {
                if (e.code != "existe") throw e
            }
        }
        error("« ${f.nom} » : trop de fichiers du même nom dans le dossier.")
    }

    fun livrer(c: ChatOuvert, repli: String) {
        val cwd = c.cwd.ifEmpty { repli }
        portee.launch {
            erreur = null
            try {
                val envoyes = ArrayList<String>()
                p.fichiers.forEachIndexed { k, u ->
                    val f = Transferts.decrire(ctx, Uri.parse(u))
                    progres = "Envoi de « ${f.nom} »" + (if (p.fichiers.size > 1) " (${k + 1}/${p.fichiers.size})" else "") + "…"
                    envoyes += envoyerSansEcraser(f, cwd)
                }
                progres = if (p.images.isNotEmpty()) "Préparation des images…" else progres
                val images = p.images.mapNotNull { lireImage(ctx, Uri.parse(it)) }
                val perdues = p.images.size - images.size
                modele.depot.remettre(c.chatId, Remise(AnalysePartage.composer("", p.texte, envoyes), images))
                if (perdues > 0) avis.dire(if (perdues == 1) "Une image illisible ou trop lourde n'a pas été jointe." else "$perdues images illisibles ou trop lourdes n'ont pas été jointes.")
                progres = null
                ouvrir(DestChat(cwd, c.sessionId, c.path, Format.base(cwd), c.chatId))
            } catch (e: Exception) {
                progres = null
                erreur = e.texte()
            }
        }
    }

    ModalBottomSheet(onDismissRequest = { if (progres == null) fermer() }, sheetState = feuille) {
        Column(Modifier.fillMaxWidth().padding(bottom = 24.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Column(Modifier.padding(horizontal = 20.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text("Partager vers CCS", style = MaterialTheme.typography.titleLarge)
                Text(
                    p.resume() + (if (p.fichiers.isNotEmpty()) " · les fichiers iront dans le dossier du projet" else "") +
                        ". Tu relis avant d'envoyer.",
                    style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                if (p.texte.isNotBlank()) {
                    Text(p.texte, maxLines = 3, overflow = TextOverflow.Ellipsis, style = MaterialTheme.typography.bodyMedium)
                }
            }
            val pr = progres
            if (pr != null) {
                Row(Modifier.padding(horizontal = 20.dp, vertical = 12.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    CircularProgressIndicator(Modifier.size(20.dp), strokeWidth = 2.dp)
                    Text(pr)
                }
                return@Column
            }
            erreur?.let { Text(it, Modifier.padding(horizontal = 20.dp), color = MaterialTheme.colorScheme.error) }
            ListItem(
                headlineContent = { Text("Nouveau chat…") },
                supportingContent = { Text("Choisir le dossier") },
                leadingContent = { Icon(Icons.Filled.AddComment, null) },
                colors = ListItemDefaults.colors(containerColor = Color.Transparent),
                modifier = Modifier.clickable(enabled = connecte) { nouvelle = true },
            )
            Text("Chats en cours", Modifier.padding(horizontal = 20.dp), style = MaterialTheme.typography.titleSmall)
            val l = chats
            when {
                !connecte && l == null -> Text("Connexion au serveur…", Modifier.padding(horizontal = 20.dp), color = MaterialTheme.colorScheme.onSurfaceVariant)
                l == null -> Row(Modifier.padding(horizontal = 20.dp)) { CircularProgressIndicator(Modifier.size(20.dp), strokeWidth = 2.dp) }
                l.isEmpty() -> Text("Aucun chat ouvert.", Modifier.padding(horizontal = 20.dp), color = MaterialTheme.colorScheme.onSurfaceVariant)
                else -> LazyColumn(Modifier.heightIn(max = 360.dp)) {
                    items(l, key = { it.chatId }) { c ->
                        val e = EtatChat.de(c.state)
                        ListItem(
                            headlineContent = { Text(Format.base(c.cwd), maxLines = 1, overflow = TextOverflow.Ellipsis) },
                            supportingContent = { Text("${e.libelle} · ${c.cwd}", maxLines = 1, overflow = TextOverflow.Ellipsis) },
                            leadingContent = { Pastille(couleurEtat(e.ton), 12.dp) },
                            colors = ListItemDefaults.colors(containerColor = Color.Transparent),
                            modifier = Modifier.clickable { livrer(c, c.cwd) },
                        )
                    }
                }
            }
            TextButton(onClick = fermer, Modifier.padding(horizontal = 12.dp)) { Text("Annuler") }
        }
    }

    if (nouvelle) {
        FeuilleNouvelleSession(
            modele, connus = connus, fermer = { nouvelle = false },
            ouvert = { r, chemin -> nouvelle = false; livrer(r, chemin) },
        )
    }
}

private const val MAX_ESSAIS_NOM = 20
