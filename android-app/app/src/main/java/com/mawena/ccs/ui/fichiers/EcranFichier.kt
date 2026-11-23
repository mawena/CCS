package com.mawena.ccs.ui.fichiers

import android.graphics.BitmapFactory
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.rememberTransformableState
import androidx.compose.foundation.gestures.transformable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.WrapText
import androidx.compose.material.icons.filled.Code
import androidx.compose.material.icons.filled.Download
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material.icons.filled.Save
import androidx.compose.material.icons.filled.Share
import androidx.compose.material.icons.filled.Visibility
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextField
import androidx.compose.material3.TextFieldDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.input.TextFieldValue
import androidx.compose.ui.text.rememberTextMeasurer
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.mawena.ccs.logique.Fichiers
import com.mawena.ccs.reseau.CcsClient
import com.mawena.ccs.reseau.EtatConnexion
import com.mawena.ccs.reseau.FichierEcrit
import com.mawena.ccs.reseau.FichierLu
import com.mawena.ccs.reseau.ImageFichier
import com.mawena.ccs.reseau.RpcException
import com.mawena.ccs.ui.Avertissement
import com.mawena.ccs.ui.BarreHaut
import com.mawena.ccs.ui.Chargement
import com.mawena.ccs.ui.Demandes
import com.mawena.ccs.ui.EtatErreur
import com.mawena.ccs.ui.EtatVide
import com.mawena.ccs.ui.LocalAvis
import com.mawena.ccs.ui.ModeleAppli
import com.mawena.ccs.ui.VueDemandes
import com.mawena.ccs.ui.chat.CouleursCode
import com.mawena.ccs.ui.chat.MarkdownVue
import com.mawena.ccs.ui.chat.colorer
import com.mawena.ccs.ui.chat.couleursCode
import com.mawena.ccs.ui.texte
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import java.util.Base64

private const val TAILLE_COLORATION = 200     // lignes colorées ensemble (la coloration s'arrête à 30 000 caractères)
private const val CLE_RETOUR = "fichiers:retour-ligne"

/**
 * Fichier ouvert (`FileView` de `web/files.js`) : code coloré numéroté (ligne citée en évidence),
 * Markdown rendu (« Aperçu »), images (zoom à deux doigts), édition et enregistrement avec conflit
 * signalé, télécharger, partager. Quitter avec des modifications non enregistrées est confirmé.
 */
