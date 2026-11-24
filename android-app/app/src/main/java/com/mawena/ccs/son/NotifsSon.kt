package com.mawena.ccs.son

import android.app.Notification
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import com.mawena.ccs.MainActivity
import com.mawena.ccs.R
import com.mawena.ccs.notif.Notifs

/** Notifications du son partagé : services (avec Arrêter), et demandes à toucher. */
object NotifsSon {
    const val ID_RECEPTION = 20
    const val ID_EMISSION = 21
    private const val ID_DEMANDE = 22
    private const val ID_ECOUTE = 23

    const val ACTION_SON = "com.mawena.ccs.action.SON"
    const val ACTION_ENVOYER = "com.mawena.ccs.action.SON_ENVOYER"
    const val EXTRA_FLUX = "flux"
    const val EXTRA_CIBLE = "cible"
    const val EXTRA_NOM = "nom"
    const val EXTRA_IP = "ip"
    const val EXTRA_PORT = "port"

    private fun ouvrirSon(ctx: Context): PendingIntent = PendingIntent.getActivity(
        ctx, ID_RECEPTION,
        Intent(ctx, MainActivity::class.java).setAction(ACTION_SON)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP),
        PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
    )

    private fun arreter(ctx: Context, service: Class<*>, code: Int): PendingIntent = PendingIntent.getService(
        ctx, code, Intent(ctx, service).setAction(ACTION_ARRETER),
        PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
    )

    const val ACTION_ARRETER = "com.mawena.ccs.action.SON_ARRETER"

    private fun service(ctx: Context, titre: String, texte: String, arret: PendingIntent): Notification =
        NotificationCompat.Builder(ctx, Notifs.CANAL_SON)
            .setSmallIcon(R.drawable.ic_notif)
            .setContentTitle(titre)
            .setContentText(texte)
            .setContentIntent(ouvrirSon(ctx))
            .addAction(0, "Arrêter", arret)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setSilent(true)
            .setShowWhen(false)
            .setCategory(NotificationCompat.CATEGORY_TRANSPORT)
            .setForegroundServiceBehavior(NotificationCompat.FOREGROUND_SERVICE_IMMEDIATE)
            .build()

    fun reception(ctx: Context, r: SonPartage.Reception?): Notification = service(
        ctx, if (r == null) "Son partagé" else "Son de ${r.nomSource}",
        "Joué sur ce téléphone par le réseau maillé", arreter(ctx, ServiceReception::class.java, ID_RECEPTION),
    )

    fun emission(ctx: Context, c: SonPartage.Capture): Notification = service(
        ctx,
        when (c) {
            is SonPartage.Capture.Envoi -> "Son envoyé vers ${c.destination.nomCible}"
            is SonPartage.Capture.Preparation -> "Envoi du son vers ${c.nomCible}…"
            SonPartage.Capture.Arretee -> "Son partagé"
        },
        "Le son de ce téléphone part par le réseau maillé", arreter(ctx, ServiceEmission::class.java, ID_EMISSION),
    )

    /** Envoi lancé depuis un autre appareil : l'accord de capture se donne sur ce téléphone. */
    @android.annotation.SuppressLint("MissingPermission")
    fun demandeEnvoi(ctx: Context, d: SonPartage.Destination) {
        if (!Notifs.permises(ctx)) return
        Notifs.canaux(ctx)
        val i = Intent(ctx, MainActivity::class.java).setAction(ACTION_ENVOYER)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP)
            .putExtra(EXTRA_FLUX, d.flux).putExtra(EXTRA_CIBLE, d.cible).putExtra(EXTRA_NOM, d.nomCible)
            .putExtra(EXTRA_IP, d.ip).putExtra(EXTRA_PORT, d.port)
        val n = NotificationCompat.Builder(ctx, Notifs.CANAL_SON_DEMANDE)
            .setSmallIcon(R.drawable.ic_notif)
            .setContentTitle("Envoyer le son de ce téléphone")
            .setContentText("Touchez pour envoyer le son vers ${d.nomCible}")
            .setContentIntent(PendingIntent.getActivity(ctx, ID_DEMANDE, i, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT))
            .setAutoCancel(true)
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setCategory(NotificationCompat.CATEGORY_RECOMMENDATION)
            .build()
        NotificationManagerCompat.from(ctx).notify(ID_DEMANDE, n)
    }

    fun retirerDemande(ctx: Context) = NotificationManagerCompat.from(ctx).cancel(ID_DEMANDE)

    /** Le système a refusé de lancer la lecture en arrière-plan : la toucher rouvre l'appli et la relance. */
    @android.annotation.SuppressLint("MissingPermission")
    fun demandeEcoute(ctx: Context, r: SonPartage.Reception) {
        if (!Notifs.permises(ctx)) return
        Notifs.canaux(ctx)
        val n = NotificationCompat.Builder(ctx, Notifs.CANAL_SON_DEMANDE)
            .setSmallIcon(R.drawable.ic_notif)
            .setContentTitle("Son de ${r.nomSource}")
            .setContentText("Touchez pour écouter sur ce téléphone")
            .setContentIntent(ouvrirSon(ctx))
            .setAutoCancel(true)
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .build()
        NotificationManagerCompat.from(ctx).notify(ID_ECOUTE, n)
    }

    fun retirerEcoute(ctx: Context) = NotificationManagerCompat.from(ctx).cancel(ID_ECOUTE)

    /** Destination portée par l'intention de [demandeEnvoi]. */
    fun destination(i: Intent): SonPartage.Destination? {
        val flux = i.getStringExtra(EXTRA_FLUX) ?: return null
        val cible = i.getStringExtra(EXTRA_CIBLE) ?: return null
        val ip = i.getStringExtra(EXTRA_IP) ?: return null
        return SonPartage.Destination(flux, cible, i.getStringExtra(EXTRA_NOM) ?: cible, ip, i.getIntExtra(EXTRA_PORT, 4010))
    }
}
