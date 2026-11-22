package com.mawena.ccs.logique

import com.mawena.ccs.reseau.MessageHistorique
import com.mawena.ccs.reseau.OutilHistorique
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Test

class FilChatTest {
    private fun ev(json: String): EvChat = EvChat.lire(Json.parseToJsonElement(json).jsonObject)

    private fun FilChat.recu(seq: Long, json: String) = recevoir(seq, ev(json))

    @Test
    fun lectureDesEvenementsDuPont() {
        val d = ev("""{"type":"TextDelta","msg_id":"m1","index":0,"text":"Bon"}""")
        assertEquals(EvChat.Delta("m1", "Bon", null), d)
        val r = ev("""{"type":"ConversationReset","conversation_id":"x","trigger":"ccs_auto"}""") as EvChat.Reinitialise
        assertTrue(r.auto)
        assertFalse((ev("""{"type":"ConversationReset","conversation_id":"x","trigger":"clear"}""") as EvChat.Reinitialise).auto)
        val h = ev("""{"type":"Hello","commands":[["clear","Efface",""],["compact","Compacte","[consigne]"]],
            "models":[["opus","Opus","",["low","high"]],["sonnet","Sonnet","",[]]],"permission_mode":"default","capabilities":[]}""") as EvChat.Hello
        assertEquals(listOf("clear", "compact"), h.commandes.map { it.nom })
        assertEquals("[consigne]", h.commandes[1].indice)
        assertEquals(ModeleIa("opus", "Opus", listOf("low", "high")), h.modeles[0])
        val t = ev("""{"type":"Todos","items":[["Lire","completed"],["Écrire","in_progress"]]}""") as EvChat.Taches
        assertEquals(listOf(Tache("Lire", "completed"), Tache("Écrire", "in_progress")), t.taches)
        assertEquals(EvChat.Autre("Bidule"), ev("""{"type":"Bidule"}"""))
        val c = ev("""{"type":"ContextUsage","percentage":42,"total":84000,"maximum":200000,"auto_compact":false}""") as EvChat.Contexte
        assertEquals(84000L, c.total)
        assertEquals(EvChat.Fin(null, false), ev("""{"type":"ProcessExited","code":null,"stderr_tail":""}"""))
    }

    @Test
    fun deltasPuisTexteFinal() {
        val f = FilChat()
        f.recu(1, """{"type":"TextDelta","msg_id":"a","index":0,"text":"Bon"}""")
        f.recu(2, """{"type":"TextDelta","msg_id":"a","index":0,"text":"jour"}""")
        val m = f.fil.elements.single() as ElementFil.MsgClaude
        assertEquals("Bonjour", m.texte)
        assertFalse(m.fini)
        f.recu(3, """{"type":"AssistantText","msg_id":"a","text":"Bonjour !"}""")
        val fin = f.fil.elements.single() as ElementFil.MsgClaude
        assertEquals("Bonjour !", fin.texte)
        assertTrue(fin.fini)
    }

    @Test
    fun numerosDejaVusIgnores() {
        val f = FilChat()
        f.recu(5, """{"type":"Notice","text":"un","kind":"info"}""")
        f.recu(5, """{"type":"Notice","text":"un","kind":"info"}""")
        f.recu(4, """{"type":"Notice","text":"vieux","kind":"info"}""")
        assertEquals(1, f.fil.taille)
        assertEquals(5L, f.seq)
    }

    @Test
    fun seulElementQuiChangeEstRemplace() {
        val f = FilChat()
        f.recu(1, """{"type":"UserSent","text":"salut","images":0,"nonce":"n","uuid":"u1"}""")
        f.recu(2, """{"type":"TextDelta","msg_id":"a","index":0,"text":"x"}""")
        val avant = f.fil.elements[0]
        f.recu(3, """{"type":"TextDelta","msg_id":"a","index":0,"text":"y"}""")
        assertSame(avant, f.fil.elements[0])        // la bulle n'est pas recréée : pas redessinée
    }

