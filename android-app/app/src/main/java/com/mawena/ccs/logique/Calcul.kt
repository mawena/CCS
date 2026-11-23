package com.mawena.ccs.logique

import com.mawena.ccs.reseau.Machine
import com.mawena.ccs.reseau.ReglagesRicochet
import com.mawena.ccs.reseau.TravailDistant
import java.util.Locale
import kotlin.math.roundToInt

/** Calcul réparti de l'onglet Réseau (`calcul.js` du web), sans Android : testé à part. */
object Calcul {
    val ACTIFS = setOf("waiting", "scheduled", "sending", "running")

    /** États des travaux en français (`STATE_LABELS`). */
    private val ETATS = mapOf(
        "waiting" to "attente", "scheduled" to "programmé", "sending" to "envoi", "running" to "en cours",
        "done" to "fini", "failed" to "échec", "stopped" to "arrêté",
    )

    /** Limites proposées pour le nombre de travaux simultanés d'une machine. */
    val LIMITES = (1..8).toList()

    fun actif(t: TravailDistant) = t.state in ACTIFS

    fun etat(t: TravailDistant) = ETATS[t.state] ?: t.state

    /** Fini avec un code non nul : affiché comme un échec. */
    fun enEchec(t: TravailDistant) = t.state == "failed" || (t.state == "done" && (t.code ?: 0) != 0)

    /** « 42 s », « 3 min 05 s », « 2 h 07 » (`duration` du web). */
    fun duree(secondes: Double): String {
        val s = secondes.roundToInt().coerceAtLeast(0)
        return when {
            s < 60 -> "$s s"
            s < 3600 -> "${s / 60} min ${"%02d".format(s % 60)} s"
            else -> "${s / 3600} h ${"%02d".format((s % 3600) / 60)}"
        }
    }

    /** « pc-bureau · 3 min 05 s · code 0 · ~/Work/x » (`jobLine` du web). */
    fun ligne(t: TravailDistant, maintenant: Double = System.currentTimeMillis() / 1000.0): String {
        val parts = mutableListOf(t.machine?.ifEmpty { null } ?: "machine à choisir")
        val debut = t.started
        if (debut != null) parts += duree((t.ended ?: maintenant) - debut)
        else parts += "créé ${Format.ilYA(t.created, maintenant)}"
        t.code?.let { parts += "code $it" }
        if (t.cwd.isNotEmpty()) parts += TachesFond.cheminCourt(t.cwd)
        return parts.joinToString(" · ")
    }

    /** Charge par cœur (0 sans cœurs connus). */
    fun chargeParCoeur(m: Machine): Double = if (m.cores > 0) m.load / m.cores else 0.0

    fun texteCharge(m: Machine) = "${String.format(Locale.FRANCE, "%.2f", chargeParCoeur(m))}/cœur"

    fun texteMemoire(m: Machine): String {
        val go = 1024.0 * 1024 * 1024
        return "${String.format(Locale.FRANCE, "%.1f", m.memUtilisee / go)}/${String.format(Locale.FRANCE, "%.0f", m.memTotale / go)} Go"
    }

    /** « Places : 1/2 · 3 en attente ». */
    fun places(m: Machine): String =
        "Places : ${m.running}/${m.limite}" + if (m.waiting > 0) " · ${m.waiting} en attente" else ""

    /** Ni réseau maillé ni tunnel Ricochet : la machine n'est pas joignable pour un travail. */
    fun injoignable(m: Machine) = !m.local && !m.tunnel && m.ipMaille.isEmpty()

    /** L'ajout d'un PC par Ricochet (`machines.add`) demande le relais, son jeton et le jeton opérateur. */
    fun peutAjouterPc(r: ReglagesRicochet?) = r != null && r.relay.isNotEmpty() && r.jetonDefini && r.operateurDefini

    /** Dossier personnel du serveur, d'après le chemin du fichier du relais (`/home/x/…` ou `/root/…`). */
    fun maison(cheminReglages: String): String =
        Regex("^(/home/[^/]+|/root)(?=/|$)").find(cheminReglages)?.value.orEmpty()

    /** Dossier saisi → chemin complet (`~` développé ; vide → dossier personnel). */
    fun dossier(saisie: String, maison: String): String {
        val d = saisie.trim().ifEmpty { maison }
        return if (d.startsWith("~") && maison.isNotEmpty()) maison + d.substring(1) else d
    }

    private val ID_PC = Regex("^[A-Za-z0-9_-]{1,64}$")
    private val COMPTE = Regex("^[a-z_][a-z0-9_-]{0,31}$")
    fun idPcValide(s: String) = ID_PC.matches(s)
    fun compteValide(s: String) = COMPTE.matches(s)

    private val HEURE = Regex("^([01]\\d|2[0-3]):[0-5]\\d$")
    fun heureValide(s: String) = HEURE.matches(s)
}
