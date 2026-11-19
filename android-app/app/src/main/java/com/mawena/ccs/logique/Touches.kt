package com.mawena.ccs.logique

/**
 * Saisie du terminal (`controlChar` de `web/terminal.js`) : Ctrl et Alt collants de la barre de
 * touches appliqués au caractère suivant, retours à la ligne du clavier en Entrée.
 */
object Touches {
    const val ECHAP = "\u001b"
    const val TAB = "\t"

    /** Ctrl + caractère → caractère de contrôle (Ctrl+C → 0x03, Ctrl+[ → Échap, Ctrl+? → DEL). */
    fun controle(c: Char): Char {
        if (c == ' ') return '\u0000'
        if (c == '?') return '\u007f'
        val code = c.uppercaseChar().code
        return if (code in 64..95) (code - 64).toChar() else c
    }

    /**
     * Texte tapé au clavier du téléphone, avec les touches collantes : Ctrl transforme le premier
     * caractère, Alt le précède d'Échap. Les « \n » du clavier deviennent « \r » (touche Entrée).
     */
    fun appliquer(texte: String, ctrl: Boolean, alt: Boolean): String {
        if (texte.isEmpty()) return texte
        val t = texte.replace("\r\n", "\r").replace('\n', '\r')
        val premier = if (ctrl) controle(t[0]).toString() else t[0].toString()
        return (if (alt) ECHAP else "") + premier + t.substring(1)
    }

    /** Touches de la barre (libellé, texte envoyé) ; les flèches suivent le mode « curseur application ». */
    enum class Fleche(val libelle: String, val lettre: Char) {
        Gauche("←", 'D'), Bas("↓", 'B'), Haut("↑", 'A'), Droite("→", 'C');

        fun sequence(modeApplication: Boolean, ctrl: Boolean = false, alt: Boolean = false): String {
            val mod = 1 + (if (alt) 2 else 0) + (if (ctrl) 4 else 0)
            return when {
                mod > 1 -> "\u001b[1;$mod$lettre"
                modeApplication -> "\u001bO$lettre"
                else -> "\u001b[$lettre"
            }
        }
    }

    val SYMBOLES = listOf("|", "~", "/", "-", "_", "*", "&", "$")

    /** Nombre de colonnes et de lignes qui tiennent dans une surface (au moins 4 × 2). */
    fun taille(largeurPx: Int, hauteurPx: Int, largeurCellule: Float, hauteurCellule: Int): Pair<Int, Int> {
        val cols = if (largeurCellule > 0) (largeurPx / largeurCellule).toInt() else 80
        val lignes = if (hauteurCellule > 0) hauteurPx / hauteurCellule else 24
        return cols.coerceIn(4, 999) to lignes.coerceIn(2, 999)
    }
}
