package com.mawena.ccs.terminal

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** L'émulateur de Termux tourne aussi sur la JVM : séquences VT100/xterm et réponses au programme. */
class SessionTerminalTest {
    private val envoye = StringBuilder()
    private fun session() = SessionTerminal("t1", "ccs", "/home/c", { envoye.append(it) }, 20, 5)
    private fun ligne(s: SessionTerminal, n: Int) = s.emulateur.screen.getSelectedText(0, n, 19, n).trimEnd()

    @Test
    fun texteCouleursEtEffacement() {
        val s = session()
        s.recevoir("\u001b[31mrouge\u001b[0m\r\nbleu")
        assertEquals("rouge", ligne(s, 0))
        assertEquals("bleu", ligne(s, 1))
        assertEquals(1, s.emulateur.cursorRow)
        assertEquals(4, s.emulateur.cursorCol)
        s.recevoir("\u001b[2J\u001b[H")
        assertEquals("", ligne(s, 0))
        assertEquals(0, s.emulateur.cursorRow)
    }

    @Test
    fun reponsesAuProgramme() {
        val s = session()
        s.recevoir("\u001b[3;4H\u001b[6n")                       // position du curseur demandée
        assertEquals("\u001b[3;4R", envoye.toString())
        envoye.clear()
        s.recevoir("\u001b[?2004h")
        s.coller("ls")
        assertEquals("\u001b[200~ls\u001b[201~", envoye.toString())
    }

    @Test
    fun ecranAlternatifEtDefilement() {
        val s = session()
        repeat(12) { s.recevoir("ligne $it\r\n") }
        assertTrue(s.emulateur.screen.activeTranscriptRows > 0)
        assertTrue(s.texte().contains("ligne 0"))
        s.recevoir("\u001b[?1049h")
        assertTrue(s.emulateur.isAlternateBufferActive)
        s.recevoir("\u001b[?1049l")
        assertFalse(s.emulateur.isAlternateBufferActive)
    }

    @Test
    fun tailleRattachementEtFin() {
        val s = session()
        var vu = 0
        s.ecouter { vu++ }
        assertTrue(s.redimensionner(40, 10))
        assertFalse(s.redimensionner(40, 10))
        assertEquals(40, s.emulateur.mColumns)
        s.recevoir("avant")
        s.remplacer("après")
        assertEquals("après", s.emulateur.screen.getSelectedText(0, 0, 39, 0).trimEnd())
        assertEquals(40, s.emulateur.mColumns)
        s.recevoir("\u001b]0;mon titre\u0007")
        assertEquals("mon titre", s.titre)
        s.terminer(0)
        assertEquals(0, s.fin)
        envoye.clear()
        s.coller("x")
        assertEquals("", envoye.toString())
        assertTrue(vu > 3)
    }
}
