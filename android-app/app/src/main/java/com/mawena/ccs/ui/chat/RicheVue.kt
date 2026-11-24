package com.mawena.ccs.ui.chat

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.media.AudioAttributes
import android.media.MediaPlayer
import android.util.LruCache
import android.widget.MediaController
import android.widget.VideoView
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Movie
import androidx.compose.material.icons.filled.MusicNote
import androidx.compose.material.icons.filled.Pause
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Slider
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.Stable
import androidx.compose.runtime.compositionLocalOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalUriHandler
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import com.mawena.ccs.logique.ChatRiche
import com.mawena.ccs.logique.Markdown
import com.mawena.ccs.reseau.CcsClient
import com.mawena.ccs.ui.fichiers.Transferts
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import java.io.File
import java.io.IOException
import java.security.MessageDigest
import java.util.concurrent.ConcurrentHashMap

/**
 * Contexte du chat riche (phase 49) : dossier de la session, accès aux fichiers du serveur, cache
 * local et envoi d'un message comme Charles (`null` : vue d'un sous-agent, boutons inactifs).
 */
@Stable
class Riche(
    val cwd: String,
    val client: CcsClient,
    val http: OkHttpClient,
    val cache: File,
    val envoyer: ((String) -> Unit)?,
)

/** Présent seulement dans le chat : ailleurs (fichiers .md…), le Markdown reste simple. */
val LocalRiche = compositionLocalOf<Riche?> { null }

/** Fichiers des médias (https ou serveur) gardés dans le cache, et images décodées en mémoire. */
private object CacheRiche {
    private const val COTE_MAX = 1600
    private val fichiers = ConcurrentHashMap<String, File>()
    private val verrou = Mutex()
    private var menage = false
    private val images = object : LruCache<String, Bitmap>(24 * 1024 * 1024) {
        override fun sizeOf(key: String, value: Bitmap): Int = value.byteCount
    }

    private fun cle(s: ChatRiche.Source): String = when (s) {
        is ChatRiche.Source.Url -> s.url
        is ChatRiche.Source.Chemin -> s.chemin
    }

    private fun nom(cle: String): String {
        val h = MessageDigest.getInstance("SHA-256").digest(cle.toByteArray()).joinToString("") { "%02x".format(it) }
        val ext = Regex("\\.([A-Za-z0-9]{1,5})$").find(cle.substringBefore('?').substringBefore('#'))?.value.orEmpty()
        return h.take(32) + ext
    }

    private fun tropGros(): Nothing = throw IOException("Fichier trop gros pour être affiché ici.")

    /** Le fichier local du média, téléchargé une fois (60 Mo au plus). */
    suspend fun fichier(r: Riche, s: ChatRiche.Source): File {
        val cle = cle(s)
        fichiers[cle]?.takeIf { it.exists() }?.let { return it }
        val f = verrou.withLock {
            fichiers[cle]?.takeIf { it.exists() } ?: withContext(Dispatchers.IO) {
                r.cache.mkdirs()
                if (!menage) {
                    menage = true
                    val limite = System.currentTimeMillis() - 24L * 3600 * 1000
                    r.cache.listFiles()?.filter { it.lastModified() < limite }?.forEach { it.delete() }
                }
                val cible = File(r.cache, nom(cle))
                if (cible.exists()) return@withContext cible
                val tmp = File(r.cache, cible.name + ".part")
                try {
                    when (s) {
                        is ChatRiche.Source.Chemin -> Transferts.telecharger(r.client, s.chemin, tmp) { _, total ->
                            if (total > ChatRiche.MAX_LOCAL) tropGros()
                        }
                        is ChatRiche.Source.Url -> r.http.newCall(Request.Builder().url(s.url).build()).execute().use { rep ->
                            if (!rep.isSuccessful) throw IOException("HTTP ${rep.code}")
                            val corps = rep.body ?: throw IOException("Réponse vide")
                            if (corps.contentLength() > ChatRiche.MAX_LOCAL) tropGros()
                            tmp.outputStream().use { out ->
                                corps.byteStream().use { entree ->
                                    val tampon = ByteArray(64 * 1024)
                                    var total = 0L
                                    while (true) {
                                        val n = entree.read(tampon)
                                        if (n < 0) break
                                        total += n
                                        if (total > ChatRiche.MAX_LOCAL) tropGros()
                                        out.write(tampon, 0, n)
                                    }
                                }
                            }
                        }
                    }
                    if (!tmp.renameTo(cible)) throw IOException("Cache illisible")
                    cible
                } catch (e: Exception) {
                    tmp.delete()
                    throw e
                }
            }
        }
        fichiers[cle] = f
        return f
    }

