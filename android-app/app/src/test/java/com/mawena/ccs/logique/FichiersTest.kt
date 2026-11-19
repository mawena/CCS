package com.mawena.ccs.logique

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class FichiersTest {
    @Test
    fun chemins() {
        assertEquals("b.txt", Fichiers.nom("/a/b.txt"))
        assertEquals("a", Fichiers.nom("/a/"))
        assertEquals("/a", Fichiers.parent("/a/b"))
        assertEquals("/", Fichiers.parent("/a"))
        assertEquals("/a/b/c", Fichiers.joindre("/a/b/", "c"))
        assertEquals("/a", Fichiers.joindre("/a", ""))
        assertEquals("", Fichiers.relatif("/home/c", "/home/c"))
        assertEquals("x/y", Fichiers.relatif("/home/c/x/y", "/home/c"))
        assertNull(Fichiers.relatif("/home/cc/x", "/home/c"))
        assertTrue(Fichiers.sous("/srv/site", "/srv"))
        assertFalse(Fichiers.sous("/srvx", "/srv"))
    }

    @Test
    fun racineEtAriane() {
        val racines = listOf("/home/c", "/var/www", "/srv")
        assertEquals("/var/www", Fichiers.racineDe("/var/www/site/a", racines, "/home/c"))
        assertEquals("/home/c", Fichiers.racineDe("/etc", racines, "/home/c"))
        assertEquals(
            listOf("Personnel" to "/home/c", "Work" to "/home/c/Work", "ccs" to "/home/c/Work/ccs"),
            Fichiers.ariane("/home/c/Work/ccs", "/home/c", "/home/c"),
        )
        assertEquals(listOf("/srv" to "/srv"), Fichiers.ariane("/srv", "/srv", "/home/c"))
    }

    @Test
    fun genresEtLangues() {
        assertEquals(Fichiers.Genre.Dossier, Fichiers.genre("src", true))
        assertEquals(Fichiers.Genre.Code, Fichiers.genre("Main.KT"))
        assertEquals(Fichiers.Genre.Code, Fichiers.genre("Makefile"))
        assertEquals(Fichiers.Genre.Config, Fichiers.genre(".bashrc"))
        assertEquals(Fichiers.Genre.Image, Fichiers.genre("logo.svg"))
        assertEquals(Fichiers.Genre.Fichier, Fichiers.genre("donnees"))
        assertEquals("kt", Fichiers.langue("A.kt"))
        assertEquals("make", Fichiers.langue("Makefile"))
        assertEquals("ini", Fichiers.langue("ccs.service"))
        assertEquals("md", Fichiers.langue("NOTES.markdown"))
        assertTrue(Fichiers.estMarkdown("README.md"))
        assertFalse(Fichiers.estMarkdown("md"))
    }

    @Test
    fun taillesEtTextes() {
        assertEquals("512 o", Fichiers.taille(512))
        assertEquals("12 Ko", Fichiers.taille(12 * 1024))
        assertEquals("3,5 Mo", Fichiers.taille(3_670_016))
        assertEquals("Ce dossier vide sera supprimé.", Fichiers.texteSuppression(true, 0, 0))
        assertTrue(Fichiers.texteSuppression(true, 4, 0).contains("4 éléments"))
        assertTrue(Fichiers.texteSuppression(false, 0, 2048).contains("2 Ko"))
    }

    @Test
    fun noms() {
        assertNull(Fichiers.nomRefuse("a.txt"))
        assertNotNull(Fichiers.nomRefuse(" "))
        assertNotNull(Fichiers.nomRefuse(".."))
        assertNotNull(Fichiers.nomRefuse("a/b"))
        assertNotNull(Fichiers.nomRefuse("é".repeat(128)))
    }

    @Test
    fun morceauxEtLignes() {
        assertEquals(listOf(0L to 0), Fichiers.morceaux(0))
        assertEquals(listOf(0L to 10, 10L to 10, 20L to 5), Fichiers.morceaux(25, 10))
        assertEquals(listOf(0L to 10), Fichiers.morceaux(10, 10))
        assertEquals(listOf("a", "b"), Fichiers.lignes("a\r\nb\n"))
        assertEquals(listOf(""), Fichiers.lignes(""))
        assertEquals(listOf("a", ""), Fichiers.lignes("a\n\n"))
    }
}
