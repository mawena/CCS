package com.mawena.ccs.ui.chat

import androidx.compose.foundation.background
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.IntrinsicSize
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.ContentCopy
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.luminance
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.LinkAnnotation
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.TextLinkStyles
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.text.withLink
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.mawena.ccs.logique.Coloration
import com.mawena.ccs.logique.LiensFichiers
import com.mawena.ccs.logique.Markdown
import kotlinx.coroutines.delay

/** Couleurs de la coloration du code, claires ou sombres selon le fond. */
class CouleursCode(val fond: Color, val texte: Color, val motCle: Color, val chaine: Color, val commentaire: Color, val nombre: Color, val ajout: Color, val retrait: Color, val titre: Color)

@Composable
fun couleursCode(): CouleursCode {
    val sombre = MaterialTheme.colorScheme.background.luminance() < 0.5f
    return remember(sombre) {
        if (sombre) CouleursCode(
            Color(0xFF1A1A1E), Color(0xFFE6E6EA), Color(0xFFC678DD), Color(0xFF98C379), Color(0xFF7F848E),
            Color(0xFFD19A66), Color(0xFF7EE787), Color(0xFFFF7B72), Color(0xFF79C0FF),
        ) else CouleursCode(
            Color(0xFFF3F3F6), Color(0xFF24292F), Color(0xFF8250DF), Color(0xFF0A7A30), Color(0xFF6E7781),
            Color(0xFFB35900), Color(0xFF116329), Color(0xFFB3261E), Color(0xFF0550AE),
        )
    }
}

fun colorer(code: String, langue: String, c: CouleursCode): AnnotatedString = buildAnnotatedString {
    append(code)
    for (j in Coloration.jetons(code, langue)) {
        val couleur = when (j.genre) {
            Coloration.Genre.MotCle -> c.motCle
            Coloration.Genre.Chaine -> c.chaine
            Coloration.Genre.Commentaire -> c.commentaire
            Coloration.Genre.Nombre -> c.nombre
            Coloration.Genre.Ajout -> c.ajout
            Coloration.Genre.Retrait -> c.retrait
            Coloration.Genre.Titre -> c.titre
        }
        addStyle(
            SpanStyle(color = couleur, fontStyle = if (j.genre == Coloration.Genre.Commentaire) FontStyle.Italic else null,
                fontWeight = if (j.genre == Coloration.Genre.Titre) FontWeight.SemiBold else null),
            j.debut, j.fin,
        )
    }
}

/**
 * Segments en ligne (gras, italique, code, barré, liens cliquables) en texte annoté. Avec `ouvre`,
 * les chemins de fichiers du projet (en code ou dans le texte) deviennent des liens qui les ouvrent.
 */
fun annoter(segments: List<Markdown.Segment>, lien: Color, fondCode: Color, ouvre: OuvreFichier? = null): AnnotatedString = buildAnnotatedString {
    val styleLien = TextLinkStyles(SpanStyle(color = lien, textDecoration = TextDecoration.Underline))
    fun versFichier(r: LiensFichiers.Ref, style: SpanStyle, texte: String) {
        val o = ouvre ?: return
        withLink(LinkAnnotation.Clickable("fichier:${r.chemin}", styleLien) { o.ouvrir(o.liens.absolu(r), r.ligne) }) {
            withStyle(style) { append(texte) }
        }
    }
    for (s in segments) {
        val style = SpanStyle(
            fontWeight = if (s.gras) FontWeight.Bold else null,
            fontStyle = if (s.italique) FontStyle.Italic else null,
            fontFamily = if (s.code) FontFamily.Monospace else null,
            background = if (s.code) fondCode else Color.Unspecified,
            textDecoration = if (s.barre) TextDecoration.LineThrough else null,
            fontSize = if (s.code) 13.sp else androidx.compose.ui.unit.TextUnit.Unspecified,
        )
        if (s.lien != null && (s.lien.startsWith("http://") || s.lien.startsWith("https://") || s.lien.startsWith("mailto:"))) {
            withLink(LinkAnnotation.Url(s.lien, styleLien)) {
                withStyle(style) { append(s.texte) }
            }
            continue
        }
        if (ouvre != null && s.lien == null) {
            if (s.code) {
                val r = ouvre.liens.ref(s.texte)
                if (r != null) { versFichier(r, style, s.texte); continue }
            } else {
                val refs = ouvre.liens.trouver(s.texte)
                if (refs.isNotEmpty()) {
                    var a = 0
                    for (r in refs) {
                        withStyle(style) { append(s.texte.substring(a, r.index)) }
                        versFichier(r, style, r.texte)
                        a = r.index + r.texte.length
                    }
                    withStyle(style) { append(s.texte.substring(a)) }
                    continue
                }
            }
        }
        withStyle(style) { append(s.texte) }
    }
}

/** Réponse de Claude rendue : le Markdown n'est relu que quand son texte change. */
@Composable
fun MarkdownVue(texte: String, modifier: Modifier = Modifier) {
    val blocs = remember(texte) { Markdown.analyser(texte) }
    Column(modifier, verticalArrangement = Arrangement.spacedBy(6.dp)) {
        blocs.forEach { BlocVue(it) }
    }
}

