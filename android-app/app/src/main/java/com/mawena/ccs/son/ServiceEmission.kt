package com.mawena.ccs.son

import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.media.projection.MediaProjection
import android.media.projection.MediaProjectionManager
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.util.Log
import androidx.core.app.NotificationManagerCompat
import androidx.core.app.ServiceCompat
import androidx.core.content.IntentCompat
import com.mawena.ccs.CcsAppli
import com.mawena.ccs.notif.Notifs
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch

/**
 * Service au premier plan (type « mediaProjection ») qui capte le son de ce téléphone avec
 * l'accord donné dans l'activité et l'émet vers la destination de [SonPartage.capture]. Arrêté
 * quand la capture revient à « arrêtée » (événement `stop`, bouton Arrêter, projection retirée).
 */
class ServiceEmission : Service() {
    private val portee = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    private var projection: MediaProjection? = null
    private var capteur: CaptureSon? = null
    private var visee: String? = null

    private val son get() = (application as CcsAppli).depot.son

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        Notifs.canaux(this)
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        // bouton Arrêter de la notification (startService, pas de premier plan à reprendre)
        if (intent?.action == NotifsSon.ACTION_ARRETER) {
            son.arreterEmission()
            stopSelf()
            return START_NOT_STICKY
        }
        if (!premierPlan()) {
            son.emissionFinie("Envoi impossible : service refusé par le système.")
            stopSelf()
            return START_NOT_STICKY
        }
        if (projection != null) return START_NOT_STICKY       // déjà en route
        val code = intent?.getIntExtra(EXTRA_CODE, 0) ?: 0
        val donnees = intent?.let { IntentCompat.getParcelableExtra(it, EXTRA_DONNEES, Intent::class.java) }
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.Q || donnees == null) {
            son.emissionFinie("Envoi impossible : accord de capture manquant.")
            stopSelf()
            return START_NOT_STICKY
        }
        try {
            val mpm = getSystemService(MediaProjectionManager::class.java) ?: throw IllegalStateException("projection indisponible")
            val p = mpm.getMediaProjection(code, donnees) ?: throw IllegalStateException("accord expiré")
            projection = p
            // projection retirée (puce « partage » de la barre d'état, écran verrouillé…) : fin de l'envoi
            p.registerCallback(object : MediaProjection.Callback() {
                override fun onStop() {
                    son.emissionFinie(null)
                    stopSelf()
                }
            }, Handler(Looper.getMainLooper()))
            capteur = CaptureSon(p) { erreur -> portee.launch { son.emissionFinie(erreur); stopSelf() } }.also { it.demarrer() }
        } catch (e: Exception) {
            Log.w(TAG, "projection", e)
            son.emissionFinie("Envoi impossible : ${e.message}")
            stopSelf()
            return START_NOT_STICKY
        }
        portee.launch {
            son.capture.collect { c ->
                when (c) {
                    SonPartage.Capture.Arretee -> stopSelf()
                    is SonPartage.Capture.Preparation -> notifier(c)
                    is SonPartage.Capture.Envoi -> {
                        notifier(c)
                        if (c.destination.flux != visee) {
                            visee = c.destination.flux
                            runCatching { capteur?.viser(c.destination.ip, c.destination.port) }
                                .onFailure { son.emissionFinie("Adresse invalide : ${c.destination.ip}"); stopSelf() }
                        }
                    }
                }
            }
        }
        return START_NOT_STICKY
    }

    private fun notifier(c: SonPartage.Capture) {
        runCatching { NotificationManagerCompat.from(this).notify(NotifsSon.ID_EMISSION, NotifsSon.emission(this, c)) }
    }

    private fun premierPlan(): Boolean = try {
        val type = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION else 0
        ServiceCompat.startForeground(this, NotifsSon.ID_EMISSION, NotifsSon.emission(this, son.capture.value), type)
        true
    } catch (e: Exception) {
        Log.w(TAG, "premier plan", e)
        false
    }

    override fun onDestroy() {
        capteur?.arreter()
        capteur = null
        runCatching { projection?.stop() }
        projection = null
        portee.cancel()
        super.onDestroy()
    }

    companion object {
        private const val TAG = "ServiceEmission"
        private const val EXTRA_CODE = "code"
        private const val EXTRA_DONNEES = "donnees"

        fun intention(ctx: Context, code: Int, donnees: Intent): Intent =
            Intent(ctx, ServiceEmission::class.java).putExtra(EXTRA_CODE, code).putExtra(EXTRA_DONNEES, donnees)
    }
}
