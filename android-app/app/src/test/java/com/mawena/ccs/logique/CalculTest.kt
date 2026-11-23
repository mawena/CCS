package com.mawena.ccs.logique

import com.mawena.ccs.reseau.CodecRpc
import com.mawena.ccs.reseau.ListeTravaux
import com.mawena.ccs.reseau.Machine
import com.mawena.ccs.reseau.ReglagesRicochet
import com.mawena.ccs.reseau.TravailDistant
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class CalculTest {
    @Test
    fun durees() {
        assertEquals("42 s", Calcul.duree(42.0))
        assertEquals("3 min 05 s", Calcul.duree(185.0))
        assertEquals("2 h 07", Calcul.duree(2 * 3600 + 7 * 60 + 12.0))
        assertEquals("0 s", Calcul.duree(-5.0))
    }

    @Test
    fun ligneEtEtatDUnTravail() {
        val t = TravailDistant(id = "a1", text = "make", state = "done", machine = "pc-bureau",
            cwd = "/home/charles/Work/x", code = 0, created = 900.0, started = 1000.0, ended = 1185.0)
        assertEquals("pc-bureau · 3 min 05 s · code 0 · ~/Work/x", Calcul.ligne(t, maintenant = 2000.0))
        assertEquals("fini", Calcul.etat(t))
        assertFalse(Calcul.actif(t))
        assertFalse(Calcul.enEchec(t))
        assertTrue(Calcul.enEchec(t.copy(code = 2)))
        val attente = TravailDistant(text = "x", state = "waiting", created = 1000.0)
        assertEquals("machine à choisir · créé il y a 2 min", Calcul.ligne(attente, maintenant = 1150.0))
        assertTrue(Calcul.actif(attente))
        assertEquals("attente", Calcul.etat(attente))
        assertEquals("inconnu", Calcul.etat(attente.copy(state = "inconnu")))
    }

    @Test
    fun lectureDesTravaux() {
        val l = CodecRpc.json.decodeFromString(ListeTravaux.serializer(),
            """{"jobs": [{"id": "ab12cd", "text": "make", "state": "running", "machine": null, "code": null,
               "created": 1.0, "started": 2.0, "ended": null, "cwd": "/root", "why": "", "pid": 12}]}""")
        val t = l.jobs.single()
        assertEquals(null, t.machine)
        assertEquals(2.0, t.started!!, 0.0)
        assertTrue(Calcul.actif(t))
    }

    @Test
    fun blocCalcul() {
        val m = Machine(id = "pc", online = true, cores = 8, load = 4.0, memUtilisee = 3.0 * (1 shl 30), memTotale = 16.0 * (1 shl 30),
            limit = 3, running = 1, waiting = 2)
        assertEquals(0.5, Calcul.chargeParCoeur(m), 1e-9)
        assertEquals("0,50/cœur", Calcul.texteCharge(m))
        assertEquals("3,0/16 Go", Calcul.texteMemoire(m))
        assertEquals("Places : 1/3 · 2 en attente", Calcul.places(m))
        assertEquals("Places : 0/2", Calcul.places(Machine(id = "y")))
        assertTrue(Calcul.injoignable(Machine(id = "z")))
        assertFalse(Calcul.injoignable(Machine(id = "z", ipMaille = "100.64.0.9")))
        assertFalse(Calcul.injoignable(Machine(id = "z", local = true)))
    }

    @Test
    fun ajoutDePcEtDossiers() {
        assertFalse(Calcul.peutAjouterPc(null))
        assertFalse(Calcul.peutAjouterPc(ReglagesRicochet(relay = "https://r", jetonDefini = true)))
        assertTrue(Calcul.peutAjouterPc(ReglagesRicochet(relay = "https://r", jetonDefini = true, operateurDefini = true)))
        assertEquals("/home/charles", Calcul.maison("/home/charles/.config/ricochet/client.toml"))
        assertEquals("/root", Calcul.maison("/root/.config/x"))
        assertEquals("", Calcul.maison("/etc/x"))
        assertEquals("/home/charles/Work/x", Calcul.dossier(" ~/Work/x ", "/home/charles"))
        assertEquals("/home/charles", Calcul.dossier("", "/home/charles"))
        assertEquals("/srv/x", Calcul.dossier("/srv/x", "/home/charles"))
        assertTrue(Calcul.idPcValide("pc-salon"))
        assertFalse(Calcul.idPcValide("pc salon"))
        assertTrue(Calcul.compteValide("charles"))
        assertFalse(Calcul.compteValide("Charles"))
        assertTrue(Calcul.heureValide("22:30"))
        assertFalse(Calcul.heureValide("24:00"))
    }

    @Test
    fun lectureDesReglages() {
        val r = CodecRpc.json.decodeFromString(ReglagesRicochet.serializer(),
            """{"relay": "https://ricochet.mawena.cloud", "token_set": true, "operator_set": false,
               "path": "/home/c/.config/ricochet/client.toml", "default_limit": 2, "limits": {}, "relais": "x"}""")
        assertTrue(r.jetonDefini)
        assertFalse(r.operateurDefini)
        assertFalse(Calcul.peutAjouterPc(r))
    }
}