@Composable
fun EcranFichier(
    modele: ModeleAppli,
    chemin: String,
    ligne: Int?,
    retour: () -> Unit,
    /** Connexion à utiliser : la principale, ou celle d'un appareil de l'onglet Fichiers. */
    client: CcsClient = modele.depot.client,
) {
    val prefs = modele.depot.prefs
    val etat by client.etat.collectAsStateWithLifecycle()
    val connecte = etat is EtatConnexion.Connecte
    val avis = LocalAvis.current
    val contexte = LocalContext.current
    val portee = rememberCoroutineScope()
    val demandes = remember { Demandes() }
    val nom = Fichiers.nom(chemin)

    var lu by remember { mutableStateOf<FichierLu?>(null) }
    var erreur by remember { mutableStateOf<String?>(null) }
    var image by remember { mutableStateOf<android.graphics.Bitmap?>(null) }
    var imageErreur by remember { mutableStateOf<String?>(null) }
    var original by remember { mutableStateOf("") }
    var stamp by remember { mutableStateOf<JsonElement?>(null) }
    var edition by rememberSaveable { mutableStateOf(false) }
    var champ by remember { mutableStateOf(TextFieldValue("")) }
    var apercu by rememberSaveable { mutableStateOf(false) }
    var retourLigne by remember { mutableStateOf(prefs.lire(CLE_RETOUR) == "1") }
    var menu by remember { mutableStateOf(false) }
    var travail by remember { mutableStateOf<String?>(null) }
    var progres by remember { mutableFloatStateOf(-1f) }
    val modifie = edition && champ.text != original

    suspend fun charger() {
        erreur = null
        try {
            val r = client.appeler("files.read", FichierLu.serializer(), buildJsonObject { put("path", chemin) })
            stamp = r.stamp
            if (r.kind == "text") {
                original = r.text.orEmpty()
                if (!edition || champ.text.isEmpty()) champ = TextFieldValue(original)
            }
            if (r.kind == "image") {
                try {
                    val im = client.appeler("files.image", ImageFichier.serializer(), buildJsonObject { put("path", chemin) })
                    image = withContext(Dispatchers.Default) {
                        val o = Base64.getDecoder().decode(im.data)
                        BitmapFactory.decodeByteArray(o, 0, o.size)
                    }
                    imageErreur = if (image == null) "Cette image ne s'affiche pas ici (format non pris en charge)." else null
                } catch (e: Exception) {
                    imageErreur = e.texte()
                }
            }
            lu = r
        } catch (e: Exception) {
            erreur = e.texte()
        }
    }
    LaunchedEffect(connecte, chemin) { if (connecte && lu == null) charger() }

    fun quitter() {
        if (!modifie) { retour(); return }
        portee.launch {
            if (demandes.confirmer("Abandonner les modifications ?", "Elles ne sont pas enregistrées.", "Abandonner", danger = true)) retour()
        }
    }
    BackHandler(enabled = modifie) { quitter() }

    fun agir(libelle: String, action: suspend () -> Unit) {
        if (travail != null) return
        portee.launch {
            travail = libelle
            progres = -1f
            try { action() } catch (e: Exception) { avis.dire(e.texte()) } finally { travail = null }
        }
    }
    val progresDe = { recu: Long, total: Long -> progres = if (total > 0) (recu.toFloat() / total).coerceIn(0f, 1f) else -1f }

    fun enregistrer() = agir("Enregistrement…") {
        try {
            val r = client.appeler("files.write", FichierEcrit.serializer(), buildJsonObject {
                put("path", chemin); put("text", champ.text); stamp?.let { put("stamp", it) }
            })
            stamp = r.stamp
            original = champ.text
            edition = false
            avis.dire("Enregistré.")
        } catch (e: RpcException) {
            if (e.code == "conflit") avis.dire(
                "Le fichier a changé depuis son ouverture (Claude l'a peut-être modifié) : copie tes changements, puis rouvre-le.", long = true,
            ) else throw e
        }
    }

    val texte = lu?.takeIf { it.kind == "text" }
    val md = Fichiers.estMarkdown(nom)
    Column(Modifier.fillMaxSize().imePadding()) {
        BarreHaut(nom, Fichiers.parent(chemin), retour = ::quitter) {
            if (texte != null && edition) {
                IconButton(onClick = ::enregistrer, enabled = travail == null) { Icon(Icons.Filled.Save, "Enregistrer") }
            } else if (texte != null) {
                if (md) IconButton(onClick = { apercu = !apercu }) {
                    Icon(if (apercu) Icons.Filled.Code else Icons.Filled.Visibility, if (apercu) "Source" else "Aperçu")
                }
                IconButton(onClick = { champ = TextFieldValue(original); apercu = false; edition = true }) { Icon(Icons.Filled.Edit, "Modifier") }
            }
            Box {
                IconButton(onClick = { menu = true }) { Icon(Icons.Filled.MoreVert, "Plus d'actions") }
                DropdownMenu(menu, { menu = false }) {
                    DropdownMenuItem(text = { Text("Télécharger") }, leadingIcon = { Icon(Icons.Filled.Download, null) }, onClick = {
                        menu = false
                        agir("Téléchargement…") { avis.dire("« ${Transferts.versTelechargements(contexte, client, chemin, progresDe)} » enregistré dans Téléchargements.") }
                    })
                    DropdownMenuItem(text = { Text("Partager") }, leadingIcon = { Icon(Icons.Filled.Share, null) }, onClick = {
                        menu = false
                        agir("Préparation du partage…") { Transferts.partager(contexte, client, chemin, progresDe) }
                    })
                    if (texte != null) DropdownMenuItem(
                        text = { Text(if (retourLigne) "Sans retour à la ligne" else "Retour à la ligne") },
                        leadingIcon = { Icon(Icons.AutoMirrored.Filled.WrapText, null) },
                        onClick = { menu = false; retourLigne = !retourLigne; prefs.ecrire(CLE_RETOUR, if (retourLigne) "1" else "0") },
                    )
                    if (edition) DropdownMenuItem(text = { Text("Annuler les modifications") }, onClick = {
                        menu = false
                        portee.launch {
                            if (!modifie || demandes.confirmer("Abandonner les modifications ?", "Elles ne sont pas enregistrées.", "Abandonner", danger = true)) {
                                champ = TextFieldValue(original); edition = false
                            }
                        }
                    })
                }
            }
        }
        travail?.let { t ->
            Column(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 4.dp)) {
                Text(t, style = MaterialTheme.typography.bodySmall)
                if (progres >= 0f) LinearProgressIndicator(progress = { progres }, Modifier.fillMaxWidth()) else LinearProgressIndicator(Modifier.fillMaxWidth())
            }
        }
        val l = lu
        when {
            l == null && erreur != null -> EtatErreur(erreur!!) { portee.launch { charger() } }
            l == null -> Chargement()
            l.kind == "text" && edition -> TextField(
                champ, { champ = it }, Modifier.fillMaxSize(),
                textStyle = TextStyle(fontFamily = FontFamily.Monospace, fontSize = 13.sp, lineHeight = 18.sp),
                colors = TextFieldDefaults.colors(),
            )
            l.kind == "text" && md && apercu -> MarkdownVue(original, Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp))
            l.kind == "text" -> VueCode(original, Fichiers.langue(nom), ligne, retourLigne)
            l.kind == "image" -> {
                val b = image
                if (b != null) ImageZoom(b) else EtatVide(imageErreur ?: "Chargement de l'image…")
            }
            else -> Column(Modifier.fillMaxWidth().padding(24.dp), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(12.dp)) {
                Text(
                    if (l.kind == "binary") "Fichier binaire : il n'est pas affiché." else "Fichier trop gros pour être affiché ici.",
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                OutlinedButton(onClick = {
                    agir("Téléchargement…") { avis.dire("« ${Transferts.versTelechargements(contexte, client, chemin, progresDe)} » enregistré dans Téléchargements.") }
                }) { Text("Télécharger") }
                OutlinedButton(onClick = { agir("Préparation du partage…") { Transferts.partager(contexte, client, chemin, progresDe) } }) { Text("Partager") }
            }
        }
    }
    VueDemandes(demandes)
}

