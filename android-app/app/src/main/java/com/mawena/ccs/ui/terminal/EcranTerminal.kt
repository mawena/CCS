package com.mawena.ccs.ui.terminal

import android.content.ClipData
import android.content.ClipboardManager
import android.view.KeyEvent
import androidx.compose.foundation.background
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.ContentCopy
import androidx.compose.material.icons.filled.ContentPaste
import androidx.compose.material.icons.filled.Keyboard
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.mawena.ccs.donnees.PrefsAppli
import com.mawena.ccs.logique.Touches
import com.mawena.ccs.terminal.Collants
import com.mawena.ccs.terminal.SessionTerminal
import com.mawena.ccs.terminal.VueTerminal
import com.mawena.ccs.ui.BarreHaut
import com.mawena.ccs.ui.Confirmation
import com.mawena.ccs.ui.EtatVide
import com.mawena.ccs.ui.LocalAvis
import com.mawena.ccs.ui.ModeleAppli
import com.mawena.ccs.ui.texte
import kotlinx.coroutines.launch

/** Ctrl et Alt collants (état Compose lu par la vue du terminal). */
private class EtatCollants : Collants {
    var c by mutableStateOf(false)
    var a by mutableStateOf(false)
    override val ctrl get() = c
    override val alt get() = a
    override fun relacher() { c = false; a = false }
}

/**
 * Un terminal en plein écran (`web/terminal.js`) : la vue de l'émulateur, la barre de touches
 * (Échap, Tab, Ctrl et Alt collants, flèches, symboles difficiles à taper), Coller, Copier,
 * taille du texte (boutons ou deux doigts), Fermer.
 */
@Composable
fun EcranTerminal(modele: ModeleAppli, id: String, retour: () -> Unit) {
    val terminaux = modele.depot.terminaux
    val sessions by terminaux.sessions.collectAsStateWithLifecycle()
    val s = sessions.firstOrNull { it.id == id }
    val avis = LocalAvis.current
    val portee = rememberCoroutineScope()
    val ctx = LocalContext.current
    val collants = remember { EtatCollants() }
    var taille by remember { mutableIntStateOf(modele.depot.reglages.tailleTerminal) }
    var vue by remember { mutableStateOf<VueTerminal?>(null) }
    var menu by remember { mutableStateOf(false) }
    var fermer by remember { mutableStateOf(false) }
    var titre by remember(s) { mutableStateOf(s?.titre ?: "Terminal") }
    var fini by remember(s) { mutableStateOf(s?.fin != null) }

    LaunchedEffect(terminaux) { terminaux.avis.collect { avis.dire(it) } }
    androidx.compose.runtime.DisposableEffect(s) {
        val f = { titre = s?.titre ?: "Terminal"; fini = s?.fin != null }
        s?.ecouter(f)
        s?.surCopie = { t -> copier(ctx, t); avis.dire("Copié.") }
        onDispose { s?.oublier(f); s?.surCopie = null }
    }

    fun zoomer(pas: Int) {
        taille = (taille + pas).coerceIn(PrefsAppli.MIN_TERMINAL, PrefsAppli.MAX_TERMINAL)
        modele.depot.reglages.tailleTerminal = taille
    }

    fun coller() {
        val t = ctx.getSystemService(ClipboardManager::class.java)?.primaryClip?.takeIf { it.itemCount > 0 }
            ?.getItemAt(0)?.coerceToText(ctx)?.toString()
        if (t.isNullOrEmpty()) avis.dire("Le presse-papiers est vide.") else { vue?.enBas(); s?.coller(t) }
    }

    Column(Modifier.fillMaxSize().imePadding()) {
        BarreHaut(
            titre, (s?.cwd?.let { com.mawena.ccs.logique.TachesFond.cheminCourt(it) } ?: "") + if (fini) " · terminé" else "", retour = retour,
            actions = {
                IconButton(onClick = { vue?.montrerClavier() }, enabled = s != null && !fini) { Icon(Icons.Filled.Keyboard, "Clavier") }
                IconButton(onClick = { coller() }, enabled = s != null && !fini) { Icon(Icons.Filled.ContentPaste, "Coller") }
                IconButton(onClick = { menu = true }) { Icon(Icons.Filled.MoreVert, "Plus") }
                DropdownMenu(menu, { menu = false }) {
                    DropdownMenuItem({ Text("Copier tout le texte") }, leadingIcon = { Icon(Icons.Filled.ContentCopy, null) }, onClick = {
                        menu = false
                        s?.let { copier(ctx, it.texte().trimEnd()); avis.dire("Copié.") }
                    })
                    DropdownMenuItem({ Text("Texte plus grand") }, onClick = { zoomer(1) })
                    DropdownMenuItem({ Text("Texte plus petit") }, onClick = { zoomer(-1) })
                    DropdownMenuItem({ Text(if (fini) "Retirer" else "Fermer le terminal") }, leadingIcon = { Icon(Icons.Filled.Close, null) }, onClick = {
                        menu = false
                        if (fini) s?.let { terminaux.retirer(it); retour() } else fermer = true
                    })
                }
            },
        )
        if (s == null) {
            EtatVide("Ce terminal n'est plus ouvert dans l'appli.")
            return@Column
        }
        AndroidView(
            factory = { c ->
                VueTerminal(c, collants).also { v ->
                    v.setPadding(8, 4, 8, 4)
                    vue = v
                }
            },
            update = { v ->
                v.surSaisie = { d -> terminaux.entrer(s.id, d) }
                v.surTaille = { ses, c, l -> terminaux.redimensionner(ses, c, l) }
                v.surZoom = { zoomer(it) }
                v.surAppuiLong = { menu = true }
                v.tailleTexte(taille)
                v.session = s
            },
            modifier = Modifier.weight(1f).fillMaxWidth().background(Color(0xFF1E1E22)),
        )
        BarreTouches(collants, actif = !fini, touche = { code -> vue?.envoyerTouche(code, null) }, texte = { vue?.taper(it) })
    }
    LaunchedEffect(vue, s) {
        // le clavier ne s'ouvre qu'une fois la vue attachée et la fenêtre au premier plan
        kotlinx.coroutines.delay(250)
        if (s != null && s.fin == null) vue?.montrerClavier()
    }

    if (fermer && s != null) {
        Confirmation(
            "Fermer le terminal « ${s.nom} » ?", "Ce qui y tourne est arrêté.", "Fermer", danger = true,
            surOui = {
                fermer = false
                portee.launch {
                    try { terminaux.fermer(s); retour() } catch (e: Exception) { avis.dire(e.texte()) }
                }
            },
            surNon = { fermer = false },
        )
    }
}

