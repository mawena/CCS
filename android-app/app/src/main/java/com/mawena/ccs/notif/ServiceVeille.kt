package com.mawena.ccs.notif

import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import androidx.core.app.NotificationManagerCompat
import androidx.core.app.ServiceCompat
import androidx.core.content.ContextCompat
import com.mawena.ccs.CcsAppli
import com.mawena.ccs.reseau.EtatConnexion
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.launch

/**
 * Service de premier plan (type « remoteMessaging ») qui garde le WebSocket ouvert quand l'appli
 * est en arrière-plan, pour prévenir des fins de tour et des attentes. Notification persistante
 * discrète (« CCS connecté », canal à importance minimale). Pas de réveil programmé : la
 * reconnexion du client suit le réseau (Doze coupe le réseau, on se reconnecte à la fenêtre
 * suivante ou quand le réseau revient).
 */
class ServiceVeille : Service() {
    private var suivi: Job? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        Notifs.canaux(this)
        if (!premierPlan(false)) { stopSelf(); return }
        val depot = (application as CcsAppli).depot
        if (!depot.demarrerSiBesoin()) { stopSelf(); return }
        depot.veille.demarrer()
        suivi = depot.portee.launch {
            depot.client.etat.map { e ->
                when (e) {
                    EtatConnexion.Arrete, is EtatConnexion.Refuse -> null
                    EtatConnexion.Connecte -> true
                    else -> false
                }
            }.distinctUntilChanged().collect { connecte ->
                if (connecte == null) stopSelf()
                else runCatching { NotificationManagerCompat.from(this@ServiceVeille).notify(Notifs.ID_SERVICE, Notifs.service(this@ServiceVeille, connecte)) }
            }
        }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int = START_STICKY

    override fun onTimeout(startId: Int, fgsType: Int) {
        stopSelf()
    }

    override fun onDestroy() {
        suivi?.cancel()
        (application as CcsAppli).depot.veille.arreter()
        super.onDestroy()
    }

    private fun premierPlan(connecte: Boolean): Boolean = try {
        val type = if (Build.VERSION.SDK_INT >= 34) ServiceInfo.FOREGROUND_SERVICE_TYPE_REMOTE_MESSAGING else 0
        ServiceCompat.startForeground(this, Notifs.ID_SERVICE, Notifs.service(this, connecte), type)
        true
    } catch (_: Exception) {
        false       // démarrage en arrière-plan refusé par le système (Android 12+)
    }

    companion object {
        /**
         * Lance ou arrête le service selon le réglage de l'appli, la connexion et la permission
         * des notifications. À appeler depuis le premier plan (démarrage, réglage changé).
         */
        fun appliquer(ctx: Context) {
            val depot = (ctx.applicationContext as CcsAppli).depot
            val voulu = depot.reglages.notifications && depot.coffre.lire() != null && Notifs.permises(ctx)
            val intention = Intent(ctx, ServiceVeille::class.java)
            if (voulu) {
                runCatching { ContextCompat.startForegroundService(ctx, intention) }
            } else {
                ctx.stopService(intention)
            }
        }
    }
}
