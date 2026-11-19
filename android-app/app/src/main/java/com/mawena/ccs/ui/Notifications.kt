package com.mawena.ccs.ui

import android.Manifest
import android.content.Context
import android.content.Intent
import android.os.Build
import android.provider.Settings
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.ui.platform.LocalContext
import com.mawena.ccs.notif.Notifs
import com.mawena.ccs.notif.ServiceVeille

/**
 * Demande la permission des notifications (Android 13+) une seule fois, au premier chat ouvert :
 * c'est là qu'on comprend à quoi elles servent. Ensuite, le choix se refait dans les réglages.
 */
@Composable
fun DemandeNotifications(modele: ModeleAppli) {
    val ctx = LocalContext.current
    val lanceur = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { ServiceVeille.appliquer(ctx) }
    LaunchedEffect(Unit) {
        val r = modele.depot.reglages
        if (Build.VERSION.SDK_INT < 33 || r.permissionDemandee || !r.notifications || Notifs.permises(ctx)) return@LaunchedEffect
        r.permissionDemandee = true
        lanceur.launch(Manifest.permission.POST_NOTIFICATIONS)
    }
}

/** Réglages des notifications de l'appli dans Android (canaux, permission refusée pour de bon). */
fun ouvrirReglagesNotifications(ctx: Context) {
    val i = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
        Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS).putExtra(Settings.EXTRA_APP_PACKAGE, ctx.packageName)
    } else {
        Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, android.net.Uri.fromParts("package", ctx.packageName, null))
    }
    runCatching { ctx.startActivity(i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) }
}
