package com.mawena.ccs

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.viewModels
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.runtime.getValue
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.mawena.ccs.donnees.Theme
import com.mawena.ccs.ui.ModeleAppli
import com.mawena.ccs.ui.Racine
import com.mawena.ccs.ui.ThemeCcs

class MainActivity : ComponentActivity() {
    private val modele: ModeleAppli by viewModels()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            val theme by modele.theme.collectAsStateWithLifecycle()
            val sombre = when (theme) {
                Theme.Clair -> false
                Theme.Sombre -> true
                Theme.Systeme -> isSystemInDarkTheme()
            }
            // icônes de la barre d'état lisibles avec le thème choisi dans l'appli
            androidx.compose.runtime.DisposableEffect(sombre) {
                val transparent = android.graphics.Color.TRANSPARENT
                enableEdgeToEdge(
                    statusBarStyle = androidx.activity.SystemBarStyle.auto(transparent, transparent) { sombre },
                    navigationBarStyle = androidx.activity.SystemBarStyle.auto(transparent, transparent) { sombre },
                )
                onDispose {}
            }
            ThemeCcs(sombre) { Racine(modele) }
        }
    }

    override fun onStart() {
        super.onStart()
        // Retour au premier plan : se reconnecter sans attendre la fin du délai.
        (application as CcsAppli).depot.client.reessayer()
    }
}
