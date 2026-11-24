package com.mawena.ccs.son

import android.service.notification.NotificationListenerService

/**
 * Écouteur de notifications vide : il ne lit aucune notification. Il n'existe que parce que
 * l'accès aux notifications accordé à ce composant ouvre `MediaSessionManager.getActiveSessions`,
 * la liste des lecteurs du téléphone ([LecteursTelephone], phase 42).
 */
class EcouteurNotifications : NotificationListenerService() {
    override fun onListenerConnected() {
        super.onListenerConnected()
        quandConnecte?.invoke()
    }

    override fun onListenerDisconnected() {
        super.onListenerDisconnected()
        quandConnecte?.invoke()
    }

    companion object {
        /** Appelé quand le système (dé)lie l'écouteur : l'accès vient d'être accordé ou retiré. */
        @Volatile var quandConnecte: (() -> Unit)? = null
    }
}