private fun copier(ctx: android.content.Context, t: String) {
    ctx.getSystemService(ClipboardManager::class.java)?.setPrimaryClip(ClipData.newPlainText("Terminal", t))
}

/** Barre de touches : deux rangées défilantes, au-dessus du clavier du téléphone. */
@Composable
private fun BarreTouches(collants: EtatCollants, actif: Boolean, touche: (Int) -> Unit, texte: (String) -> Unit) {
    Surface(color = MaterialTheme.colorScheme.surfaceContainer, modifier = Modifier.navigationBarsPadding()) {
        Column(Modifier.fillMaxWidth().padding(vertical = 4.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Rangee {
                Touche("Échap", actif) { touche(KeyEvent.KEYCODE_ESCAPE) }
                Touche("Tab", actif) { touche(KeyEvent.KEYCODE_TAB) }
                Collant("Ctrl", collants.c, actif) { collants.c = !collants.c }
                Collant("Alt", collants.a, actif) { collants.a = !collants.a }
                Touche(Touches.Fleche.Gauche.libelle, actif) { touche(KeyEvent.KEYCODE_DPAD_LEFT) }
                Touche(Touches.Fleche.Bas.libelle, actif) { touche(KeyEvent.KEYCODE_DPAD_DOWN) }
                Touche(Touches.Fleche.Haut.libelle, actif) { touche(KeyEvent.KEYCODE_DPAD_UP) }
                Touche(Touches.Fleche.Droite.libelle, actif) { touche(KeyEvent.KEYCODE_DPAD_RIGHT) }
            }
            Rangee {
                Touches.SYMBOLES.forEach { sym -> Touche(sym, actif) { texte(sym) } }
                Touche("Début", actif) { touche(KeyEvent.KEYCODE_MOVE_HOME) }
                Touche("Fin", actif) { touche(KeyEvent.KEYCODE_MOVE_END) }
                Touche("PgPréc", actif) { touche(KeyEvent.KEYCODE_PAGE_UP) }
                Touche("PgSuiv", actif) { touche(KeyEvent.KEYCODE_PAGE_DOWN) }
            }
        }
    }
}

@Composable
private fun Rangee(contenu: @Composable () -> Unit) {
    Row(
        Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()).padding(horizontal = 6.dp),
        horizontalArrangement = Arrangement.spacedBy(4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) { contenu() }
}

private val MargeTouche = PaddingValues(horizontal = 10.dp, vertical = 0.dp)

@Composable
private fun Touche(libelle: String, actif: Boolean, faire: () -> Unit) {
    OutlinedButton(onClick = faire, enabled = actif, contentPadding = MargeTouche, modifier = Modifier.padding(0.dp)) {
        Text(libelle, fontFamily = FontFamily.Monospace)
    }
}

@Composable
private fun Collant(libelle: String, arme: Boolean, actif: Boolean, faire: () -> Unit) {
    if (arme) FilledTonalButton(onClick = faire, enabled = actif, contentPadding = MargeTouche) { Text(libelle, fontFamily = FontFamily.Monospace) }
    else Touche(libelle, actif, faire)
}

/** Ouvre un terminal dans `cwd` (shell, ou commande permise) et rend son identifiant. */
suspend fun ouvrirTerminal(modele: ModeleAppli, cwd: String, commande: String? = null, nom: String? = null): SessionTerminal =
    modele.depot.terminaux.ouvrir(cwd, 80, 24, commande, nom)
