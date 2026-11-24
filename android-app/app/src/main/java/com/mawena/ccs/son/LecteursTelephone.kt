package com.mawena.ccs.son

import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.media.AudioManager
import android.media.MediaMetadata
import android.media.session.MediaController
import android.media.session.MediaSessionManager
import android.media.session.PlaybackState
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.provider.Settings
import android.util.Log
import androidx.core.app.NotificationManagerCompat
import com.mawena.ccs.logique.Lecteurs
import com.mawena.ccs.reseau.CcsClient
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull
import kotlinx.coroutines.Dispatchers
import kotlin.math.abs
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.put

/**
 * Le téléphone comme lecteur piloté (phase 42) : avec l'accès aux notifications, les lecteurs du
 * téléphone (sessions média : Spotify, YouTube, Deezer…) sont rapportés au pont comme ceux de
 * l'agent Linux (`audio.report`), et les commandes `audio.control` qui les visent sont exécutées
 * par `MediaController`. La conversion est dans [Lecteurs] (testée sans Android).
 */
class LecteursTelephone(
    private val ctx: Context,
    private val client: CcsClient,
    portee: CoroutineScope,
    private val identite: StateFlow<SonPartage.Identite?>,
) {
    private val composant = ComponentName(ctx, EcouteurNotifications::class.java)
    private val principal = Handler(Looper.getMainLooper())
    private val gestionnaire: MediaSessionManager? = ctx.getSystemService(MediaSessionManager::class.java)

    private val _acces = MutableStateFlow(aAcces())
    /** L'accès aux notifications est accordé : les lecteurs du téléphone sont partagés. */
    val acces: StateFlow<Boolean> = _acces.asStateFlow()

    private val _nombre = MutableStateFlow(0)
    /** Nombre de lecteurs rapportés au pont. */
    val nombre: StateFlow<Int> = _nombre.asStateFlow()

    /** Sessions suivies (lues et changées sur le fil principal). */
    @Volatile private var controleurs: List<MediaController> = emptyList()
    private val rappels = HashMap<MediaController, MediaController.Callback>()
    private var ecouteInstallee = false

    /** Un lecteur a changé : rapport à refaire. */
    private val signal = Channel<Unit>(Channel.CONFLATED)
    /** Rapport à envoyer même sans changement visible (commande exécutée, demande du pont). */
    @Volatile private var forcer = false

    /** Noms affichés des applis, par paquet. */
    private val noms = HashMap<String, String>()

    private fun signaler(force: Boolean) {
        if (force) forcer = true
        signal.trySend(Unit)
    }

    private val ecouteSessions = MediaSessionManager.OnActiveSessionsChangedListener { liste ->
        suivre(liste.orEmpty())
        signaler(false)
    }

    init {
        EcouteurNotifications.quandConnecte = { actualiser() }
        principal.post { installer() }
        portee.launch {
            identite.collectLatest { moi ->
                if (moi == null) return@collectLatest
                var dernier: List<Map<String, Any?>>? = null
                var tours = 0
                var force = true
                while (true) {
                    // rapport forcé de temps en temps (2 min) : le pont a pu redémarrer
                    if (tours++ % 4 == 0) force = true
                    val rapport = Lecteurs.rapport(lire())
                    val inst = Lecteurs.instantane(rapport)
                    if (force || inst != dernier) {
                        val ok = runCatching {
                            client.appeler("audio.report", buildJsonObject {
                                put("device", moi.device); put("players", rapport)
                            })
                        }.onFailure { Log.w(TAG, "audio.report : ${it.message}") }.isSuccess
                        if (ok) { dernier = inst; _nombre.value = rapport.size }
                    }
                    withTimeoutOrNull(ATTENTE_MS) { signal.receive() }
                    force = forcer
                    forcer = false
                }
            }
        }
        portee.launch {
            client.evenements("audio").collect { d ->
                val moi = identite.value?.device ?: return@collect
                val action = (d["action"] as? JsonPrimitive)?.contentOrNull
                if (action == "players_refresh") {
                    // device null : tous les appareils
                    val cible = (d["device"] as? JsonPrimitive)?.contentOrNull
                    if (cible == null || cible == moi) signaler(true)
                    return@collect
                }
                val c = Lecteurs.lireCommande(d, moi) ?: return@collect
                runCatching { executer(c) }.onFailure { Log.w(TAG, "commande ${c::class.simpleName} : ${it.message}") }
                // comme l'agent Linux : petite attente puis nouvel état rapporté
                delay(300)
                signaler(true)
            }
        }
    }

    // ---- accès ---------------------------------------------------------------------------------

    private fun aAcces(): Boolean =
        NotificationManagerCompat.getEnabledListenerPackages(ctx).contains(ctx.packageName)

    /** À rappeler au retour dans l'appli (l'accès a pu être accordé dans les réglages). */
    fun actualiser() {
        principal.post {
            val avant = _acces.value
            _acces.value = aAcces()
            installer()
            if (avant != _acces.value) signaler(true)
        }
    }

    /** Ouvre le réglage où Charles accorde l'accès aux notifications à CCS. */
    fun demanderAcces(depuis: Context) {
        val detail = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            Intent(Settings.ACTION_NOTIFICATION_LISTENER_DETAIL_SETTINGS)
                .putExtra(Settings.EXTRA_NOTIFICATION_LISTENER_COMPONENT_NAME, composant.flattenToString())
        } else null
        val liste = Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS)
        for (i in listOfNotNull(detail, liste)) {
            if (depuis !is android.app.Activity) i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            if (runCatching { depuis.startActivity(i) }.isSuccess) return
        }
    }

    /** Fil principal : écoute des sessions installée dès que l'accès est là, retirée sinon. */
    private fun installer() {
        val g = gestionnaire ?: return
        if (!_acces.value) {
            if (ecouteInstallee) runCatching { g.removeOnActiveSessionsChangedListener(ecouteSessions) }
            ecouteInstallee = false
            suivre(emptyList())
            return
        }
        try {
            if (!ecouteInstallee) {
                g.addOnActiveSessionsChangedListener(ecouteSessions, composant, principal)
                ecouteInstallee = true
            }
            suivre(g.getActiveSessions(composant))
        } catch (e: SecurityException) {
            // accès retiré entre-temps
            _acces.value = false
            ecouteInstallee = false
            suivre(emptyList())
        }
    }

    /** Fil principal : un rappel par session, pour rapporter tout de suite lecture, pause, morceau. */
    private fun suivre(liste: List<MediaController>) {
        val garder = liste.take(Lecteurs.MAX_LECTEURS)
        val parJeton = garder.map { it.sessionToken }.toSet()
        val iter = rappels.entries.iterator()
        while (iter.hasNext()) {
            val e = iter.next()
            if (e.key.sessionToken !in parJeton) {
                runCatching { e.key.unregisterCallback(e.value) }
                iter.remove()
            }
        }
        val suivis = rappels.keys.map { k -> k.sessionToken }.toSet()
        for (c in garder) {
            if (c.sessionToken in suivis) continue
            val r = object : MediaController.Callback() {
                override fun onPlaybackStateChanged(state: PlaybackState?) { signaler(false) }
                override fun onMetadataChanged(metadata: MediaMetadata?) { signaler(false) }
                override fun onSessionDestroyed() { signaler(false) }
            }
            runCatching { c.registerCallback(r, principal) }.onSuccess { rappels[c] = r }
        }
        controleurs = garder
    }

    // ---- lecture des sessions ------------------------------------------------------------------

    @Suppress("DEPRECATION")
    private fun nomAppli(paquet: String): String = synchronized(noms) {
        noms.getOrPut(paquet) {
            runCatching {
                val pm = ctx.packageManager
                val info = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU)
                    pm.getApplicationInfo(paquet, PackageManager.ApplicationInfoFlags.of(0))
                else pm.getApplicationInfo(paquet, 0)
                pm.getApplicationLabel(info).toString()
            }.getOrDefault("")
        }
    }

    private fun session(c: MediaController): Lecteurs.Session {
        val p: PlaybackState? = c.playbackState
        val md: MediaMetadata? = c.metadata
        val info: MediaController.PlaybackInfo? = c.playbackInfo
        val etat = p?.state
        val duree = md?.getLong(MediaMetadata.METADATA_KEY_DURATION)?.takeIf { it > 0 }
        val position = p?.let {
            Lecteurs.position(it.position, it.lastPositionUpdateTime, it.playbackSpeed,
                SystemClock.elapsedRealtime(), Lecteurs.statut(it.state) == "Playing", duree)
        }
        fun texte(vararg cles: String): String =
            cles.firstNotNullOfOrNull { k -> md?.getString(k)?.takeIf { it.isNotBlank() } }.orEmpty()
        return Lecteurs.Session(
            paquet = c.packageName.orEmpty(),
            nomAppli = nomAppli(c.packageName.orEmpty()),
            etat = etat,
            actions = p?.actions ?: 0L,
            titre = texte(MediaMetadata.METADATA_KEY_TITLE, MediaMetadata.METADATA_KEY_DISPLAY_TITLE),
            artiste = texte(MediaMetadata.METADATA_KEY_ARTIST, MediaMetadata.METADATA_KEY_ALBUM_ARTIST,
                MediaMetadata.METADATA_KEY_DISPLAY_SUBTITLE),
            positionMs = position,
            dureeMs = duree,
            volume = info?.currentVolume,
            volumeMax = info?.maxVolume,
            controleVolume = info?.volumeControl ?: Lecteurs.VOLUME_FIXE,
        )
    }

    private fun lire(): List<Lecteurs.Session> =
        if (!_acces.value) emptyList()
        else controleurs.mapNotNull { c -> runCatching { session(c) }.getOrNull() }

    // ---- commandes -----------------------------------------------------------------------------

    /** Le contrôleur visé par l'identifiant (paquet, ou paquet.2… comme dans le rapport). */
    private fun controleur(id: String): MediaController? {
        val liste = controleurs
        val i = Lecteurs.ids(liste.map { m -> m.packageName.orEmpty() }).indexOf(id)
        return if (i < 0) null else liste[i]
    }

    private suspend fun executer(c: Lecteurs.Commande): Unit = withContext(Dispatchers.Main) {
        val m = controleur(c.lecteur) ?: return@withContext
        val t = m.transportControls
        val p = m.playbackState
        when (Lecteurs.action(c, p?.state)) {
            Lecteurs.Action.LECTURE -> t.play()
            Lecteurs.Action.PAUSE -> t.pause()
            Lecteurs.Action.SUIVANT -> t.skipToNext()
            Lecteurs.Action.PRECEDENT -> t.skipToPrevious()
            Lecteurs.Action.DEPLACER -> {
                val s = session(m)
                val d = c as Lecteurs.Commande.Deplacer
                t.seekTo(Lecteurs.positionVisee(s.positionMs ?: 0L, d.secondes, s.dureeMs))
            }
            Lecteurs.Action.VOLUME -> {
                val info = m.playbackInfo ?: return@withContext
                val max = info.maxVolume
                if (info.volumeControl == Lecteurs.VOLUME_FIXE || max <= 0) return@withContext
                val actuel = Lecteurs.volumePourcent(session(m))
                val vise = Lecteurs.volumeVise(c as Lecteurs.Commande.Volume, actuel) ?: return@withContext
                val cran = Lecteurs.cran(vise, max)
                if (info.volumeControl == Lecteurs.VOLUME_ABSOLU) {
                    m.setVolumeTo(cran, 0)
                } else {
                    // contrôle relatif : un cran à la fois, vers le cran visé
                    val ecart = (cran - info.currentVolume).coerceIn(-max, max)
                    val sens = if (ecart > 0) AudioManager.ADJUST_RAISE else AudioManager.ADJUST_LOWER
                    repeat(abs(ecart)) { m.adjustVolume(sens, 0) }
                }
            }
        }
    }

    private companion object {
        const val TAG = "LecteursTelephone"
        /** Relecture des lecteurs sans signal (volume changé, par exemple), comme l'annonce. */
        const val ATTENTE_MS = 30_000L
    }
}
