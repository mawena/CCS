package com.mawena.ccs.terminal

import com.termux.terminal.TerminalColors
import com.termux.terminal.TerminalEmulator
import com.termux.terminal.TerminalOutput
import com.termux.terminal.TerminalSession
import com.termux.terminal.TerminalSessionClient
import java.util.Properties

/**
 * Un terminal du pont (`bridge_term.py`) affiché par l'émulateur de Termux (`TerminalEmulator` :
 * VT100/xterm, couleurs 256 et 24 bits, écran alternatif, défilement, modes du curseur). Le texte
 * reçu par `term.output` y est versé ; ce que l'émulateur doit répondre au programme (position du
 * curseur, collage entre crochets…) part par [envoyer], comme la saisie.
 *
 * À n'utiliser que depuis le fil principal (l'émulateur et le dessin ne sont pas synchronisés).
 */
class SessionTerminal(
    val id: String,
    nom: String,
    val cwd: String,
    private val envoyer: (String) -> Unit,
    colonnes: Int = 80,
    lignes: Int = 24,
) {
    var nom: String = nom
        private set

    /** Titre donné par le programme (séquence OSC 0/2), sinon le nom. */
    var titre: String = nom
        private set

    /** Code de sortie quand le shell s'est arrêté (ou −1 : le pont ne connaît plus ce terminal). */
    var fin: Int? = null
        private set

    var colonnes = colonnes
        private set
    var lignes = lignes
        private set

    private val ecouteurs = mutableListOf<() -> Unit>()
    var surCopie: ((String) -> Unit)? = null
    var surSonnerie: (() -> Unit)? = null

    private val sortie = object : TerminalOutput() {
        override fun write(data: ByteArray, offset: Int, count: Int) {
            if (fin == null) envoyer(String(data, offset, count, Charsets.UTF_8))
        }
        override fun titleChanged(oldTitle: String?, newTitle: String?) {
            titre = newTitle?.takeIf { it.isNotBlank() } ?: nom
            prevenir()
        }
        override fun onCopyTextToClipboard(text: String?) { text?.let { surCopie?.invoke(it) } }
        override fun onPasteTextFromClipboard() = Unit
        override fun onBell() { surSonnerie?.invoke() }
        override fun onColorsChanged() = prevenir()
    }

    var emulateur: TerminalEmulator = nouvelEmulateur()
        private set

    private fun nouvelEmulateur() = TerminalEmulator(sortie, colonnes, lignes, LIGNES_GARDEES, Client)

    /** Texte reçu du pont. */
    fun recevoir(texte: String) {
        if (texte.isEmpty()) return
        val o = texte.toByteArray(Charsets.UTF_8)
        emulateur.append(o, o.size)
        prevenir()
    }

    /** Rattachement : écran remis à neuf, puis la fin de la sortie gardée par le pont. */
    fun remplacer(texte: String) {
        emulateur = nouvelEmulateur()
        recevoir(texte)
        prevenir()
    }

    fun redimensionner(c: Int, l: Int): Boolean {
        if (c == colonnes && l == lignes) return false
        colonnes = c
        lignes = l
        emulateur.resize(c, l)
        prevenir()
        return true
    }

    fun terminer(code: Int) {
        if (fin != null) return
        recevoir(if (code < 0) "\r\n[terminal fermé]\r\n" else "\r\n[terminé, code $code]\r\n")
        fin = code
        prevenir()
    }

    /** Collage : entre crochets si le programme l'a demandé (mode 2004), comme un vrai terminal. */
    fun coller(texte: String) {
        if (fin == null) emulateur.paste(texte)
    }

    /** Tout le texte (écran et historique), pour « Copier ». */
    fun texte(): String = emulateur.screen.transcriptText

    fun ecouter(f: () -> Unit) { ecouteurs.add(f) }
    fun oublier(f: () -> Unit) { ecouteurs.remove(f) }
    private fun prevenir() = ecouteurs.toList().forEach { it() }

    /** L'émulateur ne parle à ce client que pour journaliser et pour le style du curseur. */
    private object Client : TerminalSessionClient {
        override fun onTextChanged(changedSession: TerminalSession) = Unit
        override fun onTitleChanged(changedSession: TerminalSession) = Unit
        override fun onSessionFinished(finishedSession: TerminalSession) = Unit
        override fun onCopyTextToClipboard(session: TerminalSession, text: String?) = Unit
        override fun onPasteTextFromClipboard(session: TerminalSession?) = Unit
        override fun onBell(session: TerminalSession) = Unit
        override fun onColorsChanged(session: TerminalSession) = Unit
        override fun onTerminalCursorStateChange(state: Boolean) = Unit
        override fun getTerminalCursorStyle(): Int? = null
        override fun logError(tag: String?, message: String?) = Unit
        override fun logWarn(tag: String?, message: String?) = Unit
        override fun logInfo(tag: String?, message: String?) = Unit
        override fun logDebug(tag: String?, message: String?) = Unit
        override fun logVerbose(tag: String?, message: String?) = Unit
        override fun logStackTraceWithMessage(tag: String?, message: String?, e: Exception?) = Unit
        override fun logStackTrace(tag: String?, e: Exception?) = Unit
    }

    companion object {
        const val LIGNES_GARDEES = 3000

        /** Couleurs du terminal sombre de la version web (fond #1e1e22, texte #f2f2f5). */
        init {
            TerminalColors.COLOR_SCHEME.updateWith(
                Properties().apply {
                    setProperty("background", "#1e1e22")
                    setProperty("foreground", "#f2f2f5")
                    setProperty("cursor", "#f2f2f5")
                },
            )
        }
    }
}
