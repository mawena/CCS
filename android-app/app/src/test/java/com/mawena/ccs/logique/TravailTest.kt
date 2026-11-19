package com.mawena.ccs.logique

import com.mawena.ccs.reseau.EtapeRetour
import com.mawena.ccs.reseau.FichierChange
import com.mawena.ccs.reseau.PhaseFeuille
import com.mawena.ccs.reseau.PlanRetour
import com.mawena.ccs.reseau.TacheFeuille
import com.mawena.ccs.reseau.TacheFond
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** Feuille de route, tâches de fond et changements du chat : la logique sans Android. */
class TravailTest {
    private fun phase(vararg faites: Boolean) = PhaseFeuille("P", tasks = faites.mapIndexed { i, f -> TacheFeuille("t$i", f, i + 1) })

    @Test
    fun progressionEtPhasesOuvertes() {
        val phases = listOf(phase(true, true), phase(true, false, false), phase(), phase(false))
        assertEquals("2/2", FeuilleRoute.progression(phases[0]).toString())
        assertEquals(1f / 3, FeuilleRoute.progression(phases[1]).fraction, 1e-6f)
        assertEquals(0f, FeuilleRoute.progression(phases[2]).fraction)
        assertEquals(setOf(1, 3), FeuilleRoute.ouvertes(phases))
        assertEquals(1, FeuilleRoute.enCours(phases))
        assertNull(FeuilleRoute.enCours(listOf(phase(true))))
        assertEquals(3, FeuilleRoute.niveau(7))
        assertEquals(0, FeuilleRoute.niveau(-1))
    }

    private fun tache(etat: String, vararg autres: Pair<String, Any?>): TacheFond {
        var t = TacheFond(id = etat, message = "Ranger le dépôt\nen détail", cwd = "/home/c/Work/ccs", state = etat)
        for ((k, v) in autres) t = when (k) {
            "note" -> t.copy(note = v as String)
            "error" -> t.copy(error = v as String)
            "finished" -> t.copy(finished = v as Double)
            "when" -> t.copy(quand = v as String)
            else -> t
        }
        return t
    }

    @Test
    fun sousTitresDesTaches() {
        assertEquals("En attente · cette nuit · ~/Work/ccs", TachesFond.sousTitre(tache("queued", "when" to "nuit")))
        assertEquals("En attente · à 03:30 · ~/Work/ccs", TachesFond.sousTitre(tache("queued", "when" to "03:30")))
        assertEquals("À reprendre (limite atteinte) · limite du compte · ~/Work/ccs", TachesFond.sousTitre(tache("waiting", "note" to "limite du compte")))
        assertEquals("Échouée · délai dépassé · ~/Work/ccs", TachesFond.sousTitre(tache("failed", "error" to "délai dépassé")))
        assertEquals("Finie · il y a 2 h · ~/Work/ccs", TachesFond.sousTitre(tache("done", "finished" to 1000.0), maintenant = 1000.0 + 7200))
        assertEquals("Ranger le dépôt", TachesFond.titre(tache("done")))
        assertEquals("Modifications des fichiers", TachesFond.droits("modifications"))
    }

    @Test
    fun filtresDesTaches() {
        val l = listOf(tache("done"), tache("failed"), tache("running").copy(id = "r1"), tache("queued").copy(id = "q2"))
        assertEquals("actives", TachesFond.filtreInitial(l))
        assertEquals("done", TachesFond.filtreInitial(listOf(tache("done"))))
        assertEquals("actives", TachesFond.filtreInitial(emptyList()))
        assertEquals(listOf("q2", "r1"), TachesFond.filtrer(l, "actives").map { it.id })      // plus récentes d'abord
        assertEquals(1, TachesFond.nombre(l, TachesFond.FILTRES[2]))
        assertTrue(TachesFond.active(tache("waiting")))
    }

    @Test
    fun formulaireDeTache() {
        assertEquals("/home/c/Work/x", TachesFond.dossier(" ~/Work/x ", "/home/c"))
        assertEquals("~/x", TachesFond.dossier("~/x", ""))
        assertEquals("Indique le dossier du projet.", TachesFond.verifier("", "m", "quota", ""))
        assertEquals("Écris ce que Claude doit faire.", TachesFond.verifier("/d", "  ", "quota", ""))
        assertEquals("Choisis l'heure (HH:MM).", TachesFond.verifier("/d", "m", "heure", "25:00"))
        assertNull(TachesFond.verifier("/d", "m", "heure", "3:05"))
        assertEquals("03:05", TachesFond.quandEnvoye("heure", "3:05"))
        assertEquals("nuit", TachesFond.quandEnvoye("nuit", "3:05"))
    }

    @Test
    fun diffUnifieNumerote() {
        val d = "--- a/x.py\n+++ b/x.py\n@@ -1,3 +1,3 @@\n un\n-deux\n+DEUX\n trois\n\\ No newline at end of file\n@@ -10 +10,2 @@\n+neuf\n dix\n"
        val l = ChangementsChat.lignes(d)
        assertEquals(Diff.Genre.Morceau, l[0].genre)
        assertEquals(Diff.Ligne(Diff.Genre.Contexte, "un", 1, 1), l[1])
        assertEquals(Diff.Ligne(Diff.Genre.Retrait, "deux", 2, null), l[2])
        assertEquals(Diff.Ligne(Diff.Genre.Ajout, "DEUX", null, 2), l[3])
        assertEquals(Diff.Ligne(Diff.Genre.Contexte, "trois", 3, 3), l[4])
        assertEquals(Diff.Genre.Morceau, l[5].genre)
        assertEquals(Diff.Ligne(Diff.Genre.Ajout, "neuf", null, 10), l[6])
        assertEquals(Diff.Ligne(Diff.Genre.Contexte, "dix", 10, 11), l[7])
        assertEquals(8, l.size)
        assertTrue(ChangementsChat.lignes("").isEmpty())
    }

    @Test
    fun texteDuRetourArriere() {
        val plan = PlanRetour(
            listOf(EtapeRetour("/p/a.txt", deleted = true), EtapeRetour("/p/src/b.kt", modifieParToi = true), EtapeRetour("/ailleurs/c")),
            skipped = listOf("/etc/x"),
        )
        assertEquals(
            "a.txt (supprimé)\nsrc/b.kt (modifié depuis par toi ?)\n/ailleurs/c\n\nLaissés tels quels (hors des dossiers permis) :\n/etc/x\n\nC'est définitif.",
            ChangementsChat.texteRetour(plan, "/p"),
        )
        assertEquals("Revenir avant ce message ? (3 fichiers)", ChangementsChat.titreRetour(plan))
        assertEquals("Revenir avant ce message ? (1 fichier)", ChangementsChat.titreRetour(PlanRetour(listOf(EtapeRetour("/p/a")))))
        assertEquals("Le fichier sera supprimé (Claude l'a créé). C'est définitif.", ChangementsChat.texteAnnulation(FichierChange(kind = "created")))
        assertEquals("créé", ChangementsChat.genre(FichierChange(kind = "created")))
    }
}
