package com.mawena.ccs.reseau

import kotlinx.serialization.DeserializationStrategy
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** Réponses de roadmap.*, tasks.*, work.*, term.* et /api/tokens telles que les écrit le serveur. */
class ModelesTravailTest {
    private fun <T> lire(l: DeserializationStrategy<T>, texte: String): T = CodecRpc.json.decodeFromString(l, texte)

    @Test
    fun feuilleDeRoute() {
        val f = lire(FeuilleDeRoute.serializer(), """{"path":"/p/ROADMAP.md","title":"Feuille",
            "phases":[{"title":"Phase 1 (0.1)","version":"0.1","line":3,"tasks":[{"text":"a","done":true,"line":5,"depth":0},{"text":"b","done":false,"line":6,"depth":1}]}]}""")
        assertEquals(2, f.phases[0].tasks.size)
        assertEquals(1, f.phases[0].tasks[1].depth)
        assertNull(lire(FeuilleDeRoute.serializer(), """{"path":null,"phases":[],"title":""}""").path)
        assertFalse(lire(ResultatCase.serializer(), """{"changed":false}""").changed)
    }

    @Test
    fun tachesEtJournal() {
        val j = lire(JournalTache.serializer(), """{"task":{"id":"a1","message":"m","cwd":"/p","model":null,"rights":"tout","when":"nuit",
            "not_before":null,"state":"running","created":1.0,"started":2.0,"finished":null,"session_id":"s","account":"perso","attempts":0,
            "retry_at":null,"pid":12,"duration":null,"cost":null,"error":null,"note":"","extra":{"roadmap":{"path":"/p/R"}}},
            "when":"cette nuit","summary":"3 outils","lines":["x","y"],"truncated":true}""")
        assertEquals("nuit", j.task.quand)
        assertEquals("s", j.task.sessionId)
        assertTrue(j.truncated)
        assertEquals(listOf("x", "y"), j.lines)
    }

    @Test
    fun changementsEtRetour() {
        val c = lire(Changements.serializer(), """{"unknown":false,"files":[{"path":"/p/a","kind":"deleted","binary":false,"diff":"","too_big":false,"sha256":null},
            {"path":"/p/b","kind":"modified","binary":false,"diff":"@@ -1 +1 @@\n-a\n+b\n","too_big":true,"sha256":"ab12"}],
            "points":[{"message_id":"m1","text":"Fais ça","time":3.0}]}""")
        assertNull(c.files[0].sha256)
        assertTrue(c.files[1].tropGros)
        assertEquals("m1", c.points[0].messageId)
        val p = lire(PlanRetour.serializer(), """{"steps":[{"path":"/p/a","deleted":true,"user_edited":true,"sha256":null}],"skipped":["/etc/x"]}""")
        assertTrue(p.steps[0].modifieParToi)
        assertEquals(2, lire(ResultatRetour.serializer(), """{"count":2,"skipped":[]}""").count)
        assertEquals("projet", lire(MessagesEnregistres.serializer(), """{"items":[{"name":"n","text":"t","scope":"projet"}]}""").items[0].scope)
    }

    @Test
    fun terminauxEtAcces() {
        val l = lire(ListeTerminaux.serializer(), """{"terms":[{"term_id":"tab12-1","cwd":"/home/c","name":"c"}]}""")
        assertEquals("tab12-1", l.terms[0].termId)
        assertEquals("$ ", lire(SortieTerminal.serializer(), """{"output":"$ "}""").output)
        val a = lire(ListeAcces.serializer(), """{"tokens":[{"id":"0123456789ab","kind":"app","name":"Pixel 4 XL","created":1.0,"last_used":2.0}]}""")
        assertEquals(2.0, a.tokens[0].dernierUsage!!, 0.0)
        assertEquals("tok", lire(JetonAppli.serializer(), """{"token":"tok"}""").token)
    }
}
