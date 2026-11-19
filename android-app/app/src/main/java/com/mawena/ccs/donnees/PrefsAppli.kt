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

/** Réglages propres à l'appli : thème, taille du texte du terminal. */
class PrefsAppli(private val prefs: Preferences) {
    var theme: Theme
        get() = Theme.de(prefs.lire(THEME))
        set(t) = prefs.ecrire(THEME, t.valeur)

    /** Taille du texte du terminal en sp, bornée ([MIN_TERMINAL], [MAX_TERMINAL]). */
    var tailleTerminal: Int
        get() = (prefs.lire(TERMINAL)?.toIntOrNull() ?: NORMAL_TERMINAL).coerceIn(MIN_TERMINAL, MAX_TERMINAL)
        set(v) = prefs.ecrire(TERMINAL, v.coerceIn(MIN_TERMINAL, MAX_TERMINAL).toString())

    companion object {
        private const val THEME = "theme"
        private const val TERMINAL = "terminal-taille"
        const val MIN_TERMINAL = 8
        const val MAX_TERMINAL = 24
        const val NORMAL_TERMINAL = 12
    }
}
