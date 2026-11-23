package com.mawena.ccs.logique

import com.mawena.ccs.reseau.Appareil
import com.mawena.ccs.reseau.EtatReseau

/** Calculs de l'onglet Réseau, sans Android (testés à part). Mêmes règles que la version web. */
object Reseau {
    enum class Chemin(val libelle: String) {
        Ici("Cet appareil"), Lan("Réseau local"), Direct("Direct par internet"),
        Relais("Relais du VPS"), Veille("En veille"), HorsLigne("Hors ligne");

        companion object {
            fun de(path: String) = when (path) {
                "self" -> Ici; "lan" -> Lan; "direct" -> Direct; "relay" -> Relais
                "offline" -> HorsLigne; else -> Veille
            }
        }
    }

    enum class Genre { Serveur, Portable, Bureau, Android, IPhone }

    fun genre(a: Appareil): Genre {
        val os = a.os.lowercase()
        val nom = a.name.lowercase()
        return when {
            os == "ios" || "iphone" in nom || "ipad" in nom -> Genre.IPhone
            os == "android" || "pixel" in nom || "phone" in nom -> Genre.Android
            os == "macos" -> Genre.Portable
            listOf("vps", "cloud", "server", "serveur").any { it in nom } -> Genre.Serveur
            "laptop" in nom || "portable" in nom -> Genre.Portable
            else -> Genre.Bureau
        }
    }

    enum class SorteAdresse(val libelle: String) { Locale("Local"), Publique("Public"), V6("IPv6"), Maille("Réseau") }

    data class Adresse(val ip: String, val sorte: SorteAdresse)

    /** « 192.168.1.20:41641 » ou « [2a02::1]:41641 » → adresse et sorte. */
    fun adresse(texte: String): Adresse {
        val hote = if (texte.startsWith("[")) texte.substring(1, texte.indexOf(']').coerceAtLeast(1))
        else texte.replace(Regex(":\\d+$"), "")
        if (':' in hote) {
            val local = Regex("^(fe80|fc|fd)", RegexOption.IGNORE_CASE).containsMatchIn(hote)
            return Adresse(hote, if (local) SorteAdresse.Locale else SorteAdresse.V6)
        }
        val p = hote.split('.').map { it.toIntOrNull() }
        if (p.size != 4 || p.any { it == null }) return Adresse(hote, SorteAdresse.Publique)
        val (a, b) = p[0]!! to p[1]!!
        val sorte = when {
            a == 100 && b in 64..127 -> SorteAdresse.Maille
            a == 10 || (a == 172 && b in 16..31) || (a == 192 && b == 168) || (a == 169 && b == 254) -> SorteAdresse.Locale
            else -> SorteAdresse.Publique
        }
        return Adresse(hote, sorte)
    }

    /** Adresses publiées par l'appareil, sans celles du réseau maillé. */
    fun adressesPubliees(a: Appareil): List<Adresse> =
        a.addrs.map(::adresse).filter { it.sorte != SorteAdresse.Maille }.distinctBy { it.ip }

    data class Bilan(val total: Int, val enLigne: Int, val lan: Int, val direct: Int, val relais: Int)

    fun bilan(e: EtatReseau): Bilan {
        val ici = if (e.ici != null) 1 else 0
        return Bilan(
            total = e.peers.size + ici,
            enLigne = e.peers.count { it.online } + ici,
            lan = e.peers.count { it.path == "lan" },
            direct = e.peers.count { it.path == "direct" },
            relais = e.peers.count { it.path == "relay" },
        )
    }

    /** Tous les appareils à afficher : celui-ci, ses pairs, puis ceux que seul le serveur connaît. */
    fun appareils(e: EtatReseau): List<Pair<Appareil, Boolean>> {
        val liste = buildList {
            e.ici?.let { add(it to true) }
            e.peers.forEach { add(it to false) }
        }
        val vus = liste.map { it.first.name }.toSet()
        val enPlus = e.nodes.filter { it.name !in vus }.map {
            Appareil(name = it.name, host = it.host, ips = it.ips, online = it.online,
                path = if (it.online) "idle" else "offline") to false
        }
        return liste + enPlus
    }

    fun octets(n: Long): String {
        if (n < 1024) return "$n o"
        val unites = listOf("Ko", "Mo", "Go", "To")
        var x = n / 1024.0
        var i = 0
        while (x >= 1024 && i < unites.size - 1) { x /= 1024; i++ }
        val t = if (x < 10) String.format(java.util.Locale.FRANCE, "%.1f", x).removeSuffix(",0") else x.toLong().toString()
        return "$t ${unites[i]}"
    }

    private val NOM = Regex("^[a-z0-9][a-z0-9-]{0,62}$")
    fun nomValide(n: String) = NOM.matches(n)

    /** La ligne à coller sur un PC Linux. */
    fun ligneLinux(lignes: List<String>) = "sudo sh -c '${lignes.joinToString(" && ")}'"
}