/** Lignes colorées (par paquets, la coloration du chat étant bornée en taille). */
private fun colorerLignes(lignes: List<String>, langue: String, cc: CouleursCode): List<AnnotatedString> {
    val out = ArrayList<AnnotatedString>(lignes.size)
    for (debut in lignes.indices step TAILLE_COLORATION) {
        val paquet = lignes.subList(debut, minOf(lignes.size, debut + TAILLE_COLORATION))
        val bloc = colorer(paquet.joinToString("\n"), langue, cc)
        var pos = 0
        for (t in paquet) {
            out.add(bloc.subSequence(pos, pos + t.length))
            pos += t.length + 1
        }
    }
    return out
}

@Composable
private fun VueCode(texte: String, langue: String, ligne: Int?, retourLigne: Boolean) {
    val cc = couleursCode()
    val lignes = remember(texte) { Fichiers.lignes(texte) }
    val colorees by produceState<List<AnnotatedString>?>(null, texte, langue, cc) {
        value = withContext(Dispatchers.Default) { colorerLignes(lignes, langue, cc) }
    }
    val etat = rememberLazyListState()
    LaunchedEffect(ligne, colorees != null) {
        if (ligne != null && ligne > 0 && colorees != null) etat.scrollToItem((ligne - 1 - 5).coerceIn(0, maxOf(0, lignes.size - 1)))
    }
    val style = TextStyle(fontFamily = FontFamily.Monospace, fontSize = 12.5.sp, lineHeight = 17.sp, color = cc.texte)
    val mesure = rememberTextMeasurer()
    val densite = LocalDensity.current
    val chiffres = lignes.size.toString().length
    val largeurNumero = with(densite) { mesure.measure("0".repeat(chiffres), style).size.width.toDp() } + 12.dp
    val largeur = remember(texte, retourLigne) {
        if (retourLigne) 0.dp else {
            val plusLongue = lignes.maxOfOrNull { it.length }?.coerceAtMost(2000) ?: 0
            with(densite) { mesure.measure("0".repeat(maxOf(1, plusLongue)), style).size.width.toDp() } + largeurNumero + 24.dp
        }
    }
    Box(Modifier.fillMaxSize().background(cc.fond).let { if (retourLigne) it else it.horizontalScroll(rememberScrollState()) }) {
        SelectionContainer {
            LazyColumn(if (retourLigne) Modifier.fillMaxSize() else Modifier.width(largeur).fillMaxSize(), state = etat) {
                itemsIndexed(lignes, key = { i, _ -> i }) { i, t ->
                    val cible = ligne == i + 1
                    Row(Modifier.fillMaxWidth().background(if (cible) Avertissement.copy(alpha = 0.22f) else cc.fond).padding(end = 8.dp)) {
                        Text(
                            (i + 1).toString(), Modifier.width(largeurNumero).padding(end = 8.dp),
                            style = style.copy(color = cc.commentaire), textAlign = androidx.compose.ui.text.style.TextAlign.End,
                        )
                        Text(colorees?.getOrNull(i) ?: AnnotatedString(t), style = style, softWrap = retourLigne)
                    }
                }
            }
        }
    }
}

@Composable
private fun ImageZoom(b: android.graphics.Bitmap) {
    var echelle by remember { mutableFloatStateOf(1f) }
    var decalage by remember { mutableStateOf(Offset.Zero) }
    val etat = rememberTransformableState { zoom, pan, _ ->
        echelle = (echelle * zoom).coerceIn(1f, 8f)
        decalage = if (echelle == 1f) Offset.Zero else decalage + pan
    }
    val im = remember(b) { b.asImageBitmap() }
    Box(Modifier.fillMaxSize().transformable(etat), contentAlignment = Alignment.Center) {
        Image(
            im, null,
            Modifier.fillMaxWidth().padding(8.dp).graphicsLayer(scaleX = echelle, scaleY = echelle, translationX = decalage.x, translationY = decalage.y),
        )
    }
}
