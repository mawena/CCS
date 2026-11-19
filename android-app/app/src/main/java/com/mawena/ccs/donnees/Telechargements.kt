package com.mawena.ccs.donnees

import android.content.ContentValues
import android.content.Context
import android.os.Build
import android.os.Environment
import android.provider.MediaStore
import android.webkit.MimeTypeMap
import java.io.BufferedOutputStream
import java.io.File
import java.io.OutputStream

/**
 * Enregistre un fichier dans Téléchargements (repris de l'appli Flutter). Android 10 et plus :
 * MediaStore, sans permission ; Android 8 et 9 : dossier Téléchargements propre à l'appli.
 * Rend le nom réel (le système ajoute « (1) » si le nom est pris) ou le chemin sous Android 9.
 */
class Telechargements(private val context: Context) {
    fun enregistrer(nomBrut: String, type: String = "", ecrire: (OutputStream) -> Unit): String {
        val nom = nettoyer(nomBrut)
        val extension = nom.substringAfterLast('.', "").lowercase()
        val mime = type.ifEmpty {
            MimeTypeMap.getSingleton().getMimeTypeFromExtension(extension) ?: "application/octet-stream"
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            val resolveur = context.contentResolver
            val valeurs = ContentValues().apply {
                put(MediaStore.Downloads.DISPLAY_NAME, nom)
                put(MediaStore.Downloads.MIME_TYPE, mime)
                put(MediaStore.Downloads.IS_PENDING, 1)
            }
            val uri = resolveur.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, valeurs)
                ?: error("Dossier Téléchargements inaccessible")
            try {
                (resolveur.openOutputStream(uri) ?: error("Impossible d'écrire « $nom »")).use {
                    BufferedOutputStream(it).use(ecrire)
                }
            } catch (e: Exception) {
                runCatching { resolveur.delete(uri, null, null) }
                throw e
            }
            resolveur.update(uri, ContentValues().apply { put(MediaStore.Downloads.IS_PENDING, 0) }, null, null)
            resolveur.query(uri, arrayOf(MediaStore.Downloads.DISPLAY_NAME), null, null, null)?.use {
                if (it.moveToFirst()) return it.getString(0) ?: nom
            }
            return nom
        }
        val dossier = context.getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS) ?: File(context.filesDir, "Download")
        dossier.mkdirs()
        val base = nom.substringBeforeLast('.')
        val suffixe = if (extension.isEmpty()) "" else ".${nom.substringAfterLast('.')}"
        var fichier = File(dossier, nom)
        var n = 1
        while (fichier.exists()) fichier = File(dossier, "$base (${n++})$suffixe")
        BufferedOutputStream(fichier.outputStream()).use(ecrire)
        return fichier.absolutePath
    }

    companion object {
        fun nettoyer(nom: String): String =
            nom.replace(Regex("[/\\\\:*?\"<>|\\u0000-\\u001f]"), "_").trim().ifEmpty { "fichier" }
    }
}
