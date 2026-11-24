package com.mawena.ccs

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.media.projection.MediaProjectionConfig
import android.media.projection.MediaProjectionManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import androidx.activity.result.contract.ActivityResultContracts
import androidx.core.content.ContextCompat
import androidx.core.content.IntentCompat
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import com.mawena.ccs.son.NotifsSon
import kotlinx.coroutines.launch
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

    // Son partagé : envoi du son de ce téléphone, accord demandé à chaque départ (micro puis capture).
    private var accordEnCours: com.mawena.ccs.son.SonPartage.DemandeAccord? = null

    private val demandeMicro = registerForActivityResult(ActivityResultContracts.RequestPermission()) { ok ->
        if (ok) demanderProjection() else {
            accordEnCours = null
            son().accordRefuse()
        }
    }

    private val demandeProjection = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { r ->
        val d = accordEnCours
        accordEnCours = null
        val donnees = r.data
        if (d != null && r.resultCode == RESULT_OK && donnees != null) son().accordObtenu(d, r.resultCode, donnees)
        else son().accordRefuse()
    }

    private fun son() = (application as CcsAppli).depot.son

    private fun demanderAccord(d: com.mawena.ccs.son.SonPartage.DemandeAccord) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.Q) return
        accordEnCours = d
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED) {
            demanderProjection()
        } else {
            demandeMicro.launch(Manifest.permission.RECORD_AUDIO)
        }
    }

    private fun demanderProjection() {
        val mpm = getSystemService(MediaProjectionManager::class.java) ?: return
        // tout l'écran (pas une seule appli) : le son de toutes les applis est capté
        val intention = if (Build.VERSION.SDK_INT >= 34) {
            mpm.createScreenCaptureIntent(MediaProjectionConfig.createConfigForDefaultDisplay())
        } else {
            mpm.createScreenCaptureIntent()
        }
        try {
            demandeProjection.launch(intention)
        } catch (_: Exception) {
            accordEnCours = null
            son().accordRefuse()
        }
    }

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
        // demande d'accord de capture (écran Son, notification « Touchez pour envoyer… »)
        lifecycleScope.launch {
            repeatOnLifecycle(Lifecycle.State.STARTED) {
                son().demandeAccord.collect { d ->
                    if (d != null) {
                        son().demandeAccord.value = null
                        demanderAccord(d)
                    }
                }
            }
        }
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
            NotifsSon.ACTION_SON -> {
                son().reprendre()
                modele.demande.value = DemandeAppli.Son
            }
            NotifsSon.ACTION_ENVOYER -> {
                NotifsSon.destination(i)?.let { son().accepterEnvoi(it) }
                modele.demande.value = DemandeAppli.Son
            }
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