    @Test
    fun echoDeNosEnvoisPasMontreDeuxFois() {
        val f = FilChat()
        f.retenirEnvoi("abc")
        f.bulleToi("salut", 0, "u1")
        f.recu(1, """{"type":"UserSent","text":"salut","images":0,"nonce":"abc","uuid":"u1"}""")
        assertEquals(1, f.fil.taille)
        f.recu(2, """{"type":"UserSent","text":"d'un autre appareil","images":1,"nonce":"zz","uuid":"u2"}""")
        val autre = f.fil.elements[1] as ElementFil.MsgToi
        assertEquals("d'un autre appareil", autre.texte)
        assertEquals(1, autre.images)
        assertEquals("u2", autre.msgId)
    }

    @Test
    fun outilsResultatsEtDiff() {
        val f = FilChat()
        f.recu(1, """{"type":"ToolUse","tool_id":"t1","name":"Edit","input":{"file_path":"/p/a.kt","old_string":"a\nb","new_string":"a\nc"}}""")
        f.recu(2, """{"type":"ToolResult","tool_id":"t1","text":"ok","is_error":false}""")
        val o = f.fil.elements.single() as ElementFil.Outil
        assertEquals("/p/a.kt", o.cible)
        assertTrue(o.fini)
        assertEquals("ok", o.resultat)
        assertEquals(1, o.diff!!.ajouts)
        assertEquals(1, o.diff.retraits)
    }

    @Test
    fun sousAgentDansSaVue() {
        val f = FilChat()
        f.recu(1, """{"type":"ToolUse","tool_id":"ag","name":"Task","input":{"description":"Chercher","prompt":"Trouve X"}}""")
        f.recu(2, """{"type":"ToolUse","tool_id":"t2","name":"Grep","input":{"pattern":"X"},"parent_id":"ag"}""")
        f.recu(3, """{"type":"AssistantText","msg_id":"s1","text":"Trouvé","parent_id":"ag"}""")
        assertEquals(1, f.fil.taille)                      // seule la carte du sous-agent est dans le fil
        assertEquals(2, f.filAgent("ag").size)
        assertEquals(StatutAgent.Travaille, f.vuesAgents.single().statut)
        f.recu(4, """{"type":"ToolResult","tool_id":"ag","text":"résultat","is_error":false}""")
        assertEquals(StatutAgent.Fini, f.vuesAgents.single().statut)
        assertEquals("résultat", (f.fil.elements.single() as ElementFil.Agent).resultat)
    }

    @Test
    fun sousAgentEnArrierePlanAttendSonAvis() {
        val f = FilChat()
        f.recu(1, """{"type":"ToolUse","tool_id":"ag","name":"Agent","input":{"description":"Fond","run_in_background":true}}""")
        f.recu(2, """{"type":"ToolResult","tool_id":"ag","text":"lancé","is_error":false}""")
        assertEquals(StatutAgent.Travaille, f.vuesAgents.single().statut)
        f.recu(3, """{"type":"TaskNotice","tool_id":"ag","status":"completed","summary":"Fini"}""")
        assertEquals(StatutAgent.Fini, f.vuesAgents.single().statut)
    }

    @Test
    fun autorisationsEtQuestions() {
        val f = FilChat()
        val e = f.recu(1, """{"type":"PermissionRequest","request_id":"r1","tool_name":"Bash","display_name":"Bash","input":{"command":"ls -la"}}""")
        assertTrue(Effet.AutorisationArrivee in e)
        assertEquals("ls -la", (f.fil.elements.single() as ElementFil.Demande).cible)
        f.recu(2, """{"type":"PermissionSettled","request_id":"r1","decision":"allow"}""")
        assertEquals(0, f.fil.taille)
        f.recu(3, """{"type":"PermissionRequest","request_id":"q1","tool_name":"AskUserQuestion","display_name":"","input":
            {"questions":[{"question":"Lequel ?","header":"Choix","multiSelect":true,"options":[{"label":"A","description":"a"},{"label":"B"}]}]}}""")
        val q = f.fil.elements.single() as ElementFil.Questions
        assertTrue(q.questions[0].plusieurs)
        assertEquals(listOf("A", "B"), q.questions[0].options.map { it.libelle })
        f.recu(4, """{"type":"TurnResult","ok":true,"subtype":"success","cost_usd":0.5}""")
        assertEquals(0, f.fil.taille)                      // fin du tour : les demandes restantes partent
    }

