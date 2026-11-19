package com.mawena.ccs.donnees

import android.content.SharedPreferences
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import java.security.KeyStore
import java.util.Base64
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/**
 * Ce qui ouvre le WebSocket. Mode normal : `jeton` d'appareil (appairage par `/api/pair`), envoyé en
 * `Authorization: Bearer`. Mode Portier : `cookies` de Portier récupérés après la connexion dans la
 * vue web, envoyés tels quels en en-tête `Cookie`.
 */
@Serializable
data class Identifiants(
    val serveur: String,
    val utilisateur: String,
    val jeton: String? = null,
    val cookies: String? = null,
) {
    val portier: Boolean get() = jeton == null && cookies != null
}

interface Chiffreur {
    fun chiffrer(clair: ByteArray): ByteArray
    fun dechiffrer(chiffre: ByteArray): ByteArray
}

/** AES-256-GCM avec une clé du Keystore d'Android (jamais exportable) ; sortie = IV (12 o) + chiffré. */
class ChiffreurKeystore(private val alias: String = "ccs-identifiants") : Chiffreur {
    private fun cle(): SecretKey {
        val ks = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (ks.getKey(alias, null) as? SecretKey)?.let { return it }
        val gen = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore")
        gen.init(
            KeyGenParameterSpec.Builder(alias, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setKeySize(256)
                .build(),
        )
        return gen.generateKey()
    }

    override fun chiffrer(clair: ByteArray): ByteArray {
        val c = Cipher.getInstance(TRANSFORMATION).apply { init(Cipher.ENCRYPT_MODE, cle()) }
        return c.iv + c.doFinal(clair)
    }

    override fun dechiffrer(chiffre: ByteArray): ByteArray {
        val c = Cipher.getInstance(TRANSFORMATION)
        c.init(Cipher.DECRYPT_MODE, cle(), GCMParameterSpec(128, chiffre, 0, IV))
        return c.doFinal(chiffre, IV, chiffre.size - IV)
    }

    private companion object {
        const val TRANSFORMATION = "AES/GCM/NoPadding"
        const val IV = 12
    }
}

/** Identifiants gardés chiffrés dans les préférences. Illisibles (clé perdue…) = pas d'identifiants. */
class Coffre(private val prefs: Preferences, private val chiffreur: Chiffreur) {
    private val json = Json { ignoreUnknownKeys = true }

    fun lire(): Identifiants? = runCatching {
        val brut = prefs.lire(CLE) ?: return null
        val clair = chiffreur.dechiffrer(Base64.getDecoder().decode(brut))
        json.decodeFromString(Identifiants.serializer(), clair.decodeToString())
    }.getOrNull()

    fun ecrire(identifiants: Identifiants?) {
        if (identifiants == null) {
            prefs.ecrire(CLE, null)
            return
        }
        val clair = json.encodeToString(Identifiants.serializer(), identifiants).encodeToByteArray()
        prefs.ecrire(CLE, Base64.getEncoder().encodeToString(chiffreur.chiffrer(clair)))
    }

    private companion object {
        const val CLE = "identifiants"
    }
}

class PreferencesAndroid(private val sp: SharedPreferences) : Preferences {
    override fun lire(cle: String): String? = sp.getString(cle, null)
    override fun ecrire(cle: String, valeur: String?) {
        sp.edit().apply { if (valeur == null) remove(cle) else putString(cle, valeur) }.commit()
    }
}
