package com.mawena.ccs.notif

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import com.mawena.ccs.MainActivity
import com.mawena.ccs.R
import com.mawena.ccs.logique.Veilleur.Action

/** Ce qu'il faut pour rouvrir un chat depuis une notification. */
data class CibleChat(val chatId: String, val cwd: String, val sessionId: String?, val chemin: String?, val titre: String)

/**
 * Notifications de l'appli : canaux séparés (« Fin de tour », « Attend ta réponse », et
 * « Connexion en arrière-plan » pour la notification discrète du service). Une notification par
 * chat et par demande (étiquette : l'identifiant du chat).
 */
object Notifs {
    const val CANAL_FIN = "fin-de-tour"
    const val CANAL_ATTENTE = "attente"
    const val CANAL_CONNEXION = "connexion"

    const val ID_SERVICE = 1
    private const val ID_FIN = 2

    const val ACTION_OUVRIR = "com.mawena.ccs.action.OUVRIR_CHAT"
    const val EXTRA_CHAT = "chat_id"
    const val EXTRA_CWD = "cwd"
    const val EXTRA_SESSION = "session_id"
    const val EXTRA_CHEMIN = "chemin"
    const val EXTRA_TITRE = "titre"

    fun canaux(ctx: Context) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val nm = ctx.getSystemService(NotificationManager::class.java) ?: return
        nm.createNotificationChannels(
            listOf(
                NotificationChannel(CANAL_FIN, "Fin de tour", NotificationManager.IMPORTANCE_DEFAULT).apply {
                    description = "Un chat a fini de travailler et attend la suite."
                },
                NotificationChannel(CANAL_ATTENTE, "Attend ta réponse", NotificationManager.IMPORTANCE_HIGH).apply {
                    description = "Claude demande une autorisation ou pose une question (avec un rappel après quelques minutes)."
                },
                NotificationChannel(CANAL_CONNEXION, "Connexion en arrière-plan", NotificationManager.IMPORTANCE_MIN).apply {
                    description = "Notification discrète tant que l'appli reste connectée pour te prévenir. Tu peux la masquer ici."
                    setShowBadge(false)
                },
            ),
        )
    }

    fun permises(ctx: Context): Boolean {
        if (Build.VERSION.SDK_INT >= 33 &&
            ContextCompat.checkSelfPermission(ctx, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
        ) return false
        return NotificationManagerCompat.from(ctx).areNotificationsEnabled()
    }

    fun idAttente(requestId: String) = 1000 + (requestId.hashCode() and 0x3fffffff)

    fun intentionOuvrir(ctx: Context, c: CibleChat): PendingIntent {
        val i = Intent(ctx, MainActivity::class.java).apply {
            action = ACTION_OUVRIR
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP or Intent.FLAG_ACTIVITY_CLEAR_TOP
            putExtra(EXTRA_CHAT, c.chatId)
            putExtra(EXTRA_CWD, c.cwd)
            putExtra(EXTRA_SESSION, c.sessionId)
            putExtra(EXTRA_CHEMIN, c.chemin)
            putExtra(EXTRA_TITRE, c.titre)
        }
        return PendingIntent.getActivity(ctx, c.chatId.hashCode(), i, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
    }

    private fun reponse(ctx: Context, c: CibleChat, requestId: String, decision: String): PendingIntent {
        val i = Intent(ctx, RecepteurActions::class.java).apply {
            action = RecepteurActions.ACTION_REPONDRE
            putExtra(EXTRA_CHAT, c.chatId)
            putExtra(RecepteurActions.EXTRA_DEMANDE, requestId)
            putExtra(RecepteurActions.EXTRA_DECISION, decision)
        }
        val code = (c.chatId + requestId + decision).hashCode()
        return PendingIntent.getBroadcast(ctx, code, i, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
    }

    /** Affiche une alerte du [com.mawena.ccs.logique.Veilleur] ; retire celles qui ne servent plus. */
    @android.annotation.SuppressLint("MissingPermission")
    fun appliquer(ctx: Context, a: Action, c: CibleChat?) {
        val nm = NotificationManagerCompat.from(ctx)
        when (a) {
            is Action.RetirerFin -> nm.cancel(a.chatId, ID_FIN)
            is Action.RetirerAttente -> nm.cancel(a.chatId, idAttente(a.requestId))
            is Action.RetirerTout -> {
                val nmS = ctx.getSystemService(NotificationManager::class.java)
                nmS?.activeNotifications?.filter { it.tag == a.chatId }?.forEach { nm.cancel(it.tag, it.id) }
            }
            is Action.FinTour, is Action.Attente, is Action.Rappel -> {
                if (c == null || !permises(ctx)) return
                nm.notify(a.chatId, idDe(a), construire(ctx, a, c))
            }
        }
    }

    private fun idDe(a: Action) = when (a) {
        is Action.Attente -> idAttente(a.requestId)
        is Action.Rappel -> idAttente(a.requestId)
        else -> ID_FIN
    }

    private fun construire(ctx: Context, a: Action, c: CibleChat): android.app.Notification {
        val (canal, texte) = when (a) {
            is Action.FinTour -> CANAL_FIN to a.resume
            is Action.Attente -> CANAL_ATTENTE to (if (a.question) "Question : " else "Autorisation : ") + a.texte
            is Action.Rappel -> CANAL_ATTENTE to "Toujours en attente depuis ${a.minutes} min — " + a.texte
            else -> CANAL_FIN to ""
        }
        val sousTitre = when (a) {
            is Action.FinTour -> "a terminé"
            is Action.Rappel -> "attend toujours ta réponse"
            else -> "attend ta réponse"
        }
        val b = NotificationCompat.Builder(ctx, canal)
            .setSmallIcon(R.drawable.ic_notif)
            .setContentTitle(c.titre)
            .setSubText(sousTitre)
            .setContentText(texte)
            .setStyle(NotificationCompat.BigTextStyle().bigText(texte))
            .setContentIntent(intentionOuvrir(ctx, c))
            .setAutoCancel(true)
            .setCategory(if (a is Action.FinTour) NotificationCompat.CATEGORY_STATUS else NotificationCompat.CATEGORY_REMINDER)
            .setPriority(if (a is Action.FinTour) NotificationCompat.PRIORITY_DEFAULT else NotificationCompat.PRIORITY_HIGH)
            .setWhen(System.currentTimeMillis())
            .setShowWhen(true)
        val demande = when (a) {
            is Action.Attente -> if (a.question) null else a.requestId
            is Action.Rappel -> if (a.question) null else a.requestId
            else -> null
        }
        if (demande != null) {
            b.addAction(0, "Autoriser", reponse(ctx, c, demande, "allow"))
            b.addAction(0, "Refuser", reponse(ctx, c, demande, "deny"))
        }
        return b.build()
    }

    /** Notification persistante du service (canal à importance minimale). */
    fun service(ctx: Context, connecte: Boolean): android.app.Notification {
        val ouvrir = PendingIntent.getActivity(
            ctx, 0, Intent(ctx, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
        return NotificationCompat.Builder(ctx, CANAL_CONNEXION)
            .setSmallIcon(R.drawable.ic_notif)
            .setContentTitle(if (connecte) "CCS connecté" else "CCS : reconnexion…")
            .setContentText("Te prévient quand un chat finit ou attend ta réponse.")
            .setContentIntent(ouvrir)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setSilent(true)
            .setShowWhen(false)
            .setPriority(NotificationCompat.PRIORITY_MIN)
            .setCategory(NotificationCompat.CATEGORY_SERVICE)
            .setForegroundServiceBehavior(NotificationCompat.FOREGROUND_SERVICE_DEFERRED)
            .build()
    }

    /** Remplace l'alerte d'une demande par un message d'échec (réponse rapide impossible). */
    @android.annotation.SuppressLint("MissingPermission")
    fun echecReponse(ctx: Context, chatId: String, requestId: String, message: String, c: CibleChat?) {
        if (!permises(ctx)) return
        val n = NotificationCompat.Builder(ctx, CANAL_ATTENTE)
            .setSmallIcon(R.drawable.ic_notif)
            .setContentTitle("Réponse non envoyée")
            .setContentText(message)
            .setContentIntent(
                c?.let { intentionOuvrir(ctx, it) } ?: PendingIntent.getActivity(
                    ctx, chatId.hashCode(), Intent(ctx, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
                    PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
                ),
            )
            .setAutoCancel(true)
            .build()
        NotificationManagerCompat.from(ctx).notify(chatId, idAttente(requestId), n)
    }
}
