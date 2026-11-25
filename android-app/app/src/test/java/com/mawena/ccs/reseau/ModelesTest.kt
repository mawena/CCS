package com.mawena.ccs.reseau

import kotlinx.serialization.DeserializationStrategy
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** Réponses du pont telles que les écrit `ccs_app/server` (champs en plus ignorés). */
class ModelesTest {
    private fun <T> lire(l: DeserializationStrategy<T>, texte: String): T = CodecRpc.json.decodeFromString(l, texte)

    @Test
    fun sessionsDesAutresMachines() {
        val r = lire(
            SessionsMachines.serializer(),
            """{"machines":[
               {"id":"lp-home","name":"PC maison","chats":[{"chat_id":"c1","cwd":"/home/c/Work/x","state":"busy","seq":4,
                 "options":{"model":"opus","rights":"auto"},"session_id":"s1","path":"/p/s1.jsonl","extra":1}]},
               {"id":"lp-work","name":"","error":"lp-work injoignable : délai dépassé"}]}""",
        )
        assertEquals(2, r.machines.size)
        val a = r.machines[0]
        assertEquals("PC maison", a.nom)
        assertNull(a.error)
        assertEquals("c1", a.chats.single().chatId)
        assertEquals("s1", a.chats.single().sessionId)
        assertEquals("auto", a.chats.single().options!!.rights)
        val b = r.machines[1]
        assertEquals("lp-work", b.nom)
        assertTrue(b.chats.isEmpty())
        assertEquals("lp-work injoignable : délai dépassé", b.error)
        assertTrue(lire(SessionsMachines.serializer(), "{}").machines.isEmpty())
    }

    @Test
    fun etatDesComptes() {
        val e = lire(
            EtatComptes.serializer(),
            """{"user":"c","home":"/home/c","colors":{"perso":"#3584e4"},"profiles":[{"name":"perso"}],
               "active":"perso","state":{"x":1},"pause":null,
               "pause_choices":[["1h","1 heure"],["4h","4 heures"],["demain","Jusqu'à demain 8 h"],["manuel","Jusqu'à reprise manuelle"]]}""",
        )
        assertEquals("perso", e.active)
        assertNull(e.pause)
        assertEquals("1h" to "1 heure", e.choix.first())
        assertEquals(4, e.choix.size)
        val p = lire(EtatComptes.serializer(), """{"pause":{"until":null,"label":"jusqu'à reprise manuelle"},"pause_choices":[["x"]]}""")
        assertEquals("jusqu'à reprise manuelle", p.pause!!.label)
        assertTrue(p.choix.isEmpty())
    }

    @Test
    fun cartesMeilleurCompteEtDecision() {
        val c = lire(
            Cartes.serializer(),
            """{"cards":[],"best":{"name":"pro","reason":"le plus de marge"},
               "auto_switch":{"enabled":true,"decision":{"action":"stay","target":null,"reason":"rien à faire"}},
               "updated_at":1763550000.5,"running_chats":2}""",
        )
        assertEquals("pro", c.best.texte("name"))
        assertEquals("le plus de marge", c.best.texte("reason"))
        assertEquals("rien à faire", c.bascule.texte("decision", "reason"))
        assertNull(c.bascule.texte("decision", "target"))
        assertEquals(1763550000.5, c.misAJour.secondes()!!, 0.0)
        assertEquals(2, c.chatsEnCours)
        val vide = lire(Cartes.serializer(), """{"cards":[],"best":null,"auto_switch":null,"updated_at":null}""")
        assertNull(vide.best.texte("name"))
        assertNull(vide.misAJour.secondes())
    }

    @Test
    fun bilanDeSante() {
        val b = lire(
            Bilan.serializer(),
            """{"checks":[{"nom":"Service","statut":"erreur","detail":"arrêté","commande":"systemctl --user start ccs"},
               {"nom":"Comptes","statut":"ok","detail":"2 comptes","commande":null}],"errors":1,"warnings":0,"summary":"1 erreur"}""",
        )
        assertEquals(1, b.errors)
        assertEquals("systemctl --user start ccs", b.checks[0].commande)
        assertNull(b.checks[1].commande)
    }

