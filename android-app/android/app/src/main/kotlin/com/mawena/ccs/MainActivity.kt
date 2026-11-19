package com.mawena.ccs

import android.content.ContentValues
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.os.Handler
import android.os.Looper
import android.provider.MediaStore
import android.webkit.MimeTypeMap
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel
import java.io.BufferedOutputStream
import java.io.File
import java.io.OutputStream
import java.util.concurrent.Executors

/**
 * Enregistre dans Téléchargements les fichiers que le web remet au navigateur (liens `blob:` reçus
 * morceau par morceau côté Dart). Canal `com.mawena.ccs/telechargements` : `ouvrir`, `ecrire`,
 * `fermer`, `annuler`. Les écritures se font sur un fil à part, dans l'ordre d'arrivée.
 */
class MainActivity : FlutterActivity() {
    private val travail = Executors.newSingleThreadExecutor()
    private val principal = Handler(Looper.getMainLooper())

    // Lu et modifié seulement sur le fil `travail`.
    private val ouverts = HashMap<Int, Telechargement>()
    private var suivant = 0

    private class Telechargement(val flux: OutputStream, val uri: Uri?, val nom: String)

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, CANAL).setMethodCallHandler { appel, resultat ->
            travail.execute {
                try {
                    val reponse: Any? = when (appel.method) {
                        "ouvrir" -> ouvrir(appel.argument<String>("nom") ?: "", appel.argument<String>("type") ?: "")
                        "ecrire" -> {
                            val t = ouverts[appel.argument<Int>("id")] ?: throw IllegalStateException("Téléchargement inconnu")
                            t.flux.write(appel.argument<ByteArray>("donnees") ?: ByteArray(0))
                            null
                        }
                        "fermer" -> fermer(appel.argument<Int>("id") ?: -1)
                        "annuler" -> { annuler(appel.argument<Int>("id") ?: -1); null }
                        else -> { principal.post { resultat.notImplemented() }; return@execute }
                    }
                    principal.post { resultat.success(reponse) }
                } catch (e: Exception) {
                    principal.post { resultat.error("telechargement", e.message ?: e.toString(), null) }
                }
            }
        }
    }

    override fun onDestroy() {
        travail.execute { ouverts.keys.toList().forEach { annuler(it) } }
        travail.shutdown()
        super.onDestroy()
    }

    private fun ouvrir(nomBrut: String, type: String): Int {
        val nom = nomBrut.replace(Regex("[/\\\\:*?\"<>|\\u0000-\\u001f]"), "_").trim().ifEmpty { "fichier" }
        val extension = nom.substringAfterLast('.', "").lowercase()
        val mime = type.ifEmpty { MimeTypeMap.getSingleton().getMimeTypeFromExtension(extension) ?: "application/octet-stream" }
        val id = ++suivant
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            val valeurs = ContentValues().apply {
                put(MediaStore.Downloads.DISPLAY_NAME, nom)
                put(MediaStore.Downloads.MIME_TYPE, mime)
                put(MediaStore.Downloads.IS_PENDING, 1)
            }
            val uri = contentResolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, valeurs)
                ?: throw IllegalStateException("Dossier Téléchargements inaccessible")
            val flux = contentResolver.openOutputStream(uri)
                ?: throw IllegalStateException("Impossible d'écrire « $nom »")
            ouverts[id] = Telechargement(BufferedOutputStream(flux), uri, nom)
        } else {
            // Android 9 et avant : dossier Téléchargements propre à l'appli, sans permission de stockage.
            val dossier = getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS) ?: File(filesDir, "Download")
            dossier.mkdirs()
            var fichier = File(dossier, nom)
            var n = 1
            val base = nom.substringBeforeLast('.')
            val suffixe = if (extension.isEmpty()) "" else ".${nom.substringAfterLast('.')}"
            while (fichier.exists()) fichier = File(dossier, "$base (${n++})$suffixe")
            ouverts[id] = Telechargement(BufferedOutputStream(fichier.outputStream()), null, fichier.absolutePath)
        }
        return id
    }

    /** Termine le fichier ; rend son nom (ou son chemin sous Android 9 et avant). */
    private fun fermer(id: Int): String {
        val t = ouverts.remove(id) ?: throw IllegalStateException("Téléchargement inconnu")
        t.flux.close()
        val uri = t.uri ?: return t.nom
        contentResolver.update(uri, ContentValues().apply { put(MediaStore.Downloads.IS_PENDING, 0) }, null, null)
        // Le système renomme « nom (1).ext » si le nom est déjà pris : rendre le nom réel.
        contentResolver.query(uri, arrayOf(MediaStore.Downloads.DISPLAY_NAME), null, null, null)?.use {
            if (it.moveToFirst()) return it.getString(0) ?: t.nom
        }
        return t.nom
    }

    private fun annuler(id: Int) {
        val t = ouverts.remove(id) ?: return
        runCatching { t.flux.close() }
        t.uri?.let { runCatching { contentResolver.delete(it, null, null) } }
    }

    private companion object {
        const val CANAL = "com.mawena.ccs/telechargements"
    }
}
