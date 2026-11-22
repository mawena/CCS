package com.mawena.ccs.donnees

/** Apparence choisie dans l'appli (propre à ce téléphone, comme le thème du navigateur sur le web). */
enum class Theme(val valeur: String, val libelle: String) {
    Systeme("auto", "Automatique (celui du téléphone)"),
    Clair("light", "Clair"),
    Sombre("dark", "Sombre");

    companion object {
        fun de(valeur: String?): Theme = entries.firstOrNull { it.valeur == valeur } ?: Systeme
    }
}

/** Réglages propres à l'appli : thème, taille du texte du terminal, notifications, lecture à voix haute. */
class PrefsAppli(private val prefs: Preferences) {
    var theme: Theme
        get() = Theme.de(prefs.lire(THEME))
        set(t) = prefs.ecrire(THEME, t.valeur)

    /** Taille du texte du terminal en sp, bornée ([MIN_TERMINAL], [MAX_TERMINAL]). */
    var tailleTerminal: Int
        get() = (prefs.lire(TERMINAL)?.toIntOrNull() ?: NORMAL_TERMINAL).coerceIn(MIN_TERMINAL, MAX_TERMINAL)
        set(v) = prefs.ecrire(TERMINAL, v.coerceIn(MIN_TERMINAL, MAX_TERMINAL).toString())

    /** Notifications de l'appli (service de fond) : actives par défaut. */
    var notifications: Boolean
        get() = prefs.lire(NOTIFS) != "0"
        set(v) = prefs.ecrire(NOTIFS, if (v) "1" else "0")

    /** Chaque réponse de Claude terminée est lue à voix haute (chat affiché) : désactivé par défaut. */
    var lireReponses: Boolean
        get() = prefs.lire(LIRE) == "1"
        set(v) = prefs.ecrire(LIRE, if (v) "1" else null)

    /** La permission des notifications (Android 13+) a déjà été demandée une fois. */
    var permissionDemandee: Boolean
        get() = prefs.lire(PERMISSION) == "1"
        set(v) = prefs.ecrire(PERMISSION, if (v) "1" else null)

    companion object {
        private const val THEME = "theme"
        private const val NOTIFS = "notifications"
        private const val PERMISSION = "notifications-demandees"
        private const val TERMINAL = "terminal-taille"
        private const val LIRE = "lire-reponses"
        const val MIN_TERMINAL = 8
        const val MAX_TERMINAL = 24
        const val NORMAL_TERMINAL = 12
    }
}