@Composable
private fun BlocVue(b: Markdown.Bloc) {
    val lien = MaterialTheme.colorScheme.primary
    val ouvre = LocalOuvreFichier.current
    val cc = couleursCode()
    when (b) {
        is Markdown.Paragraphe -> Text(remember(b, lien, ouvre) { annoter(b.contenu, lien, cc.fond, ouvre) }, style = MaterialTheme.typography.bodyMedium)
        is Markdown.Titre -> Text(
            remember(b, lien, ouvre) { annoter(b.contenu, lien, cc.fond, ouvre) },
            style = when (b.niveau) {
                1 -> MaterialTheme.typography.titleLarge
                2 -> MaterialTheme.typography.titleMedium
                else -> MaterialTheme.typography.titleSmall
            },
            fontWeight = FontWeight.SemiBold,
            modifier = Modifier.padding(top = 4.dp),
        )
        is Markdown.Liste -> Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
            b.elements.forEach { e ->
                Row(Modifier.padding(start = (e.niveau * 16).dp)) {
                    val marque = when (e.coche) { true -> "☑"; false -> "☐"; null -> e.marque }
                    Text(marque, Modifier.width(if (e.marque.length > 2) 30.dp else 20.dp), style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant)
                    Text(remember(e, lien, ouvre) { annoter(e.contenu, lien, cc.fond, ouvre) }, style = MaterialTheme.typography.bodyMedium)
                }
            }
        }
        is Markdown.Code -> BlocCode(b.texte, b.langue)
        is Markdown.Citation -> Row(Modifier.height(IntrinsicSize.Min).padding(vertical = 2.dp)) {
            Box(Modifier.width(3.dp).fillMaxHeight().background(MaterialTheme.colorScheme.outline, RoundedCornerShape(2.dp)))
            Column(Modifier.padding(start = 10.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                androidx.compose.runtime.CompositionLocalProvider(
                    androidx.compose.material3.LocalContentColor provides MaterialTheme.colorScheme.onSurfaceVariant,
                ) { b.blocs.forEach { BlocVue(it) } }
            }
        }
        is Markdown.Tableau -> Tableau(b, lien, cc.fond)
        Markdown.Regle -> HorizontalDivider(Modifier.padding(vertical = 4.dp))
    }
}

@Composable
private fun Tableau(t: Markdown.Tableau, lien: Color, fondCode: Color) {
    val n = maxOf(t.entetes.size, t.lignes.maxOfOrNull { it.size } ?: 0)
    val largeurs = remember(t) {
        (0 until n).map { k ->
            val lettres = (listOf(t.entetes) + t.lignes).maxOf { r -> r.getOrNull(k)?.let { Markdown.texte(it).length } ?: 0 }
            (lettres * 8 + 16).coerceIn(56, 240)
        }
    }
    Surface(shape = RoundedCornerShape(6.dp), color = MaterialTheme.colorScheme.surfaceContainerLow, modifier = Modifier.fillMaxWidth()) {
        Column(Modifier.horizontalScroll(rememberScrollState()).padding(4.dp)) {
            listOf(t.entetes).plus(t.lignes).forEachIndexed { i, r ->
                Row {
                    for (k in 0 until n) {
                        Text(
                            annoter(r.getOrNull(k).orEmpty(), lien, fondCode),
                            Modifier.width(largeurs[k].dp).padding(horizontal = 6.dp, vertical = 4.dp),
                            style = MaterialTheme.typography.bodySmall,
                            fontWeight = if (i == 0) FontWeight.SemiBold else null,
                        )
                    }
                }
                if (i == 0) HorizontalDivider()
            }
        }
    }
}

/** Bloc de code : barre avec la langue et « Copier », code coloré défilant en largeur. */
@Composable
fun BlocCode(code: String, langue: String, modifier: Modifier = Modifier) {
    val cc = couleursCode()
    val presse = LocalClipboardManager.current
    var copie by remember { mutableStateOf(false) }
    LaunchedEffect(copie) { if (copie) { delay(1500); copie = false } }
    val texte = remember(code, langue, cc) { colorer(code, langue, cc) }
    Surface(color = cc.fond, shape = RoundedCornerShape(8.dp), modifier = modifier.fillMaxWidth()) {
        Column {
            Row(Modifier.fillMaxWidth().padding(start = 10.dp), verticalAlignment = Alignment.CenterVertically) {
                Text(langue.ifEmpty { "code" }, Modifier.weight(1f), style = MaterialTheme.typography.labelSmall, color = cc.commentaire)
                TextButton(onClick = { presse.setText(AnnotatedString(code)); copie = true }) {
                    Icon(if (copie) Icons.Filled.Check else Icons.Filled.ContentCopy, null, Modifier.size(14.dp))
                    Text(if (copie) " Copié" else " Copier", style = MaterialTheme.typography.labelSmall)
                }
            }
            Text(
                texte,
                Modifier.horizontalScroll(rememberScrollState()).padding(start = 10.dp, end = 10.dp, bottom = 10.dp),
                color = cc.texte, fontFamily = FontFamily.Monospace, fontSize = 12.5.sp, lineHeight = 17.sp, softWrap = false,
            )
        }
    }
}
