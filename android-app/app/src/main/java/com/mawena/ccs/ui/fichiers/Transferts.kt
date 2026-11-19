package com.mawena.ccs.ui.fichiers

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.provider.OpenableColumns
import android.webkit.MimeTypeMap
import androidx.core.content.FileProvider
import com.mawena.ccs.donnees.Telechargements
import com.mawena.ccs.logique.Fichiers
import com.mawena.ccs.reseau.CcsClient
import com.mawena.ccs.reseau.MorceauFichier
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import java.io.File
import java.util.Base64

/**
 * Transferts par le RPC, morceau par morceau (`files.download`, `files.upload`), comme
 * `web/files-manage.js` : un message RPC est borné.
 */
object Transferts {
    /** Télécharge `chemin` du serveur dans `cible` ; `progres(reçu, total)`. */
    suspend fun telecharger(client: CcsClient, chemin: String, cible: File, progres: (Long, Long) -> Unit = { _, _ -> }) {
        withContext(Dispatchers.IO) {
            cible.outputStream().buffered().use { out ->
                var recu = 0L
                while (true) {
                    val r = client.appeler("files.download", MorceauFichier.serializer(), buildJsonObject {
                        put("path", chemin); put("offset", recu)
                    })
                    val octets = Base64.getDecoder().decode(r.data)
                    out.write(octets)
                    recu += octets.size
                    progres(recu, r.size)
                    if (r.done || octets.isEmpty()) break
                }
            }
        }
    }

    private fun dossierPartage(context: Context): File = File(context.cacheDir, "partage").apply { mkdirs() }

    /** Enregistre le fichier du serveur dans Téléchargements ; rend le nom donné par le système. */
    suspend fun versTelechargements(context: Context, client: CcsClient, chemin: String, progres: (Long, Long) -> Unit = { _, _ -> }): String {
        val tmp = File(dossierPartage(context), "telechargement-${System.nanoTime()}")
        try {
            telecharger(client, chemin, tmp, progres)
            return withContext(Dispatchers.IO) {
                Telechargements(context).enregistrer(Fichiers.nom(chemin)) { out -> tmp.inputStream().use { it.copyTo(out) } }
            }
        } finally {
            tmp.delete()
        }
    }

    /** Télécharge le fichier puis ouvre la feuille de partage d'Android. */
    suspend fun partager(context: Context, client: CcsClient, chemin: String, progres: (Long, Long) -> Unit = { _, _ -> }) {
        val dossier = dossierPartage(context)
        withContext(Dispatchers.IO) { dossier.listFiles()?.forEach { it.deleteRecursively() } }
        val sous = File(dossier, System.nanoTime().toString()).apply { mkdirs() }
        val f = File(sous, Telechargements.nettoyer(Fichiers.nom(chemin)))
        telecharger(client, chemin, f, progres)
        val uri = FileProvider.getUriForFile(context, "${context.packageName}.fichiers", f)
        val mime = MimeTypeMap.getSingleton().getMimeTypeFromExtension(Fichiers.extension(f.name)) ?: "application/octet-stream"
        val envoi = Intent(Intent.ACTION_SEND).apply {
            type = mime
            putExtra(Intent.EXTRA_STREAM, uri)
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        }
        context.startActivity(Intent.createChooser(envoi, "Partager « ${f.name} »").addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
    }

    data class Choisi(val uri: Uri, val nom: String, val taille: Long)

    fun decrire(context: Context, uri: Uri): Choisi {
        var nom = "fichier"
        var taille = -1L
        context.contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE), null, null, null)?.use { c ->
            if (c.moveToFirst()) {
                c.getString(0)?.let { nom = it }
                if (!c.isNull(1)) taille = c.getLong(1)
            }
        }
        return Choisi(uri, nom, taille)
    }

    /** Envoie le fichier choisi dans le dossier `dossier` du serveur (`replace` : écrase). */
    suspend fun envoyer(context: Context, client: CcsClient, dossier: String, f: Choisi, remplacer: Boolean, progres: (Long, Long) -> Unit = { _, _ -> }) {
        if (f.taille > Fichiers.MAX_TRANSFERT) error("Fichier trop gros pour être envoyé (200 Mo au plus).")
        withContext(Dispatchers.IO) {
            val entree = context.contentResolver.openInputStream(f.uri) ?: error("Impossible de lire « ${f.nom} ».")
            entree.buffered().use { e ->
                val tampon = ByteArray(Fichiers.MORCEAU)
                var envoye = 0L
                var suivant = lireTout(e, tampon)
                while (true) {
                    val n = suivant
                    val donnees = if (n > 0) tampon.copyOf(n) else ByteArray(0)
                    suivant = if (n == tampon.size) lireTout(e, tampon) else 0
                    val dernier = suivant <= 0
                    if (envoye + n > Fichiers.MAX_TRANSFERT) error("Fichier trop gros pour être envoyé (200 Mo au plus).")
                    client.appeler("files.upload", buildJsonObject {
                        put("dir", dossier); put("name", f.nom); put("offset", envoye)
                        put("data", Base64.getEncoder().encodeToString(donnees)); put("last", dernier); put("replace", remplacer)
                    }, delaiMs = 120_000)
                    envoye += n
                    progres(envoye, f.taille)
                    if (dernier) break
                }
            }
        }
    }

    /** Remplit `tampon` autant que possible ; rend le nombre d'octets lus (0 à la fin). */
    private fun lireTout(e: java.io.InputStream, tampon: ByteArray): Int {
        var n = 0
        while (n < tampon.size) {
            val k = e.read(tampon, n, tampon.size - n)
            if (k < 0) break
            n += k
        }
        return n
    }
}
