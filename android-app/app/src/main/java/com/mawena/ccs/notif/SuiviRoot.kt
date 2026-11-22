package com.mawena.ccs.notif

import android.content.Context
import com.mawena.ccs.logique.EtatRoot
import com.mawena.ccs.logique.Root
import com.mawena.ccs.logique.UsageRoot
import com.mawena.ccs.reseau.CcsClient
import com.mawena.ccs.reseau.EtatConnexion
import com.mawena.ccs.reseau.RpcException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.drop
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.put

/**
 * Mot de passe root demandé par la machine pilotée (phase 34) : suit `root.*` du pont pendant toute
 * la vie de l'appli (écrans et service de fond), relit `root.status` à chaque connexion pour
 * retrouver une demande en cours, et montre une notification quand l'appli n'est pas à l'écran.
 *
 * Le mot de passe ne fait que passer par [repondre] : jamais gardé, jamais écrit dans un journal.
 */
class SuiviRoot(private val ctx: Context, private val client: CcsClient, private val portee: CoroutineScope) {
    private val _etat = MutableStateFlow(EtatRoot())
    val etat: StateFlow<EtatRoot> = _etat.asStateFlow()

    private val _usages = MutableSharedFlow<UsageRoot>(extraBufferCapacity = 4)
    /** Commandes lancées avec le mot de passe gardé (avis discret à l'écran). */
    val usages: SharedFlow<UsageRoot> = _usages.asSharedFlow()

    /** Une activité de l'appli est visible : pas de notification, la fenêtre suffit. */
    @Volatile private var visible = false
    private var notifiee: String? = null

    init {
        portee.launch { client.evenements("root.ask").collect { d -> changer { Root.apresDemande(it, d, maintenant()) } } }
        portee.launch { client.evenements("root.resolved").collect { d -> changer { Root.apresReglee(it, d) } } }
        portee.launch { client.evenements("root.forgotten").collect { d -> changer { Root.apresOubli(it, d) } } }
        portee.launch {
            client.evenements("root.used").collect { d ->
                _usages.tryEmit(Root.lireUsage(d))
                actualiser()   // durée restante de la garde
            }
        }
        portee.launch { client.etat.collect { if (it is EtatConnexion.Connecte) actualiser() } }
        // autre machine pilotée : ce qu'on savait de l'ancienne ne vaut plus (relu à la connexion)
        portee.launch { client.machine.drop(1).collect { changer { EtatRoot() } } }
        portee.launch {
            while (true) {
                delay(TIC_MS)
                changer { Root.apresTemps(it, maintenant()) }
            }
        }
    }

    private fun maintenant() = System.currentTimeMillis()

    private fun changer(f: (EtatRoot) -> EtatRoot) {
        _etat.update(f)
        notifier()
    }

    /** Notification de la demande en cours, seulement hors de l'écran ; retirée sinon. */
    @Synchronized
    private fun notifier() {
        val d = _etat.value.demande
        val voulue = if (visible) null else d?.id
        if (voulue == notifiee) return
        notifiee?.let { Notifs.retirerRoot(ctx) }
        if (d != null && voulue != null) Notifs.root(ctx, d)
        notifiee = voulue
    }

    /** Appelé par l'activité (onStart / onStop). */
    fun premierPlan(oui: Boolean) {
        visible = oui
        notifier()
        if (oui) portee.launch { actualiser() }
    }

    /** `root.status` : garde et demande en cours (silencieux en cas d'échec). */
    suspend fun actualiser() {
        if (client.etat.value !is EtatConnexion.Connecte) return
        val r = runCatching { client.appeler("root.status").jsonObject }.getOrNull() ?: return
        changer { Root.apresStatut(it, r, maintenant()) }
    }

    /**
     * Envoie le mot de passe pour la demande `id`. Le paramètre est oublié dès l'appel construit ;
     * l'appelant vide son champ. Rend le message d'erreur à montrer, ou null si accepté.
     */
    suspend fun repondre(id: String, motDePasse: String): String? =
        envoyer(id, buildJsonObject { put("id", id); put("password", motDePasse) })

    suspend fun refuser(id: String): String? = envoyer(id, buildJsonObject { put("id", id); put("cancel", true) }, refus = true)

    private suspend fun envoyer(id: String, params: JsonObject, refus: Boolean = false): String? {
        changer { Root.envoiEnCours(it, id) }
        return try {
            val r = client.appeler("root.answer", params, DELAI_REPONSE_MS).jsonObject
            val ok = (r["ok"] as? JsonPrimitive)?.booleanOrNull == true
            val erreur = (r["error"] as? JsonPrimitive)?.contentOrNull
            changer { Root.apresReponse(it, id, ok || refus, erreur) }
            if (ok) portee.launch { actualiser() }
            if (ok || refus) null else erreur
        } catch (e: RpcException) {
            val texte = Root.texteErreur(e.code, e.message)
            changer {
                if (Root.demandePerdue(e.code)) Root.apresReponse(it, id, true, null) else Root.apresReponse(it, id, false, texte)
            }
            texte
        }
    }

    /** `root.forget` : efface le mot de passe gardé. Rend vrai s'il y en avait un. */
    suspend fun oublier(): Boolean {
        val r = client.appeler("root.forget").jsonObject
        changer { it.copy(garde = null) }
        return (r["had"] as? JsonPrimitive)?.booleanOrNull == true
    }

    private companion object {
        const val TIC_MS = 5_000L
        /** Vérification par `sudo -k -S -v` : jusqu'à 30 s côté pont, plus le relais. */
        const val DELAI_REPONSE_MS = 45_000L
    }
}
