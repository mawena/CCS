package com.mawena.ccs.logique

import com.mawena.ccs.reseau.Appareil
import com.mawena.ccs.reseau.CodecRpc
import com.mawena.ccs.reseau.EtatReseau
import com.mawena.ccs.reseau.ListeMachines
import com.mawena.ccs.reseau.Machine
import com.mawena.ccs.reseau.NoeudServeur
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class ReseauTest {
    @Test
    fun adresses() {
        assertEquals(Reseau.SorteAdresse.Locale, Reseau.adresse("192.168.0.12:41641").sorte)
        assertEquals(Reseau.SorteAdresse.Publique, Reseau.adresse("84.46.246.202:41641").sorte)
        assertEquals(Reseau.SorteAdresse.Maille, Reseau.adresse("100.64.0.2:41641").sorte)
        assertEquals(Reseau.Adresse("2a02:c207::1", Reseau.SorteAdresse.V6), Reseau.adresse("[2a02:c207::1]:41641"))
        assertEquals(Reseau.SorteAdresse.Locale, Reseau.adresse("[fe80::1]:41641").sorte)
    }

    @Test
    fun genres() {
        assertEquals(Reseau.Genre.IPhone, Reseau.genre(Appareil(name = "iphone", os = "iOS")))
        assertEquals(Reseau.Genre.Android, Reseau.genre(Appareil(name = "x", os = "android")))
        assertEquals(Reseau.Genre.Serveur, Reseau.genre(Appareil(name = "srv-mawena-cloud", os = "linux")))
        assertEquals(Reseau.Genre.Portable, Reseau.genre(Appareil(name = "lp-work", os = "linux")))
        assertEquals(Reseau.Genre.Bureau, Reseau.genre(Appareil(name = "vieux", os = "linux")))
    }

    @Test
    fun bilanEtListe() {
        val e = EtatReseau(
            ici = Appareil(name = "a", path = "self", online = true),
            peers = listOf(Appareil(name = "b", path = "lan", online = true), Appareil(name = "c", path = "offline")),
            nodes = listOf(NoeudServeur(name = "b"), NoeudServeur(name = "pixel", online = false)),
        )
        assertEquals(Reseau.Bilan(3, 2, 1, 0, 0), Reseau.bilan(e))
        assertEquals(listOf("a", "b", "c", "pixel"), Reseau.appareils(e).map { it.first.name })
        assertTrue(Reseau.appareils(e)[0].second)
        assertEquals("offline", Reseau.appareils(e)[3].first.path)
    }

    @Test
    fun formats() {
        assertEquals("1,5 Ko", Reseau.octets(1536))
        assertEquals("12 Mo", Reseau.octets(12L * 1024 * 1024))
        assertTrue(Reseau.nomValide("pc-x"))
        assertFalse(Reseau.nomValide("Pas Bon"))
        assertEquals("sudo sh -c 'a && b'", Reseau.ligneLinux(listOf("a", "b")))
    }

    @Test
    fun lectureJson() {
        val e = CodecRpc.json.decodeFromString(EtatReseau.serializer(),
            """{"url":"https://network.mawena.cloud","self":{"name":"vps","path":"self","online":true},"peers":[],"state":"Running","inconnu":1}""")
        assertEquals("vps", e.ici?.name)
        assertEquals("Running", e.state)
    }

    @Test
    fun rattachementDesMachines() {
        val vps = Machine(id = "vps", local = true)
        val bureau = Machine(id = "lp-work", ipMaille = "100.64.0.3")
        val salon = Machine(id = "pc-salon", mesh = "Salon")
        val portable = Machine(id = "lm", host = "lp-home")
        val seul = Machine(id = "ricochet-seul", name = "Vieux PC")
        val machines = listOf(vps, bureau, salon, portable, seul)
        // le serveur lui-même ↔ la machine locale, quel que soit son nom
        assertEquals(vps, Reseau.machineDe(machines, Appareil(name = "srv-mawena-cloud"), ici = true))
        // adresse du réseau maillé parmi celles de l'appareil
        assertEquals(bureau, Reseau.machineDe(machines, Appareil(name = "bureau", ips = listOf("100.64.0.3", "fd7a::3")), ici = false))
        // nom `reseau` des réglages, sans casse
        assertEquals(salon, Reseau.machineDe(machines, Appareil(name = "salon"), ici = false))
        // nom d'hôte de la machine égal au nom de l'appareil
        assertEquals(portable, Reseau.machineDe(machines, Appareil(name = "lp-home"), ici = false))
        // identifiant égal à l'hôte de l'appareil
        assertEquals(bureau, Reseau.machineDe(machines, Appareil(name = "x", host = "LP-Work"), ici = false))
        // la machine locale n'est jamais rattachée à un autre appareil ; champs vides ignorés
        assertNull(Reseau.machineDe(machines, Appareil(name = "vps"), ici = false))
        assertNull(Reseau.machineDe(listOf(Machine(id = "a")), Appareil(name = "pixel", host = ""), ici = false))
        assertNull(Reseau.machineDe(listOf(Machine(id = "a")), Appareil(name = "srv"), ici = true))
    }

    @Test
    fun fichesAvecLesMachinesHorsReseau() {
        val e = EtatReseau(
            ici = Appareil(name = "srv-mawena-cloud", path = "self", online = true),
            peers = listOf(Appareil(name = "lp-work", path = "lan", online = true, ips = listOf("100.64.0.3"))),
        )
        val machines = listOf(
            Machine(id = "vps", local = true),
            Machine(id = "lp-work", online = true),
            Machine(id = "vieux", name = "Vieux PC", online = true),
            Machine(id = "eteint"),
        )
        val f = Reseau.fiches(e, machines)
        assertEquals(listOf("srv-mawena-cloud", "lp-work", "Vieux PC", "eteint"), f.map { it.appareil.name })
        assertEquals(listOf("vps", "lp-work", "vieux", "eteint"), f.map { it.machine?.id })
        assertEquals(listOf(false, false, true, true), f.map { it.sansMaille })
        assertTrue(f[0].ici)
        assertEquals("ricochet", f[2].appareil.path)
        assertEquals("offline", f[3].appareil.path)
        assertEquals(Reseau.Chemin.Ricochet, Reseau.Chemin.de("ricochet"))
        assertEquals("Par Ricochet", Reseau.Chemin.Ricochet.libelle)
        assertEquals("Serveur CCS", Reseau.Chemin.de("self").libelle)
        // sans machines : les appareils seuls
        assertEquals(listOf(null, null), Reseau.fiches(e, emptyList()).map { it.machine })
    }

    @Test
    fun lectureDesNouveauxChampsDeMachinesList() {
        val l = CodecRpc.json.decodeFromString(ListeMachines.serializer(),
            """{"configured": true, "message": "", "machines": [{"id": "pc", "host": "lp-work", "mesh": "",
               "mesh_ip": "100.64.0.3", "tools": ["flutter", "gradle"], "limit": 3, "running": 1, "waiting": 2, "online": true}]}""")
        val m = l.machines.single()
        assertEquals("100.64.0.3", m.ipMaille)
        assertEquals("lp-work", m.host)
        assertEquals(listOf("flutter", "gradle"), m.tools)
        assertEquals(3, m.limite)
        // joignable par le réseau maillé sans tunnel Ricochet : pilotable
        assertTrue(m.choisissable)
        assertEquals(2, Machine(id = "x").limite)
    }
}
