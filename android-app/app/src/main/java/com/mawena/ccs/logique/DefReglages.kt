package com.mawena.ccs.logique

import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.doubleOrNull

/**
 * Réglages du serveur (`web/settings.js`, `web/pages-phone.js`) : mêmes groupes, mêmes libellés,
 * mêmes bornes. Chaque valeur part seule par `settings.set` ; le pont la valide à son tour.
 */
object DefReglages {
    sealed interface Genre {
        data object Booleen : Genre
        data class Nombre(val min: Double, val max: Double, val entier: Boolean = false) : Genre
        data object Heure : Genre
        data object Texte : Genre
        data class Choix(val options: List<Pair<String, String>>) : Genre
    }

    data class Def(val chemin: String, val libelle: String, val genre: Genre, val aide: String = "")

    data class Groupe(val titre: String, val reglages: List<Def>, val texte: String = "")

    private val B = Genre.Booleen
    private val H = Genre.Heure
    private fun n(min: Number, max: Number, entier: Boolean = false) = Genre.Nombre(min.toDouble(), max.toDouble(), entier)

    val DEHORS = listOf("notify" to "Notification", "resume" to "Relance en arrière-plan")
    val DROITS = listOf(
        "manual" to "Manuel", "acceptEdits" to "Accepter les modifications", "plan" to "Plan",
        "auto" to "Auto", "dontAsk" to "Sans question", "bypassPermissions" to "Aucune vérification",
    )

    /** Téléphone (ntfy) : en tête, comme sur le web. */
    val TELEPHONE = Groupe(
        "Téléphone (notifications ntfy)",
        listOf(
            Def("phone.enabled", "Envoyer les notifications", B),
            Def("phone.server", "Serveur ntfy", Genre.Texte, "https://ntfy.sh par défaut"),
            Def("phone.topic", "Canal secret", Genre.Texte, "Celui qui le connaît peut lire tes notifications : ne le partage pas."),
            Def("phone.events.waiting", "Une session attend ma réponse", B),
            Def("phone.events.task", "Une tâche se termine", B),
            Def("phone.events.switch", "Bascule de compte", B),
            Def("phone.events.exhausted", "Tous les comptes sont épuisés", B),
            Def("phone.show_content", "Montrer la commande", B,
                "La notification d'autorisation affiche la commande exacte (sinon : le type et le projet seulement)."),
        ),
        "Reçois sur ton téléphone « attend ta réponse », tâche finie, bascule. Installe l'application ntfy, puis scanne le QR code.",
    )

