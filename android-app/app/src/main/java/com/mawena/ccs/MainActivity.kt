package com.mawena.ccs

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.viewModels
import com.mawena.ccs.ui.ModeleAppli
import com.mawena.ccs.ui.Racine
import com.mawena.ccs.ui.ThemeCcs

class MainActivity : ComponentActivity() {
    private val modele: ModeleAppli by viewModels()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent { ThemeCcs { Racine(modele) } }
    }

    override fun onStart() {
        super.onStart()
        // Retour au premier plan : se reconnecter sans attendre la fin du délai.
        (application as CcsAppli).depot.client.reessayer()
    }
}
