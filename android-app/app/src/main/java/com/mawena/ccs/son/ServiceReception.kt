package com.mawena.ccs.son

import android.app.Service
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import androidx.core.app.NotificationManagerCompat
import androidx.core.app.ServiceCompat
import com.mawena.ccs.CcsAppli
import com.mawena.ccs.notif.Notifs
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch

/**
 * Service au premier plan (type « mediaPlayback ») qui joue le flux reçu
 * ([SonPartage.reception]) : relancé quand le flux change, arrêté quand il n'y en a plus
 * (événement `stop`, bouton Arrêter, 10 s sans paquet).
 */
class ServiceReception : Service() {
    private val portee = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    private var suivi: Job? = null
    private var lecteur: LecteurRtp? = null
    private var courant: SonPartage.Reception? = null

    private val son get() = (application as CcsAppli).depot.son

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        Notifs.canaux(this)
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val r = son.reception.value
        if (!premierPlan(r)) { stopSelf(); return START_NOT_STICKY }
        if (intent?.action == NotifsSon.ACTION_ARRETER || r == null) {
            son.arreterReception()
            stopSelf()
            return START_NOT_STICKY
        }
        if (suivi == null) suivi = portee.launch {
            son.reception.collect { flux ->
                if (flux == null) stopSelf() else if (flux != courant) lire(flux)
            }
        }
        return START_NOT_STICKY
    }

    private fun lire(r: SonPartage.Reception) {
        lecteur?.arreter()
        courant = r
        runCatching { NotificationManagerCompat.from(this).notify(NotifsSon.ID_RECEPTION, NotifsSon.reception(this, r)) }
        lecteur = LecteurRtp(r.port, r.canaux) { erreur ->
            portee.launch { son.receptionFinie(r.flux, erreur) }
        }.also { it.demarrer() }
    }

    private fun premierPlan(r: SonPartage.Reception?): Boolean = try {
        val type = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PLAYBACK else 0
        ServiceCompat.startForeground(this, NotifsSon.ID_RECEPTION, NotifsSon.reception(this, r), type)
        true
    } catch (_: Exception) {
        false
    }

    override fun onTimeout(startId: Int, fgsType: Int) {
        son.arreterReception()
        stopSelf()
    }

    override fun onDestroy() {
        suivi?.cancel()
        lecteur?.arreter()
        lecteur = null
        portee.cancel()
        super.onDestroy()
    }
}
