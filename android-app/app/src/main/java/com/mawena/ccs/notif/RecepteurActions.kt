package com.mawena.ccs.notif

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import androidx.core.app.NotificationManagerCompat
import com.mawena.ccs.CcsAppli
import com.mawena.ccs.reseau.RpcException
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeout
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

/** Actions rapides d'une notification d'autorisation : Autoriser ou Refuser (`chat.answer`). */
class RecepteurActions : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != ACTION_REPONDRE) return
        val chatId = intent.getStringExtra(Notifs.EXTRA_CHAT) ?: return
        val demande = intent.getStringExtra(EXTRA_DEMANDE) ?: return
        val decision = intent.getStringExtra(EXTRA_DECISION)?.takeIf { it == "allow" || it == "deny" } ?: return
        val ctx = context.applicationContext
        val depot = (ctx as CcsAppli).depot
        val fin = goAsync()
        depot.portee.launch {
            try {
                if (!depot.demarrerSiBesoin()) error("Pas connecté : ouvre l'appli.")
                withTimeout(DELAI_MS) {
                    depot.client.appeler("chat.answer", buildJsonObject {
                        put("chat_id", chatId); put("request_id", demande); put("decision", decision)
                    })
                }
                NotificationManagerCompat.from(ctx).cancel(chatId, Notifs.idAttente(demande))
            } catch (e: Exception) {
                val m = when (e) {
                    is RpcException -> e.message ?: "Le serveur a refusé."
                    is kotlinx.coroutines.TimeoutCancellationException -> "Pas de réponse du serveur."
                    else -> e.message ?: "Réponse impossible."
                }
                Notifs.echecReponse(ctx, chatId, demande, m, depot.veille.cible(chatId))
            } finally {
                fin.finish()
            }
        }
    }

    companion object {
        const val ACTION_REPONDRE = "com.mawena.ccs.action.REPONDRE"
        const val EXTRA_DEMANDE = "request_id"
        const val EXTRA_DECISION = "decision"
        /** goAsync laisse une dizaine de secondes au récepteur. */
        private const val DELAI_MS = 9_000L
    }
}
