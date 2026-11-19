package com.mawena.ccs.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Build
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.mawena.ccs.logique.Format
import com.mawena.ccs.reseau.MessageHistorique
import com.mawena.ccs.reseau.Messages
import com.mawena.ccs.reseau.RpcException
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

private const val LIMITE = 200

/**
 * Écran Chat provisoire : lecture simple de l'historique (`conversation.messages`). Le vrai chat
 * (suivi en direct, envoi, outils, markdown) remplace cet écran avec la tâche 4 de la phase 25.
 */
@Composable
fun EcranChat(modele: ModeleAppli, dest: DestChat, retour: () -> Unit) {
    var messages by remember { mutableStateOf<List<MessageHistorique>?>(null) }
    var erreur by remember { mutableStateOf<String?>(null) }
    var essai by remember { mutableIntStateOf(0) }
    val defile = rememberLazyListState()

    LaunchedEffect(dest, essai) {
        erreur = null
        val chemin = dest.chemin
        if (chemin == null) { messages = emptyList(); return@LaunchedEffect }
        try {
            messages = modele.depot.client.appeler(
                "conversation.messages", Messages.serializer(),
                buildJsonObject { put("path", chemin); put("limit", LIMITE) },
            ).messages.filter { it.text.isNotBlank() || it.tool != null }
        } catch (e: RpcException) {
            if (e.code == "introuvable") messages = emptyList() else erreur = e.texte()   // chat neuf : pas encore de journal
        } catch (e: Exception) {
            erreur = e.texte()
        }
    }
    LaunchedEffect(messages) { messages?.let { if (it.isNotEmpty()) defile.scrollToItem(it.size) } }

    Column(Modifier.fillMaxSize()) {
        BarreHaut(dest.titre ?: Format.base(dest.cwd), Format.base(dest.cwd), retour = retour)
        Surface(color = MaterialTheme.colorScheme.secondaryContainer, modifier = Modifier.fillMaxWidth()) {
            Text(
                if (dest.chatId != null) "Chat ouvert sur le serveur. L'envoi et le suivi en direct arrivent avec le chat complet."
                else "Historique en lecture. Le chat complet (reprise, envoi) arrive bientôt.",
                Modifier.padding(horizontal = 16.dp, vertical = 8.dp), style = MaterialTheme.typography.bodySmall,
            )
        }
        val m = messages
        when {
            erreur != null -> EtatErreur(erreur!!) { essai++ }
            m == null -> Chargement()
            m.isEmpty() -> EtatVide("Pas encore de message dans cette conversation.")
            else -> LazyColumn(
                Modifier.fillMaxSize(), state = defile,
                contentPadding = PaddingValues(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                if (m.size >= LIMITE) item {
                    Text("Seuls les $LIMITE derniers messages sont affichés.", Modifier.fillMaxWidth(),
                        style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                items(m) { BulleSimple(it) }
            }
        }
    }
}

@Composable
private fun BulleSimple(m: MessageHistorique) {
    val role = Format.role(m.role)
    if (role == null) {
        // outil ou note : une ligne discrète
        Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(horizontal = 8.dp)) {
            Icon(Icons.Filled.Build, null, Modifier.padding(end = 6.dp), tint = MaterialTheme.colorScheme.onSurfaceVariant)
            Text(
                m.tool?.let { listOf(it.name, it.target).filter(String::isNotBlank).joinToString(" · ") } ?: m.text,
                maxLines = 2, overflow = TextOverflow.Ellipsis,
                style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        return
    }
    val toi = role == Format.Role.Toi
    Row(Modifier.fillMaxWidth(), horizontalArrangement = if (toi) Arrangement.End else Arrangement.Start) {
        Surface(
            color = if (toi) MaterialTheme.colorScheme.primaryContainer else MaterialTheme.colorScheme.surfaceContainer,
            contentColor = if (toi) MaterialTheme.colorScheme.onPrimaryContainer else MaterialTheme.colorScheme.onSurface,
            shape = RoundedCornerShape(16.dp),
            modifier = Modifier.widthIn(max = 340.dp),
        ) {
            Column(Modifier.padding(horizontal = 12.dp, vertical = 8.dp)) {
                Text(role.libelle, style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.primary)
                SelectionContainer { Text(m.text, style = MaterialTheme.typography.bodyMedium) }
            }
        }
    }
}
