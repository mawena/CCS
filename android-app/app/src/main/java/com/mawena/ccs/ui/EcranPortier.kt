package com.mawena.ccs.ui

import android.annotation.SuppressLint
import android.graphics.Bitmap
import android.webkit.CookieManager
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.viewinterop.AndroidView
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull

/**
 * Connexion par Portier dans une vue web : la page de Portier ramène sur le serveur une fois la
 * connexion faite. À ce moment, on arrête la vue et on rend les cookies valables pour le serveur
 * (ceux de Portier, sur le domaine commun), que l'appli enverra elle-même au WebSocket.
 */
@OptIn(ExperimentalMaterial3Api::class)
@SuppressLint("SetJavaScriptEnabled")
@Composable
fun EcranPortier(adresse: String, connexion: String, fermer: () -> Unit, reussi: (String) -> Unit) {
    val hoteServeur = remember(adresse) { adresse.toHttpUrlOrNull()?.host }
    var progression by remember { mutableIntStateOf(0) }
    val fini = remember { booleanArrayOf(false) }

    fun revenu(url: String?): Boolean {
        val hote = url?.toHttpUrlOrNull()?.host ?: return false
        if (hote != hoteServeur || fini[0]) return hote == hoteServeur
        fini[0] = true
        val gestionnaire = CookieManager.getInstance()
        gestionnaire.flush()
        val cookies = gestionnaire.getCookie(adresse).orEmpty()
        reussi(cookies)
        return true
    }

    BackHandler(onBack = fermer)
    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Connexion par Portier") },
                navigationIcon = { IconButton(onClick = fermer) { Icon(Icons.Filled.Close, "Fermer") } },
            )
        },
    ) { marges ->
        Column(Modifier.fillMaxSize().then(Modifier.padding(marges))) {
            if (progression in 1..99) LinearProgressIndicator({ progression / 100f }, Modifier.fillMaxWidth())
            AndroidView(
                modifier = Modifier.fillMaxSize(),
                factory = { ctx ->
                    WebView(ctx).apply {
                        settings.javaScriptEnabled = true
                        settings.domStorageEnabled = true
                        CookieManager.getInstance().setAcceptCookie(true)
                        webViewClient = object : WebViewClient() {
                            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                                val url = request.url
                                if (url.scheme != "https" && url.scheme != "http") return true
                                if (request.isForMainFrame && revenu(url.toString())) {
                                    view.stopLoading()
                                    return true
                                }
                                return false
                            }

                            override fun onPageStarted(view: WebView, url: String?, favicon: Bitmap?) {
                                if (revenu(url)) view.stopLoading()
                            }
                        }
                        webChromeClient = object : android.webkit.WebChromeClient() {
                            override fun onProgressChanged(view: WebView, newProgress: Int) {
                                progression = newProgress
                            }
                        }
                        loadUrl(connexion)
                    }
                },
                onRelease = { it.destroy() },
            )
        }
    }
}