    @Test
    fun separateursEtGrisage() {
        val f = FilChat()
        f.bulleToi("avant")
        f.recu(1, """{"type":"ConversationReset","conversation_id":"c","trigger":"ccs_auto"}""")
        f.bulleToi("après")
        val l = LigneFil.de(f.fil.elements)
        assertTrue(l[0].grise)
        assertTrue((l[1] as LigneFil.Seul).element.let { it is ElementFil.Separateur && it.auto })
        assertFalse(l[1].grise)
        assertFalse(l[2].grise)
    }

    @Test
    fun actionsQuiSeSuiventRegroupees() {
        val f = FilChat()
        for (i in 1..3) f.recu(i.toLong(), """{"type":"ToolUse","tool_id":"t$i","name":"Read","input":{"file_path":"/f$i"}}""")
        f.bulleToi("x")
        f.recu(4, """{"type":"ToolUse","tool_id":"t4","name":"Bash","input":{"command":"ls"}}""")
        val l = LigneFil.de(f.fil.elements)
        assertEquals(3, l.size)
        assertEquals(3, (l[0] as LigneFil.Groupe).outils.size)
        assertTrue((l[2] as LigneFil.Seul).element is ElementFil.Outil)
        assertEquals(l.size, l.map { it.cle }.toSet().size)     // clés uniques (LazyColumn)
    }

    @Test
    fun historiqueEnTeteSansDoublonDeCle() {
        val f = FilChat()
        f.recu(1, """{"type":"AssistantText","msg_id":"m9","text":"direct"}""")
        val h = listOf(
            MessageHistorique("utilisateur", "q", uuid = "u1"),
            MessageHistorique("assistant", "r", msgId = "m1"),
            MessageHistorique("outil", "", tool = OutilHistorique("Bash", "ls", "a b", "t1")),
        )
        f.prefixerHistorique(h)
        f.prefixerHistorique(h)                 // tout le journal : les plus anciens ajoutés encore devant
        assertEquals(7, f.fil.taille)
        assertEquals("direct", (f.fil.elements.last() as ElementFil.MsgClaude).texte)
        assertEquals(7, f.fil.elements.map { it.cle }.toSet().size)
    }

    @Test
    fun historiqueAuxRolesAnglais() {
        // pont 1.0 : « user » et « tool » (les anciens « utilisateur » et « outil » restent lus)
        val f = FilChat()
        f.prefixerHistorique(listOf(
            MessageHistorique("user", "q", uuid = "u1"),
            MessageHistorique("tool", "", tool = OutilHistorique("Bash", "ls", "a b", "t1")),
        ))
        assertTrue(f.fil.elements[0] is ElementFil.MsgToi)
        assertTrue(f.fil.elements[1] is ElementFil.Outil)
    }

    @Test
    fun finDeTourEtEffets() {
        val f = FilChat()
        val e = f.recu(1, """{"type":"TurnResult","ok":false,"subtype":"error","text":"Panne","interrupted":false,"is_limit":false}""")
        assertTrue(Effet.TourFini in e && Effet.DemanderContexte in e)
        assertEquals("error", (f.fil.elements.single() as ElementFil.Note).genre)
        f.recu(2, """{"type":"StateChanged","state":"idle"}""")
        assertEquals("idle", f.etat)
        f.recu(3, """{"type":"Init","session_id":"s1","model":"opus","permission_mode":"default","slash_commands":[]}""")
        assertEquals("s1", f.sessionId)
    }

    @Test
    fun arretPuisReprise() {
        val f = FilChat()
        f.arrete(reprenable = true)
        f.arrete(reprenable = true)
        assertEquals(1, f.fil.taille)
        f.repris()
        assertEquals(0, f.fil.taille)
        assertNull(f.fil["arret"])
    }
}
