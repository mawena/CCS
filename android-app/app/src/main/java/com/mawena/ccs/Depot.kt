package com.mawena.ccs

import android.content.Context
import com.mawena.ccs.donnees.ChiffreurKeystore
import com.mawena.ccs.donnees.Coffre
import com.mawena.ccs.donnees.DossiersRecents
import com.mawena.ccs.donnees.PreferencesAndroid
import com.mawena.ccs.donnees.StockageAdresse
import com.mawena.ccs.reseau.ApiHttp
import com.mawena.ccs.reseau.CcsClient
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.update
import okhttp3.OkHttpClient
import java.util.concurrent.TimeUnit

/** Objets partagés par toute l'appli (un seul client WebSocket). */
class Depot(context: Context) {
    /** Contexte de l'application (synthèse vocale du chat). */
    val appli: Context = context.applicationContext
    val portee = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    val http: OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(15, TimeUnit.SECONDS)
        .readTimeout(60, TimeUnit.SECONDS)
        .pingInterval(25, TimeUnit.SECONDS)
        .build()
    val prefs = PreferencesAndroid(context.getSharedPreferences("ccs", Context.MODE_PRIVATE))
    val adresse = StockageAdresse(prefs)
    val coffre = Coffre(prefs, ChiffreurKeystore())
    val recents = DossiersRecents(prefs)
    val reglages = com.mawena.ccs.donnees.PrefsAppli(prefs)
    val api = ApiHttp(http)
    val client = CcsClient(http, portee, prefs = prefs)
    val terminaux = com.mawena.ccs.terminal.Terminaux(client)
    val veille = com.mawena.ccs.notif.Veille(context.applicationContext, client, portee)
    /** Mot de passe root demandé par la machine pilotée (phase 34). */
    val root = com.mawena.ccs.notif.SuiviRoot(context.applicationContext, client, portee)

    /** Oreille « bouton » de Jarvis (Plus → Parler à Jarvis, raccourci d'appli). */
    val jarvis = com.mawena.ccs.jarvis.OreilleJarvis(
        http, com.mawena.ccs.donnees.CoffreJarvis(prefs, ChiffreurKeystore("ccs-jarvis")),
        identifiants = { coffre.lire()?.takeIf { it.serveur == adresse.lire() } },
    )

    /** Ce qu'un partage Android remet à un chat (chat → saisie et images), pris par son écran. */
    val remises = kotlinx.coroutines.flow.MutableStateFlow<Map<String, Remise>>(emptyMap())

    fun remettre(chatId: String, r: Remise) = remises.update { it + (chatId to r) }

    fun prendreRemise(chatId: String): Remise? {
        var pris: Remise? = null
        remises.update { m -> pris = m[chatId]; m - chatId }
        return pris
    }

    /**
     * Démarre le client avec les identifiants gardés s'il est arrêté (service relancé par le
     * système, action d'une notification sans l'appli). Rend false sans identifiants.
     */
    @Synchronized
    fun demarrerSiBesoin(): Boolean {
        val i = coffre.lire()?.takeIf { it.serveur == adresse.lire() } ?: return false
        if (client.etat.value is com.mawena.ccs.reseau.EtatConnexion.Arrete) client.demarrer(i)
        return client.etat.value !is com.mawena.ccs.reseau.EtatConnexion.Refuse
    }
}

/** Saisie et images remises à un chat par un partage. */
class Remise(val texte: String, val images: List<com.mawena.ccs.ui.chat.PieceJointe>)
