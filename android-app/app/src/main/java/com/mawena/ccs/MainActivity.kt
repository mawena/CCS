package com.mawena.ccs

import android.content.Intent
import android.net.Uri
import android.os.Bundle
import androidx.core.content.IntentCompat
import com.mawena.ccs.logique.AnalysePartage
import com.mawena.ccs.logique.ElementPartage
import com.mawena.ccs.logique.Partage
import com.mawena.ccs.notif.Notifs
import com.mawena.ccs.notif.ServiceVeille
import com.mawena.ccs.ui.DemandeAppli
import com.mawena.ccs.ui.DestChat
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.viewModels
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.runtime.getValue
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.mawena.ccs.donnees.Theme
import com.mawena.ccs.ui.ModeleAppli
import com.mawena.ccs.ui.Racine
import com.mawena.ccs.ui.ThemeCcs

class MainActivity : ComponentActivity() {
    private val modele: ModeleAppli by viewModels()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            val theme by modele.theme.collectAsStateWithLifecycle()
            val sombre = when (theme) {
                Theme.Clair -> false
                Theme.Sombre -> true
                Theme.Systeme -> isSystemInDarkTheme()
            }
            // icônes de la barre d'état lisibles avec le thème choisi dans l'appli
            androidx.compose.runtime.DisposableEffect(sombre) {
                val transparent = android.graphics.Color.TRANSPARENT
                enableEdgeToEdge(
                    statusBarStyle = androidx.activity.SystemBarStyle.auto(transparent, transparent) { sombre },
                    navigationBarStyle = androidx.activity.SystemBarStyle.auto(transparent, transparent) { sombre },
                )
                onDispose {}
            }
            ThemeCcs(sombre) { Racine(modele) }
        }
        if (savedInstanceState == null) recevoir(intent)
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        recevoir(intent)
    }

    override fun onStart() {
        super.onStart()
        // Retour au premier plan : se reconnecter sans attendre la fin du délai.
        (application as CcsAppli).depot.client.reessayer()
        // Service de fond (notifications) : lancé d'ici, au premier plan, comme Android l'exige.
        ServiceVeille.appliquer(this)
        (application as CcsAppli).depot.root.premierPlan(true)
    }

    override fun onStop() {
        (application as CcsAppli).depot.root.premierPlan(false)
        super.onStop()
    }

    /** Notification touchée, raccourci d'appli ou partage depuis une autre appli. */
    private fun recevoir(i: Intent?) {
        // ccs://jarvis : écran Jarvis en écoute ; jarvis://pair?… : QR code de « jarvis pair » scanné
        val lien = i?.data?.takeIf { i.action == Intent.ACTION_VIEW }
        if (lien?.scheme == "jarvis") {
            (application as CcsAppli).depot.jarvis.adresseRecue.value = lien.toString()
            modele.demande.value = DemandeAppli.Jarvis
            return
        }
        if (lien?.scheme == "ccs" && lien.host == "jarvis") {
            ouvrirJarvis()
            return
        }
        when (i?.action) {
            Notifs.ACTION_OUVRIR -> {
                val cwd = i.getStringExtra(Notifs.EXTRA_CWD) ?: return
                modele.demande.value = DemandeAppli.OuvrirChat(
                    DestChat(
                        cwd, i.getStringExtra(Notifs.EXTRA_SESSION), i.getStringExtra(Notifs.EXTRA_CHEMIN),
                        i.getStringExtra(Notifs.EXTRA_TITRE), i.getStringExtra(Notifs.EXTRA_CHAT),
                    ),
                )
            }
            RACCOURCI_JARVIS -> ouvrirJarvis()
            // la fenêtre du mot de passe s'affiche d'elle-même au premier plan : relire l'état du pont
            Notifs.ACTION_ROOT, Intent.ACTION_VIEW -> {
                val d = (application as CcsAppli).depot
                if (i.action == Intent.ACTION_VIEW && (i.data?.scheme != "ccs" || i.data?.host != "root")) return
                d.client.reessayer()
                d.root.premierPlan(true)
                modele.ouvrirRoot(i.data?.takeIf { it.host == "root" }?.getQueryParameter("machine"))
            }
            RACCOURCI_SESSIONS -> modele.demande.value = DemandeAppli.Sessions
            RACCOURCI_NOUVEAU -> modele.demande.value = DemandeAppli.NouveauChat
            Intent.ACTION_SEND, Intent.ACTION_SEND_MULTIPLE -> {
                val p = lirePartage(i)
                if (!p.vide) modele.partage.value = p
            }
        }
    }

    private fun ouvrirJarvis() {
        (application as CcsAppli).depot.jarvis.demandeEcoute.value = true
        modele.demande.value = DemandeAppli.Jarvis
    }

    private fun lirePartage(i: Intent): Partage {
        val uris = ArrayList<Uri>()
        if (i.action == Intent.ACTION_SEND_MULTIPLE) {
            IntentCompat.getParcelableArrayListExtra(i, Intent.EXTRA_STREAM, Uri::class.java)?.let { uris += it }
        } else {
            IntentCompat.getParcelableExtra(i, Intent.EXTRA_STREAM, Uri::class.java)?.let { uris += it }
        }
        if (uris.isEmpty()) i.clipData?.let { c -> for (k in 0 until c.itemCount) c.getItemAt(k).uri?.let { uris += it } }
        val unSeul = uris.size == 1
        val elements = uris.map { u ->
            ElementPartage(u.toString(), contentResolver.getType(u) ?: i.type?.takeIf { unSeul && !it.endsWith("/*") })
        }
        return AnalysePartage.analyser(
            i.getCharSequenceExtra(Intent.EXTRA_TEXT)?.toString(),
            i.getCharSequenceExtra(Intent.EXTRA_SUBJECT)?.toString(),
            elements,
        )
    }

    companion object {
        const val RACCOURCI_SESSIONS = "com.mawena.ccs.action.SESSIONS"
        const val RACCOURCI_NOUVEAU = "com.mawena.ccs.action.NOUVEAU_CHAT"
        const val RACCOURCI_JARVIS = "com.mawena.ccs.action.JARVIS"
    }
}
