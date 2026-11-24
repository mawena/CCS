package com.mawena.ccs.logique

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.Json

/**
 * Chat riche (phase 49), comme `web/chat-rich.js` : sons et vidéos reconnus à l'extension,
 * adresses des médias (https ou chemin du serveur), blocs ```ccs (JSON) en composants : choix,
 * formulaire, carte, cartes. Format : docs/chat-riche.md. Un bloc invalide rend `null`.
 */
object ChatRiche {
    val AUDIO = setOf("mp3", "ogg", "wav", "m4a", "opus")
    val VIDEO = setOf("mp4", "webm", "mov")
    /** Un fichier local lu par l'explorateur : 60 Mo au plus. */
    const val MAX_LOCAL = 60L * 1024 * 1024
    private val TYPES = setOf("choix", "formulaire", "carte", "cartes")
    private val EXTENSION = Regex("\\.([A-Za-z0-9]+)$")
    private val SCHEMA = Regex("^([A-Za-z][\\w+.-]*:|//)")

    enum class Media { Audio, Video }

    /** Son, vidéo ou `null` d'après l'extension (avant ?requête et #ancre). */
    fun media(src: String): Media? {
        val ext = EXTENSION.find(src.trim().split('?', '#').first())?.groupValues?.get(1)?.lowercase() ?: return null
        return when (ext) {
            in AUDIO -> Media.Audio
            in VIDEO -> Media.Video
            else -> null
        }
    }

    sealed class Source {
        data class Url(val url: String) : Source()
        data class Chemin(val chemin: String) : Source()
    }

    /**
     * Adresse https gardée telle quelle ; un chemin local (absolu, ou relatif au dossier de la
     * session) devient [Source.Chemin] normalisé ; le reste (javascript:, data:, http nu, //hôte…) : `null`.
     */
    fun resoudre(src: String, cwd: String): Source? {
        val s = src.trim()
        if (s.startsWith("https://", ignoreCase = true)) return Source.Url(s)
        if (s.isEmpty() || SCHEMA.containsMatchIn(s)) return null
        val parties = ArrayList<String>()
        for (p in (if (s.startsWith("/")) s else "$cwd/$s").split('/')) {
            when (p) {
                "", "." -> Unit
                ".." -> if (parties.isNotEmpty()) parties.removeAt(parties.size - 1)
                else -> parties.add(p)
            }
        }
        return if (parties.isEmpty()) null else Source.Chemin("/" + parties.joinToString("/"))
    }

    /** Option d'un choix ou action d'une carte : "texte", ou { label, message } / { label, lien }. */
    data class Option(val label: String, val message: String, val lien: String = "")

    data class Champ(
        val cle: String,
        val label: String,
        val type: String,
        val options: List<String>,
        val aide: String,
        val valeur: String?,
    )

    sealed class Composant
    data class Choix(val titre: String, val options: List<Option>) : Composant()
    data class Formulaire(val titre: String, val champs: List<Champ>, val envoyer: String) : Composant()
    data class Carte(
        val titre: String,
        /** Lien du titre, seulement en http(s), sinon vide. */
        val lien: String,
        val image: String,
        /** Prix (mis en avant) ou `null`. */
        val prix: String?,
        val sousTitre: String,
        val description: String,
        val actions: List<Option>,
    ) : Composant()
    data class Cartes(val items: List<Carte>) : Composant()

    /** Texte d'une valeur JSON comme `String(v)` du web ; absente ou nulle : "". */
    private fun str(v: JsonElement?): String = when (v) {
        null, JsonNull -> ""
        is JsonPrimitive -> v.content
        else -> v.toString()
    }

    /** Valeur « vraie » au sens du web (ni absente, ni nulle, ni "", ni 0, ni false). */
    private fun vrai(v: JsonElement?): Boolean = when (v) {
        null, JsonNull -> false
        is JsonPrimitive -> v.content.isNotEmpty() && (v.isString || (v.content != "0" && v.content != "false"))
        else -> true
    }

    private fun ou(a: JsonElement?, b: JsonElement?): String = if (vrai(a)) str(a) else str(b)

    fun estHttp(lien: String): Boolean = lien.startsWith("http://", ignoreCase = true) || lien.startsWith("https://", ignoreCase = true)

    private fun option(o: JsonElement): Option =
        if (o is JsonObject) Option(ou(o["label"], o["message"]), ou(o["message"], o["label"]), str(o["lien"]))
        else Option(str(o), str(o))

    private fun carte(o: JsonObject): Carte {
        val lien = str(o["lien"]).takeIf { estHttp(it) }.orEmpty()
        val prix = o["prix"]?.takeIf { it != JsonNull }?.let { str(it) }
        val actions = (o["actions"] as? JsonArray).orEmpty().map { option(it) }.filter { it.label.isNotEmpty() }
        return Carte(str(o["titre"]), lien, str(o["image"]), prix, str(o["sous_titre"]), str(o["description"]), actions)
    }

    /** Bloc ```ccs : le composant décrit s'il est valide (JSON, type connu), sinon `null`. */
    fun analyser(texte: String): Composant? {
        val element = try {
            Json.parseToJsonElement(texte)
        } catch (e: Exception) {
            return null
        }
        val spec = element as? JsonObject ?: return null
        val type = (spec["type"] as? JsonPrimitive)?.takeIf { it.isString }?.content
        if (type !in TYPES) return null
        return when (type) {
            "choix" -> {
                val options = (spec["options"] as? JsonArray)?.takeIf { it.isNotEmpty() } ?: return null
                Choix(ou(spec["titre"], spec["question"]), options.map { option(it) }.filter { it.label.isNotEmpty() })
            }
            "formulaire" -> {
                val champs = (spec["champs"] as? JsonArray)?.takeIf { it.isNotEmpty() } ?: return null
                Formulaire(
                    str(spec["titre"]),
                    champs.filterIsInstance<JsonObject>().map { f ->
                        val nom = f["nom"]
                        Champ(
                            cle = if (nom == null || nom == JsonNull) str(f["label"]) else str(nom),
                            label = ou(f["label"], f["nom"]),
                            type = str(f["type"]),
                            options = (f["options"] as? JsonArray).orEmpty().map { str(it) },
                            aide = str(f["aide"]),
                            valeur = f["valeur"]?.takeIf { it != JsonNull }?.let { str(it) },
                        )
                    },
                    ou(spec["envoyer"], JsonPrimitive("Envoyer")),
                )
            }
            "carte" -> if (vrai(spec["titre"])) carte(spec) else null
            else -> {
                val items = (spec["items"] as? JsonArray)?.takeIf { it.isNotEmpty() } ?: return null
                Cartes(items.filterIsInstance<JsonObject>().filter { vrai(it["titre"]) }.map { carte(it) })
                    .takeIf { it.items.isNotEmpty() }
            }
        }
    }

    /** Valeur de départ d'un champ : la sienne, sinon la première option d'une liste. */
    fun valeurInitiale(c: Champ): String = c.valeur ?: if (c.type == "liste") c.options.firstOrNull().orEmpty() else ""

    /** Message lisible envoyé par un formulaire : le titre puis « - Libellé : valeur » par champ rempli. */
    fun messageFormulaire(f: Formulaire, valeurs: Map<String, String>): String {
        val lignes = ArrayList<String>()
        if (f.titre.isNotEmpty()) lignes.add(f.titre)
        for (c in f.champs) {
            val v = valeurs[c.cle].orEmpty().trim()
            if (v.isNotEmpty()) lignes.add("- ${c.label} : $v")
        }
        return lignes.joinToString("\n")
    }
}
