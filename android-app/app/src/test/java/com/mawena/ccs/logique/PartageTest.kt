package com.mawena.ccs.logique

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class PartageTest {
    @Test
    fun texteEtSujet() {
        assertEquals("Titre\nhttps://x.fr", AnalysePartage.analyser("https://x.fr", "Titre", emptyList()).texte)
        assertEquals("Titre https://x.fr", AnalysePartage.analyser("Titre https://x.fr", "Titre", emptyList()).texte)
        assertEquals("Sujet", AnalysePartage.analyser(null, " Sujet ", emptyList()).texte)
        assertTrue(AnalysePartage.analyser("  ", null, emptyList()).vide)
    }

    @Test
    fun imagesEtFichiers() {
        val e = listOf(
            ElementPartage("content://1", "image/jpeg"),
            ElementPartage("content://2", "image/heic"),          // non lue par Claude : fichier
            ElementPartage("content://3", "application/pdf"),
            ElementPartage("content://4", null),
            ElementPartage("content://1", "image/jpeg"),          // doublon
            ElementPartage("content://5", "IMAGE/PNG"),
        )
        val p = AnalysePartage.analyser(null, null, e)
        assertEquals(listOf("content://1", "content://5"), p.images)
        assertEquals(listOf("content://2", "content://3", "content://4"), p.fichiers)
        assertEquals("2 images et 3 fichiers", p.resume())
    }

    @Test
    fun auDelaDuMaximumLesImagesDeviennentDesFichiers() {
        val e = (1..7).map { ElementPartage("content://$it", "image/png") }
        val p = AnalysePartage.analyser("vois", null, e, maxImages = 5)
        assertEquals(5, p.images.size)
        assertEquals(listOf("content://6", "content://7"), p.fichiers)
        assertEquals("5 images, 2 fichiers et du texte", p.resume())
    }

    @Test
    fun nomsLibres() {
        assertEquals("rapport.pdf", AnalysePartage.nomLibre("rapport.pdf", 1))
        assertEquals("rapport (2).pdf", AnalysePartage.nomLibre("rapport.pdf", 2))
        assertEquals("archive.tar (3).gz", AnalysePartage.nomLibre("archive.tar.gz", 3))
        assertEquals("LISEZMOI (2)", AnalysePartage.nomLibre("LISEZMOI", 2))
        assertEquals(".env (2)", AnalysePartage.nomLibre(".env", 2))
    }

    @Test
    fun saisieComposee() {
        assertEquals("brouillon\n\nregarde\n\nFichier ajouté au dossier du projet : `a.pdf`",
            AnalysePartage.composer("brouillon\n", " regarde ", listOf("a.pdf")))
        assertEquals("Fichiers ajoutés au dossier du projet : `a.pdf`, `b (2).zip`",
            AnalysePartage.composer("", "", listOf("a.pdf", "b (2).zip")))
        assertEquals("", AnalysePartage.composer("", "", emptyList()))
    }
}