    /** Image réduite (au plus ~1600 px de côté), gardée en mémoire. */
    suspend fun image(r: Riche, s: ChatRiche.Source): Bitmap {
        val cle = cle(s)
        images.get(cle)?.let { return it }
        val f = fichier(r, s)
        val bmp = withContext(Dispatchers.IO) {
            val bornes = BitmapFactory.Options().apply { inJustDecodeBounds = true }
            BitmapFactory.decodeFile(f.path, bornes)
            if (bornes.outWidth <= 0 || bornes.outHeight <= 0) null
            else {
                var n = 1
                while (maxOf(bornes.outWidth, bornes.outHeight) / n > COTE_MAX) n *= 2
                BitmapFactory.decodeFile(f.path, BitmapFactory.Options().apply { inSampleSize = n })
            }
        } ?: throw IOException("Image illisible")
        images.put(cle, bmp)
        return bmp
    }
}

/** Comme runCatching, sans avaler l'annulation de la coroutine. */
private suspend fun <T> essayer(bloc: suspend () -> T): Result<T> = try {
    Result.success(bloc())
} catch (e: CancellationException) {
    throw e
} catch (e: Exception) {
    Result.failure(e)
}

@Composable
private fun Manque(texte: String) {
    Text("image indisponible : $texte", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
}

/** Image Markdown : taille limitée, agrandie d'un toucher (un autre la ferme). */
@Composable
fun ImageRiche(src: String, alt: String, modifier: Modifier = Modifier, hauteurMax: Dp = 300.dp) {
    val r = LocalRiche.current
    val source = remember(src, r?.cwd) { r?.let { ChatRiche.resoudre(src, it.cwd) } }
    if (r == null || source == null) {
        Manque(alt.ifEmpty { src })
        return
    }
    var etat by remember(source) { mutableStateOf<Result<Bitmap>?>(null) }
    LaunchedEffect(source) { etat = essayer { CacheRiche.image(r, source) } }
    val e = etat
    if (e == null) {
        Box(modifier.size(56.dp), contentAlignment = Alignment.Center) {
            CircularProgressIndicator(Modifier.size(20.dp), strokeWidth = 2.dp)
        }
        return
    }
    val bmp = e.getOrNull()
    if (bmp == null) {
        Manque(alt.ifEmpty { src })
        return
    }
    val ib = remember(bmp) { bmp.asImageBitmap() }
    var grand by remember { mutableStateOf(false) }
    Image(
        ib, alt,
        modifier.widthIn(max = 360.dp).heightIn(max = hauteurMax).clip(RoundedCornerShape(8.dp)).clickable { grand = true },
        contentScale = ContentScale.Fit,
    )
    if (grand) {
        Dialog(onDismissRequest = { grand = false }, properties = DialogProperties(usePlatformDefaultWidth = false)) {
            Box(
                Modifier.fillMaxSize().background(Color.Black.copy(alpha = 0.92f)).clickable { grand = false },
                contentAlignment = Alignment.Center,
            ) {
                Image(ib, alt, Modifier.fillMaxWidth(), contentScale = ContentScale.Fit)
            }
        }
    }
}

private fun duree(ms: Int): String {
    val s = (ms.coerceAtLeast(0) / 1000)
    return "%d:%02d".format(s / 60, s % 60)
}

/**
 * Lecteur d'un son ou d'une vidéo (https ou fichier du serveur). Rien ne se charge avant le premier
 * toucher ; un fichier du serveur est alors lu par `files.download` (60 Mo au plus).
 */
@Composable
fun LecteurMedia(src: String, label: String = "") {
    val r = LocalRiche.current ?: return
    val genre = remember(src) { ChatRiche.media(src) } ?: return
    val source = remember(src, r.cwd) { ChatRiche.resoudre(src, r.cwd) } ?: return
    var demande by remember(source) { mutableStateOf(false) }
    var etat by remember(source) { mutableStateOf<Result<String>?>(null) }
    LaunchedEffect(source, demande) {
        if (!demande) return@LaunchedEffect
        etat = when (source) {
            is ChatRiche.Source.Url -> Result.success(source.url)
            is ChatRiche.Source.Chemin -> essayer { CacheRiche.fichier(r, source).path }
        }
    }
    val nom = label.ifEmpty { src.trim().substringAfterLast('/') }
    Surface(
        shape = RoundedCornerShape(8.dp),
        color = MaterialTheme.colorScheme.surfaceContainerLow,
        modifier = Modifier.widthIn(max = 420.dp).fillMaxWidth(),
    ) {
        val e = etat
        val adresse = e?.getOrNull()
        when {
            !demande -> Row(
                Modifier.clickable { demande = true }.padding(horizontal = 10.dp, vertical = 8.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                Icon(if (genre == ChatRiche.Media.Audio) Icons.Filled.MusicNote else Icons.Filled.Movie, null, Modifier.size(18.dp))
                Text(nom, Modifier.weight(1f), style = MaterialTheme.typography.bodySmall, maxLines = 1, overflow = TextOverflow.Ellipsis)
                Icon(Icons.Filled.PlayArrow, "Lire", Modifier.size(20.dp))
            }
            e == null -> Row(Modifier.padding(10.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                CircularProgressIndicator(Modifier.size(16.dp), strokeWidth = 2.dp)
                Text(nom, style = MaterialTheme.typography.bodySmall, maxLines = 1, overflow = TextOverflow.Ellipsis)
            }
            adresse == null -> Text(
                "$nom : ${e.exceptionOrNull()?.message ?: "illisible"}",
                Modifier.padding(10.dp), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.error,
            )
            genre == ChatRiche.Media.Audio -> Audio(adresse, nom)
            else -> Video(adresse)
        }
    }
}

@Composable
private fun Audio(adresse: String, nom: String) {
    var joue by remember(adresse) { mutableStateOf(false) }
    var pret by remember(adresse) { mutableStateOf(false) }
    var erreur by remember(adresse) { mutableStateOf(false) }
    var position by remember(adresse) { mutableIntStateOf(0) }
    var total by remember(adresse) { mutableIntStateOf(0) }
    val lecteur = remember(adresse) { MediaPlayer() }
    DisposableEffect(lecteur) {
        lecteur.setAudioAttributes(
            AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_MEDIA).setContentType(AudioAttributes.CONTENT_TYPE_MUSIC).build(),
        )
        lecteur.setOnPreparedListener { mp ->
            pret = true
            total = mp.duration
            mp.start()
            joue = true
        }
        lecteur.setOnCompletionListener { joue = false; position = 0 }
        lecteur.setOnErrorListener { _, _, _ -> erreur = true; joue = false; true }
        try {
            lecteur.setDataSource(adresse)
            lecteur.prepareAsync()
        } catch (e: Exception) {
            erreur = true
        }
        onDispose { lecteur.release() }
    }
    LaunchedEffect(lecteur, joue) {
        while (joue) {
            position = runCatching { lecteur.currentPosition }.getOrDefault(position)
            delay(500)
        }
    }
    if (erreur) {
        Text("$nom : lecture impossible", Modifier.padding(10.dp), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.error)
        return
    }
    Row(Modifier.padding(end = 10.dp), verticalAlignment = Alignment.CenterVertically) {
        IconButton(
            onClick = {
                if (joue) { lecteur.pause(); joue = false } else { lecteur.start(); joue = true }
            },
            enabled = pret,
        ) {
            Icon(if (joue) Icons.Filled.Pause else Icons.Filled.PlayArrow, if (joue) "Pause" else "Lecture")
        }
        Column(Modifier.weight(1f)) {
            Text(nom, style = MaterialTheme.typography.bodySmall, maxLines = 1, overflow = TextOverflow.Ellipsis)
            Slider(
                value = if (total > 0) position.toFloat() / total else 0f,
                onValueChange = { v -> if (pret && total > 0) { position = (v * total).toInt(); lecteur.seekTo(position) } },
                enabled = pret && total > 0,
                modifier = Modifier.height(24.dp),
            )
        }
        Text("${duree(position)} / ${duree(total)}", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

@Composable
private fun Video(adresse: String) {
    var erreur by remember(adresse) { mutableStateOf(false) }
    if (erreur) {
        Text("Vidéo illisible", Modifier.padding(10.dp), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.error)
        return
    }
    Box(Modifier.fillMaxWidth().height(220.dp).background(Color.Black), contentAlignment = Alignment.Center) {
        AndroidView(
            factory = { c ->
                VideoView(c).apply {
                    val commandes = MediaController(c)
                    commandes.setAnchorView(this)
                    setMediaController(commandes)
                    setOnPreparedListener { start() }
                    setOnErrorListener { _, _, _ -> erreur = true; true }
                    setVideoPath(adresse)
                }
            },
            onRelease = { it.stopPlayback() },
        )
    }
}

// ---- composants des blocs ```ccs --------------------------------------------------------------

@Composable
private fun Boite(modifier: Modifier = Modifier, contenu: @Composable () -> Unit) {
    Surface(shape = RoundedCornerShape(10.dp), color = MaterialTheme.colorScheme.surfaceContainerLow, modifier = modifier) {
        Column(Modifier.padding(10.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) { contenu() }
    }
}

@Composable
private fun TitreRiche(texte: String) {
    Text(texte, style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold)
}

/** Bloc ```ccs valide : choix, formulaire, carte ou cartes. Les boutons envoient une seule fois. */
@Composable
fun ComposantVue(c: ChatRiche.Composant) {
    val envoyer = LocalRiche.current?.envoyer
    when (c) {
        is ChatRiche.Choix -> ChoixVue(c, envoyer)
        is ChatRiche.Formulaire -> FormulaireVue(c, envoyer)
        is ChatRiche.Carte -> CarteVue(c, envoyer, Modifier.widthIn(max = 360.dp))
        is ChatRiche.Cartes -> Row(
            Modifier.horizontalScroll(rememberScrollState()),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            c.items.forEach { CarteVue(it, envoyer, Modifier.width(240.dp)) }
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun ChoixVue(c: ChatRiche.Choix, envoyer: ((String) -> Unit)?) {
    var envoye by rememberSaveable { mutableStateOf(false) }
    Boite {
        if (c.titre.isNotEmpty()) TitreRiche(c.titre)
        FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            c.options.forEach { o ->
                OutlinedButton(
                    onClick = { if (o.message.isNotEmpty()) { envoye = true; envoyer?.invoke(o.message) } },
                    enabled = !envoye && envoyer != null,
                ) { Text(o.label) }
            }
        }
    }
}

@Composable
private fun FormulaireVue(f: ChatRiche.Formulaire, envoyer: ((String) -> Unit)?) {
    var envoye by rememberSaveable { mutableStateOf(false) }
    val actif = !envoye && envoyer != null
    val valeurs = remember(f) {
        mutableStateMapOf<String, String>().apply { f.champs.forEach { put(it.cle, ChatRiche.valeurInitiale(it)) } }
    }
    Boite {
        if (f.titre.isNotEmpty()) TitreRiche(f.titre)
        f.champs.forEach { c ->
            if (c.type == "liste") {
                var ouvert by remember { mutableStateOf(false) }
                Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
                    Text(c.label, style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    Box {
                        OutlinedButton(onClick = { ouvert = true }, enabled = actif) {
                            Text(valeurs[c.cle].orEmpty().ifEmpty { "—" })
                        }
                        DropdownMenu(expanded = ouvert, onDismissRequest = { ouvert = false }) {
                            c.options.forEach { o ->
                                DropdownMenuItem(text = { Text(o) }, onClick = { valeurs[c.cle] = o; ouvert = false })
                            }
                        }
                    }
                }
            } else {
                OutlinedTextField(
                    value = valeurs[c.cle].orEmpty(),
                    onValueChange = { valeurs[c.cle] = it },
                    label = { Text(c.label) },
                    placeholder = if (c.aide.isNotEmpty()) { { Text(c.aide) } } else null,
                    singleLine = true,
                    enabled = actif,
                    keyboardOptions = KeyboardOptions(keyboardType = if (c.type == "nombre") KeyboardType.Number else KeyboardType.Text),
                    modifier = Modifier.fillMaxWidth(),
                )
            }
        }
        Button(
            onClick = {
                val message = ChatRiche.messageFormulaire(f, valeurs)
                if (message.isNotEmpty()) { envoye = true; envoyer?.invoke(message) }
            },
            enabled = actif,
        ) { Text(f.envoyer) }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun CarteVue(c: ChatRiche.Carte, envoyer: ((String) -> Unit)?, modifier: Modifier = Modifier) {
    val uri = LocalUriHandler.current
    var envoye by rememberSaveable { mutableStateOf(false) }
    Surface(shape = RoundedCornerShape(10.dp), color = MaterialTheme.colorScheme.surfaceContainerLow, modifier = modifier) {
        Column {
            if (c.image.isNotEmpty()) ImageRiche(c.image, c.titre, Modifier.fillMaxWidth(), hauteurMax = 180.dp)
            Column(Modifier.padding(10.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                val aLien = c.lien.isNotEmpty()
                Text(
                    c.titre,
                    if (aLien) Modifier.clickable { runCatching { uri.openUri(c.lien) } } else Modifier,
                    style = MaterialTheme.typography.titleSmall,
                    fontWeight = FontWeight.SemiBold,
                    color = if (aLien) MaterialTheme.colorScheme.primary else Color.Unspecified,
                    textDecoration = if (aLien) TextDecoration.Underline else null,
                )
                c.prix?.takeIf { it.isNotEmpty() }?.let {
                    Text(it, style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.Bold, color = MaterialTheme.colorScheme.primary)
                }
                if (c.sousTitre.isNotEmpty()) {
                    Text(c.sousTitre, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                if (c.description.isNotEmpty()) Text(c.description, style = MaterialTheme.typography.bodyMedium)
                if (c.actions.isNotEmpty()) {
                    FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        c.actions.forEach { o ->
                            if (ChatRiche.estHttp(o.lien)) {
                                OutlinedButton(onClick = { runCatching { uri.openUri(o.lien) } }) { Text(o.label) }
                            } else {
                                OutlinedButton(
                                    onClick = { if (o.message.isNotEmpty()) { envoye = true; envoyer?.invoke(o.message) } },
                                    enabled = !envoye && envoyer != null,
                                ) { Text(o.label) }
                            }
                        }
                    }
                }
            }
        }
    }
}

// ---- texte avec images et lecteurs ------------------------------------------------------------

private sealed class Morceau {
    /** Texte, puis les sons et vidéos qu'il cite (adresse → libellé). */
    data class Texte(val segments: List<Markdown.Segment>, val medias: List<Pair<String, String>>) : Morceau()
    data class Img(val src: String, val alt: String) : Morceau()
}

private fun medias(segments: List<Markdown.Segment>, ouvre: OuvreFichier?): List<Pair<String, String>> {
    val vus = LinkedHashMap<String, String>()
    fun ajouter(src: String, label: String) { if (ChatRiche.media(src) != null && src !in vus) vus[src] = label }
    for (s in segments) {
        val l = s.lien
        when {
            l != null -> ajouter(l, s.texte)
            s.code -> ajouter(s.texte.trim(), "")
            ouvre != null -> for (ref in ouvre.liens.trouver(s.texte)) ajouter(ouvre.liens.absolu(ref), ref.texte)
        }
    }
    return vus.map { it.key to it.value }
}

private fun decouper(segments: List<Markdown.Segment>, ouvre: OuvreFichier?): List<Morceau> {
    val out = ArrayList<Morceau>()
    var courant = ArrayList<Markdown.Segment>()
    fun vider() {
        if (courant.isNotEmpty()) {
            out.add(Morceau.Texte(courant, medias(courant, ouvre)))
            courant = ArrayList()
        }
    }
    for (s in segments) {
        val l = s.lien
        if (s.image && l != null) {
            vider()
            out.add(Morceau.Img(l, if (s.texte == l) "" else s.texte))
        } else {
            courant.add(s)
        }
    }
    vider()
    return out
}

/**
 * Contenu en ligne d'un paragraphe ou d'un élément de liste. Hors du chat : le texte annoté seul.
 * Dans le chat : les images s'affichent, et un lecteur suit chaque son ou vidéo cité.
 */
@Composable
fun ContenuRiche(segments: List<Markdown.Segment>, style: TextStyle, modifier: Modifier = Modifier) {
    val lien = MaterialTheme.colorScheme.primary
    val ouvre = LocalOuvreFichier.current
    val r = LocalRiche.current
    val cc = couleursCode()
    if (r == null) {
        Text(remember(segments, lien, ouvre) { annoter(segments, lien, cc.fond, ouvre) }, modifier, style = style)
        return
    }
    val morceaux = remember(segments, ouvre) { decouper(segments, ouvre) }
    Column(modifier, verticalArrangement = Arrangement.spacedBy(4.dp)) {
        morceaux.forEach { m ->
            when (m) {
                is Morceau.Texte -> {
                    if (m.segments.any { it.texte.isNotBlank() }) {
                        Text(remember(m, lien, ouvre) { annoter(m.segments, lien, cc.fond, ouvre) }, style = style)
                    }
                    m.medias.forEach { (src, label) -> LecteurMedia(src, label) }
                }
                is Morceau.Img ->
                    if (ChatRiche.media(m.src) != null) LecteurMedia(m.src, m.alt) else ImageRiche(m.src, m.alt)
            }
        }
    }
}
