package com.mawena.ccs

import android.app.Application
import android.net.ConnectivityManager
import android.net.Network

class CcsAppli : Application() {
    lateinit var depot: Depot
        private set

    override fun onCreate() {
        super.onCreate()
        depot = Depot(this)
        // Réseau revenu : nouvel essai de connexion sans attendre la fin du délai.
        getSystemService(ConnectivityManager::class.java)?.registerDefaultNetworkCallback(
            object : ConnectivityManager.NetworkCallback() {
                override fun onAvailable(network: Network) = depot.client.reessayer()
            },
        )
    }
}
