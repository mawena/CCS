package com.mawena.ccs.logique

import org.junit.Assert.assertEquals
import org.junit.Test

class TouchesTest {
    @Test
    fun caracteresDeControle() {
        assertEquals('\u0003', Touches.controle('c'))
        assertEquals('\u0003', Touches.controle('C'))
        assertEquals('\u001b', Touches.controle('['))
        assertEquals('\u0000', Touches.controle(' '))
        assertEquals('\u007f', Touches.controle('?'))
        assertEquals('1', Touches.controle('1'))
    }

    @Test
    fun collantsEtEntree() {
        assertEquals("\u0004", Touches.appliquer("d", ctrl = true, alt = false))
        assertEquals("\u001bb", Touches.appliquer("b", ctrl = false, alt = true))
        assertEquals("\u0003lear", Touches.appliquer("clear", ctrl = true, alt = false))
        assertEquals("ls\r", Touches.appliquer("ls\n", ctrl = false, alt = false))
        assertEquals("a\rb", Touches.appliquer("a\r\nb", ctrl = false, alt = false))
        assertEquals("", Touches.appliquer("", ctrl = true, alt = true))
    }

    @Test
    fun flechesEtTaille() {
        assertEquals("\u001b[A", Touches.Fleche.Haut.sequence(false))
        assertEquals("\u001bOA", Touches.Fleche.Haut.sequence(true))
        assertEquals("\u001b[1;5D", Touches.Fleche.Gauche.sequence(false, ctrl = true))
        assertEquals(80 to 24, Touches.taille(800, 480, 10f, 20))
        assertEquals(4 to 2, Touches.taille(10, 10, 10f, 20))
    }
}
