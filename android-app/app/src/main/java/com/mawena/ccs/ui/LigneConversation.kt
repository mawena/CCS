package com.mawena.ccs.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.ListItem
import androidx.compose.material3.ListItemDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.mawena.ccs.logique.Format
import com.mawena.ccs.reseau.Conversation
import com.mawena.ccs.reseau.Cout
import kotlinx.coroutines.sync.withLock
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

/** Petite étiquette arrondie (« ouverte », compte, origine). */
@Composable
fun Etiquette(texte: String, fond: Color = MaterialTheme.colorScheme.secondaryContainer, encre: Color = MaterialTheme.colorScheme.onSecondaryContainer) {
    Surface(color = fond, contentColor = encre, shape = RoundedCornerShape(50)) {
        Text(texte, Modifier.padding(horizontal = 8.dp, vertical = 2.dp), style = MaterialTheme.typography.labelSmall, maxLines = 1)
    }
}

/**
 * Une conversation de l'historique (`convRow` de `sessions-conv.js`) : titre, marque « ouverte »,
 * projet, date et coût (demandé quand la ligne s'affiche, une requête à la fois), menu « ⋯ ».
 */
@Composable
fun LigneConversation(
    modele: ModeleAppli,
    c: Conversation,
    ouverte: Boolean,
    montrerProjet: Boolean,
    surOuvrir: () -> Unit,
    surMenu: () -> Unit,
) {
    val cle = "${c.path}:${c.misAJour}"
    var cout by remember(cle) { mutableStateOf(modele.couts[cle]) }
    LaunchedEffect(cle) {
        if (cout != null || c.path.isEmpty()) return@LaunchedEffect
        modele.fileCouts.withLock {
            modele.couts[cle]?.let { cout = it; return@withLock }
            runCatching {
                modele.depot.client.appeler("conversation.cost", Cout.serializer(), buildJsonObject { put("path", c.path) })
            }.onSuccess { modele.couts[cle] = it; cout = it }   // le coût est un plus : l'échec est tu
        }
    }
    val meta = listOfNotNull(
        if (montrerProjet) Format.base(c.cwd).takeIf { it.isNotEmpty() } else null,
        Format.ilYA(c.misAJour).takeIf { it.isNotEmpty() },
        cout?.short?.takeIf { it.isNotEmpty() },
    ).joinToString(" · ")
    ListItem(
        headlineContent = {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                Text(c.titre, Modifier.weight(1f, fill = false), maxLines = 2, overflow = TextOverflow.Ellipsis)
                if (ouverte) Etiquette("ouverte")
            }
        },
        supportingContent = { if (meta.isNotEmpty()) Text(meta, maxLines = 1, overflow = TextOverflow.Ellipsis) },
        trailingContent = {
            IconButton(onClick = surMenu) { Icon(Icons.Filled.MoreVert, contentDescription = "Actions pour ${c.titre}") }
        },
        colors = ListItemDefaults.colors(
            containerColor = Color.Transparent,
            headlineColor = if (c.dossierExiste) MaterialTheme.colorScheme.onSurface else MaterialTheme.colorScheme.onSurfaceVariant,
        ),
        modifier = Modifier.clickable(onClick = surOuvrir),
    )
}
