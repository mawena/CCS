package com.mawena.ccs.donnees

import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.builtins.serializer
import kotlinx.serialization.json.Json

/** Derniers dossiers ouverts par « Nouvelle session » (8 au plus, le plus récent d'abord). */
class DossiersRecents(private val prefs: Preferences) {
    private val format = ListSerializer(String.serializer())

    fun lire(): List<String> =
        prefs.lire(CLE)?.let { runCatching { Json.decodeFromString(format, it) }.getOrNull() } ?: emptyList()

    fun retenir(chemin: String) {
        if (chemin.isBlank()) return
        val liste = (listOf(chemin) + lire().filter { it != chemin }).take(MAX)
        prefs.ecrire(CLE, Json.encodeToString(format, liste))
    }

    private companion object {
        const val CLE = "dossiers-recents"
        const val MAX = 8
    }
}
