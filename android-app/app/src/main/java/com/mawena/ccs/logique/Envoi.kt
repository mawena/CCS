package com.mawena.ccs.logique

import java.text.Normalizer

/** Logique d'envoi du chat (`deliver`, `send`, `isSlashCommand` de `web/chat.js`), sans Android. */
object Envoi {
    private val SLASH = Regex("^\\s*/[A-Za-z]")

    /** Commande de Claude Code (`/clear`, `/compact`…) : un `/` suivi d'une lettre, en tête. */
    fun estCommandeSlash(texte: String?) = texte != null && SLASH.containsMatchIn(texte)

    /** Commande du shell (`!ls`) : lancée dans le dossier du projet, pas envoyée à Claude. */
    fun commandeShell(texte: String, images: Int): String? {
        val t = texte.trim()
        return if (t.startsWith("!") && t.length > 1 && images == 0) t.substring(1).trim().ifEmpty { null } else null
    }

    /**
     * Message prêt à partir : `envoye` (texte pour Claude), `montre` (bulle), `commande` (envoyé
     * seul : la citation et les sorties `!` attendent le prochain message).
     */
    data class Pret(val envoye: String, val montre: String, val commande: Boolean)

    fun preparer(texte: String, images: Int, citation: Citation.Cite?, notesShell: List<String>): Pret {
        val commande = estCommandeSlash(texte) && images == 0
        if (commande) {
            val t = texte.trim()
            return Pret(t, t, true)
        }
        val notes = notesShell.joinToString("")
        val montre = if (citation != null) Citation.composer(citation.auteur, citation.texte, texte) else texte
        val envoye = if (citation != null) Citation.composer(citation.auteur, citation.texte, notes + texte) else notes + texte
        return Pret(envoye, montre, false)
    }

    /** Sortie d'une commande `!`, ajoutée en tête du prochain message pour Claude. */
    fun noteShell(commande: String, code: Int, sortie: String, tronquee: Boolean): String {
        val montre = sortie + if (tronquee) "\n[sortie tronquée]" else ""
        return "J'ai lancé `$commande` dans le dossier du projet (code $code) :\n```\n$montre\n```\n\n"
    }

    /** Commandes `/…` proposées pendant la saisie d'un `/nom` (début du nom, puis ailleurs dans le nom). */
    fun completer(saisie: String, commandes: List<CommandeSlash>, max: Int = 8): List<CommandeSlash> {
        if (!saisie.startsWith("/") || saisie.contains(' ') || saisie.contains('\n')) return emptyList()
        val q = saisie.substring(1).lowercase()
        val debut = commandes.filter { it.nom.lowercase().startsWith(q) }
        val ailleurs = if (q.isEmpty()) emptyList() else commandes.filter { it !in debut && it.nom.lowercase().contains(q) }
        return (debut + ailleurs).take(max)
    }

    /** Identifiant uuid v4 du message envoyé (étiquettes : le même en direct et dans le journal). */
    fun nouvelUuid(): String = java.util.UUID.randomUUID().toString()
}

/** Recherche dans le fil (`web/chat-search.js`) : sans accents ni majuscules, boucle aux extrémités. */
object Recherche {
    private val ACCENTS = Regex("\\p{Mn}+")

    fun plier(s: String): String = ACCENTS.replace(Normalizer.normalize(s, Normalizer.Form.NFD), "").lowercase()

    fun trouver(textes: List<String>, requete: String): List<Int> {
        val aiguille = plier(requete).trim()
        if (aiguille.isEmpty()) return emptyList()
        return textes.indices.filter { plier(textes[it]).contains(aiguille) }
    }

    fun pas(at: Int, nombre: Int, sens: Int): Int = if (nombre == 0) -1 else (at + sens + nombre) % nombre
}

/** Étiquettes des messages (`web/chat-tags.js`, nettoyage comme `message_tags.py`). */
object Etiquettes {
    const val MAX = 10
    const val MAX_CAR = 40

    fun nettoyer(t: String): String =
        t.replace(',', ' ').split(Regex("\\s+")).filter { it.isNotEmpty() }.joinToString(" ").take(MAX_CAR).trim()

    fun nettoyer(liste: List<String>): List<String> {
        val vues = HashSet<String>()
        return liste.map(::nettoyer).filter { it.isNotEmpty() && vues.add(it.lowercase()) }.take(MAX)
    }

    fun lire(texte: String): List<String> = nettoyer(texte.split(','))

    /** Étiquettes par ordre alphabétique (sans casse), messages dans l'ordre où ils ont été étiquetés. */
    fun parEtiquette(messages: Map<String, EntreeEtiquettes>): List<Pair<String, List<Pair<String, EntreeEtiquettes>>>> {
        val groupes = LinkedHashMap<String, Pair<String, MutableList<Pair<String, EntreeEtiquettes>>>>()
        for ((id, e) in messages.entries.sortedBy { it.value.ts }) {
            for (t in e.etiquettes) groupes.getOrPut(t.lowercase()) { t to ArrayList() }.second.add(id to e)
        }
        return groupes.entries.sortedBy { it.key }.map { it.value.first to it.value.second }
    }
}

/** Alerte de contexte lourd (`web/chat-context.js`). */
object AlerteContexte {
    const val PART_GARDEE = 0.2      // part du contexte gardée après `/compact` (comme context_alert.py)

    data class Decision(val lourd: Boolean, val gain: Long?)

    fun decider(ev: EvChat.Contexte, actif: Boolean, seuil: Long, dejaLourd: Boolean): Decision {
        if (ev.auto) return Decision(false, null)      // le pont compacte lui-même
        val dessus = actif && seuil > 0 && ev.total >= seuil
        return Decision(dessus, if (dessus && !dejaLourd) ev.total - (ev.total * PART_GARDEE).toLong() else null)
    }
}
