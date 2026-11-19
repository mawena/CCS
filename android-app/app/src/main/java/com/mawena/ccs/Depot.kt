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
import okhttp3.OkHttpClient
import java.util.concurrent.TimeUnit

/** Objets partagés par toute l'appli (un seul client WebSocket). */
class Depot(context: Context) {
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
    val api = ApiHttp(http)
    val client = CcsClient(http, portee)
}