    @Test
    fun rapportDAnalyse() {
        val r = lire(
            Rapport.serializer(),
            """{"total":1234.5,"by_project":{"ccs":1000.0,"site":234.5},"by_model":{"opus":1234.5},
               "by_hour":[0,0,1.5,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],"by_account":{},"cache_read":5,
               "fresh_input":3,"days":7,"responses":12}""",
        )
        assertEquals(24, r.parHeure.size)
        assertEquals(1000.0, r.parProjet["ccs"]!!, 0.0)
        assertEquals(12, r.responses)
        assertTrue(r.top.isEmpty())
        val t = lire(
            Rapport.serializer(),
            """{"total":10.0,"responses":3,"top":[{"title":"Refonte du pont","project":"ccs","file":"/h/c/.claude/projects/x/a.jsonl",
               "share":62.5,"answers":140,"avg_context":180000,"rewrite_share":35.2,
               "causes":["contexte long (180 k tokens relus à chaque réponse) : /compact, ou une nouvelle session par sujet"]}]}""",
        )
        val g = t.top.single()
        assertEquals("Refonte du pont", g.title)
        assertEquals(62.5, g.share, 0.0)
        assertEquals(180_000L, g.contexteMoyen)
        assertEquals(35.2, g.partReecrite, 0.0)
        assertEquals(1, g.causes.size)
    }

    @Test
    fun listeDesProjets() {
        val l = lire(
            ListeProjets.serializer(),
            """{"entries":[{"cwd":null,"name":"Tous les projets","conversations":3,"total":3,"open":0,"waiting":0,"last":0},
               {"cwd":"/home/c/Work/ccs","name":"ccs","conversations":2,"total":2,"open":1,"waiting":0,"last":1.0,"exists":true,"moved_to":null,"profile":"pro"},
               {"cwd":"","name":"Dossier inconnu","conversations":1,"total":1,"open":0,"waiting":0,"last":0}],
               "sessions":[],"conversations":[{"session_id":"abc","path":"/home/c/.claude/projects/x/abc.jsonl","cwd":"/home/c/Work/ccs",
               "title":"","first_prompt":"Corrige le bogue","last_prompt":"merci","prompts":3,"started_at":null,"updated_at":1763550000,
               "origin":"terminal","git_branch":"develop","size":1200,"folder_exists":true,"archived":false}],"total":3,"projects":1}""",
        )
        assertEquals(listOf("/home/c/Work/ccs"), l.projets.map { it.cwd })
        assertEquals("pro", l.projets.single().profile)
        val c = l.conversations.single()
        assertEquals("Corrige le bogue", c.titre)
        assertEquals("abc", c.sessionId)
        assertEquals("(sans titre)", Conversation().titre)
    }

    @Test
    fun chatsCorbeilleEtComptes() {
        val chats = lire(
            ListeChats.serializer(),
            """{"chats":[{"chat_id":"a1","cwd":"/home/c/Work/ccs","state":"busy","seq":4,
               "options":{"model":"opus","effort":null,"ultracode":false,"rights":"manual"},"session_id":"s1","path":null,"history_before":null}]}""",
        )
        assertEquals("opus", chats.chats.single().options!!.model)
        assertNull(chats.chats.single().path)
        val co = lire(Corbeille.serializer(), """{"items":[{"trash_id":"t1","session_id":"s1","cwd":"/x","title":"T","trashed_at":10.5}],"days":30}""")
        assertEquals("t1", co.items.single().trashId)
        assertEquals("s1", co.items.single().sessionId)
        assertEquals(10.5, co.items.single().supprimeLe!!, 0.0)
        val po = lire(InfoPortier.serializer(), """{"enabled":true,"login":"https://portier.fr/x","actif":true,"connexion":"https://portier.fr/x"}""")
        assertTrue(po.enabled)
        assertEquals("https://portier.fr/x", po.login)
        val cp = lire(
            CompteProjet.serializer(),
            """{"profiles":[{"name":"perso","email":"a@b","active":true},{"name":"pro","email":"c@d","active":false}],
               "active":"perso","preferred":"pro","hint":"Associé à ce dossier","paused":false}""",
        )
        assertEquals("pro", cp.preferred)
        assertFalse(cp.profiles[1].active)
    }

    @Test
    fun messagesDeLHistorique() {
        val m = lire(
            Messages.serializer(),
            """{"messages":[{"role":"utilisateur","text":"Bonjour","ts":1.0,"tool":null,"msg_id":"","uuid":"u"},
               {"role":"outil","text":"","tool":{"name":"Bash","target":"ls","tool_id":"t","result":"ok","is_error":false}}]}""",
        )
        assertEquals("Bash", m.messages[1].tool!!.name)
    }
}
