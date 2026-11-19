package com.mawena.ccs.logique

import com.mawena.ccs.reseau.BrancheGit
import com.mawena.ccs.reseau.CodecRpc
import com.mawena.ccs.reseau.DetailCommit
import com.mawena.ccs.reseau.DiffGit
import com.mawena.ccs.reseau.EtatGit
import com.mawena.ccs.reseau.FichierGit
import com.mawena.ccs.reseau.ReponseDiff
import com.mawena.ccs.reseau.RefGit
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class GitVueTest {
    private val etat = CodecRpc.json.decodeFromString(EtatGit.serializer(), """
        {"repo": true, "root": "/p", "branch": {"name": "develop", "upstream": "origin/develop", "ahead": 2, "behind": 0},
         "files": [{"path": "a.kt", "staged": "M", "unstaged": "."},
                   {"path": "b.kt", "staged": "M", "unstaged": "M"},
                   {"path": "c.kt", "staged": ".", "unstaged": "D"},
                   {"path": "n.txt", "staged": "?", "unstaged": "?"},
                   {"path": "r.kt", "staged": "R", "unstaged": ".", "orig_path": "q.kt"}],
         "truncated": false, "proposed": "feat: x", "last_message": "fix: y", "inconnu": 1}
    """)

    @Test
    fun lectureEtGroupes() {
        assertEquals("q.kt", etat.files[4].ancien)
        assertEquals("fix: y", etat.dernierMessage)
        val g = GitVue.groupes(etat)
        assertEquals(listOf("Indexés", "Modifiés", "Non suivis"), g.map { it.titre })
        assertEquals(listOf("a.kt", "b.kt", "r.kt"), g[0].fichiers.map { it.path })
        assertEquals(listOf("b.kt", "c.kt"), g[1].fichiers.map { it.path })
        assertEquals("git.stage", g[2].methode)
        assertEquals("?", g[2].lettre(etat.files[3]))
        assertTrue(GitVue.peutCommit(etat, false))
        assertFalse(GitVue.peutCommit(etat.copy(files = listOf(FichierGit("n", "?", "?"))), false))
        assertTrue(GitVue.peutCommit(etat.copy(files = emptyList()), true))
        assertEquals(emptyList<GitVue.Groupe>(), GitVue.groupes(etat.copy(files = emptyList())))
    }

    @Test
    fun clesGardees() {
        val ouvertes = setOf(GitVue.cle(GitVue.Cote.Index, "a.kt"), GitVue.cle(GitVue.Cote.Travail, "a.kt"),
            GitVue.cle(GitVue.Cote.Travail, "n.txt"), GitVue.cle(GitVue.Cote.Index, "parti.kt"))
        assertEquals(setOf("Index:a.kt", "Travail:n.txt"), GitVue.clesGardees(ouvertes, etat))
    }

    @Test
    fun synchroEtTextes() {
        assertEquals("origin/develop · ↑2", GitVue.synchro(etat.branch))
        assertEquals("o/m · ↑1 ↓3", GitVue.synchro(BrancheGit("m", "o/m", 1, 3)))
        assertEquals("o/m · à jour", GitVue.synchro(BrancheGit("m", "o/m")))
        assertEquals("pas de suivi distant", GitVue.synchro(BrancheGit("m")))
        assertEquals("2 commit(s) partiront vers origin/develop.", GitVue.textePush(etat.branch))
        assertTrue(GitVue.textePush(BrancheGit("m")).contains("premier push"))
        assertEquals("modifié", GitVue.marque("M"))
        assertEquals("X", GitVue.marque("X"))
    }

    @Test
    fun diffsEnLignes() {
        val r = CodecRpc.json.decodeFromString(ReponseDiff.serializer(), """
            {"diff": {"path": "a.kt", "old_path": null, "binary": false, "new_file": false, "deleted": false,
              "hunks": [{"header": "@@ -1,2 +1,2 @@", "lines": [
                {"kind": " ", "text": "x", "old_no": 1, "new_no": 1},
                {"kind": "-", "text": "a", "old_no": 2, "new_no": null},
                {"kind": "+", "text": "b", "old_no": null, "new_no": 2}]}],
              "truncated": false, "too_big": false}}
        """)
        val d = r.diff!!
        assertNull(GitVue.sansDiff(d))
        assertTrue(GitVue.parMorceau("M", d))
        assertFalse(GitVue.parMorceau("?", d))
        assertFalse(GitVue.parMorceau("A", d.copy(nouveau = true)))
        val l = GitVue.lignes(d.hunks[0])
        assertEquals(listOf(Diff.Genre.Contexte, Diff.Genre.Retrait, Diff.Genre.Ajout), l.map { it.genre })
        assertEquals(2, l[1].ancien)
        assertNull(l[1].nouveau)
        val f = GitVue.fichier(d)
        assertEquals(Diff.Genre.Morceau, f.lignes[0].genre)
        assertEquals(1, f.ajouts)
        assertEquals("Fichier trop gros pour être montré.", GitVue.sansDiff(d.copy(tropGros = true)))
        assertEquals("Fichier binaire : pas de diff.", GitVue.sansDiff(d.copy(binary = true)))
        assertEquals("Pas de différence à montrer.", GitVue.sansDiff(null))
        assertEquals("renommé (b.kt)", GitVue.etatFichier(DiffGit(path = "a.kt", ancien = "b.kt")))
        assertEquals("modifié", GitVue.etatFichier(DiffGit(path = "a.kt", ancien = "a.kt")))
    }

    @Test
    fun commitEtRefs() {
        val d = CodecRpc.json.decodeFromString(DetailCommit.serializer(), """
            {"commit": {"id": "abcdef0123", "short": "abcdef01", "author": "C", "email": "c@x", "time": 1763500000,
                        "subject": "feat", "parents": ["1"], "body": "corps"},
             "files": [{"path": "a", "hunks": [], "truncated": true}], "truncated": false}
        """)
        assertEquals(1763500000L, d.commit.time)
        assertTrue(d.files[0].truncated)
        val g = GitVue.refs(listOf(RefGit("HEAD", "head", "1"), RefGit("v1", "tag", "1"), RefGit("v2", "tag", "2"),
            RefGit("main", "branch", "1"), RefGit("Dev", "branch", "2"), RefGit("origin/main", "remote", "1")))
        assertEquals(listOf("Branches", "Branches distantes", "Tags"), g.map { it.first })
        assertEquals(listOf("Dev", "main"), g[0].second.map { it.name })
        assertEquals(listOf("v2", "v1"), g[2].second.map { it.name })
    }
}