    val GROUPES = listOf(
        Groupe("Bascule automatique", listOf(
            Def("auto_switch.enabled", "Basculer avant la limite", B),
            Def("auto_switch.threshold", "Seuil de bascule (%)", n(1, 100)),
            Def("auto_switch.target_max_session", "Session maximale du compte visé (%)", n(0, 100)),
            Def("auto_switch.target_max_weekly", "Semaine maximale du compte visé (%)", n(0, 100)),
        )),
        Groupe("Orchestrateur", listOf(
            Def("orchestrator.enabled", "Orchestrateur des fenêtres de 5 h", B),
            Def("orchestrator.active_hours.start", "Début de la plage active", H),
            Def("orchestrator.active_hours.end", "Fin de la plage active", H),
            Def("orchestrator.reserve_points", "Réserve (points)", n(0, 100)),
        )),
        Groupe("Alertes", listOf(
            Def("alerts.enabled", "Alertes", B),
            Def("alerts.eta_minutes", "Prévenir avant la limite (minutes)", n(1, 1440)),
            Def("alerts.weekly_forecast", "Prévision de la semaine", B),
            Def("alerts.waiting_reminder", "Rappel quand une session attend ma réponse", B),
            Def("alerts.waiting_reminder_min", "Rappel après (minutes)", n(1, 1440)),
            Def("context_alert.enabled", "Alerte de contexte lourd", B),
            Def("context_alert.threshold_tokens", "Seuil du contexte lourd (jetons)", n(1000, 10_000_000, true)),
            Def("context_alert.auto_compact", "Compacter automatiquement les chats au-delà du seuil", B),
            Def("budget.enabled", "Budgets par projet", B),
        )),
        Groupe("Ne pas déranger", listOf(
            Def("alerts.quiet.enabled", "Plage de silence", B),
            Def("alerts.quiet.start", "Début", H),
            Def("alerts.quiet.end", "Fin", H),
            Def("alerts.quiet.allow_waiting", "Prévenir quand même si une session attend ma réponse", B),
        )),
        Groupe("Chat et sessions", listOf(
            Def("chat.rights", "Droits des nouveaux chats", Genre.Choix(DROITS)),
            Def("limit_resume.enabled", "Relancer les conversations bloquées quand la limite est levée", B),
            Def("limit_resume.outside", "Conversation fermée hors de CCS, à la levée", Genre.Choix(DEHORS)),
            Def("chat.auto_clear", "Effacement automatique : Claude vide la conversation (/clear) en fin de sujet", B),
            Def("chat.idle_suspend_min", "Mise en veille d'un chat inactif (minutes, 0 = jamais)", n(0, 1440, true)),
            Def("sessions.idle_hours", "Session inactive après (heures)", n(0.01, 720)),
        )),
        Groupe("Git", listOf(
            Def("git.fetch_minutes", "Fetch automatique (minutes, 0 = jamais)", n(0, 1440, true)),
            Def("git.layout", "Disposition de la page Git (bureau)", Genre.Choix(listOf("A" to "A", "B" to "B", "C" to "C"))),
            Def("git.avatars", "Avatars des auteurs (bureau)", B),
        )),
        Groupe("Tâches de nuit", listOf(
            Def("tasks.enabled", "Lancer les tâches", B),
            Def("tasks.night.start", "Début de la nuit", H),
            Def("tasks.night.end", "Fin de la nuit", H),
            Def("tasks.max_attempts", "Relances après une limite atteinte", n(1, 10, true)),
        )),
        Groupe("Archive des conversations", listOf(
            Def("archive.enabled", "Archiver les conversations", B),
            Def("archive.idle_days", "Archiver après (jours inactifs)", n(0, 3650, true)),
            Def("archive.max_age_days", "Supprimer après (jours, 0 = jamais)", n(0, 36500, true)),
        )),
        Groupe("Mises à jour", listOf(Def("updates.enabled", "Chercher les nouvelles versions", B))),
    )

    /** Valeur au chemin `a.b.c` des réglages, ou null. */
    fun lire(reglages: JsonObject, chemin: String): JsonElement? {
        var e: JsonElement? = reglages
        for (k in chemin.split('.')) e = (e as? JsonObject)?.get(k) ?: return null
        return e
    }

    /** Copie des réglages avec `valeur` au chemin (après un enregistrement réussi). */
    fun ecrire(reglages: JsonObject, chemin: String, valeur: JsonElement): JsonObject {
        val cles = chemin.split('.')
        fun dans(o: JsonObject, i: Int): JsonObject {
            val k = cles[i]
            val v = if (i == cles.size - 1) valeur else dans(o[k] as? JsonObject ?: JsonObject(emptyMap()), i + 1)
            return JsonObject(o + (k to v))
        }
        return dans(reglages, 0)
    }

    fun booleen(e: JsonElement?): Boolean = (e as? JsonPrimitive)?.booleanOrNull ?: false

    /** Texte à montrer dans un champ (nombre sans « .0 » inutile). */
    fun texte(e: JsonElement?): String {
        val p = e as? JsonPrimitive ?: return ""
        if (p.isString) return p.content
        val d = p.doubleOrNull ?: return p.contentOrNull.orEmpty()
        return if (d == Math.floor(d) && !d.isInfinite() && kotlin.math.abs(d) < 1e15) d.toLong().toString() else d.toString()
    }

    /** Nombre saisi (virgule ou point), vérifié contre les bornes : (valeur, erreur). */
    fun nombre(saisi: String, g: Genre.Nombre): Pair<Number?, String?> {
        val d = saisi.trim().replace(',', '.').toDoubleOrNull() ?: return null to "Entre un nombre."
        if (d < g.min || d > g.max) return null to "Entre ${texte(JsonPrimitive(g.min))} et ${texte(JsonPrimitive(g.max))}."
        if (g.entier) {
            if (d != Math.floor(d)) return null to "Entre un nombre entier."
            return d.toLong() to null
        }
        return (if (d == Math.floor(d)) d.toLong() else d) to null
    }

    private val HEURE = Regex("^([01]?\\d|2[0-3]):([0-5]\\d)$")

    /** Heure `H:MM` ou `HH:MM` → `HH:MM`, ou null. */
    fun heure(saisi: String): String? {
        val m = HEURE.matchEntire(saisi.trim()) ?: return null
        return m.groupValues[1].padStart(2, '0') + ":" + m.groupValues[2]
    }
}
