package com.mawena.ccs.logique

import com.mawena.ccs.reseau.MessageHistorique
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.contentOrNull

/** Ce que montre le fil du chat. Objets immuables : un élément qui ne change pas garde la même instance. */
sealed interface ElementFil {
    val cle: String

    data class MsgToi(override val cle: String, val texte: String, val images: Int = 0, val msgId: String = "") : ElementFil
    data class MsgClaude(override val cle: String, val texte: String, val msgId: String = "", val fini: Boolean = false) : ElementFil
    data class Outil(
        override val cle: String,
        val nom: String,
        val cible: String,
        val details: String = "",
        val diff: Diff.Fichier? = null,
        val resultat: String? = null,
        val erreur: Boolean = false,
        val fini: Boolean = false,
        val imbrique: Boolean = false,
    ) : ElementFil
    data class Agent(
        override val cle: String,
        val nom: String,
        val consigne: String,
        val arrierePlan: Boolean,
        val resultat: String? = null,
        val statut: StatutAgent = StatutAgent.Travaille,
    ) : ElementFil
    data class Note(override val cle: String, val texte: String, val genre: String = "info", val action: ActionNote? = null) : ElementFil
    data class Separateur(override val cle: String, val auto: Boolean) : ElementFil
    /** Ligne discrète sous une fin de tour : « 36 k lus · 15 k écrits · 403 produits · 0,04 $ ». */
    data class Usage(override val cle: String, val texte: String) : ElementFil
    data class Demande(
        override val cle: String, val outil: String, val cible: String, val details: String, val description: String,
    ) : ElementFil
    data class Questions(override val cle: String, val questions: List<QuestionClaude>) : ElementFil
    /** Commande `!` lancée dans le dossier du projet. */
    data class Commande(
        override val cle: String, val commande: String, val runId: String? = null,
        val sortie: String? = null, val code: Int? = null,
    ) : ElementFil {
        val finie: Boolean get() = code != null
    }
    /** Le pont ne connaît plus ce chat : « Reprendre la conversation ». */
    data class Arrete(override val cle: String, val reprenable: Boolean) : ElementFil
}

enum class StatutAgent { Travaille, Fini, Arrete }

/** Boutons d'une note : « Compacter » (contexte lourd) ; « Compacter » et « Nouvelle session » (cache expiré). */
enum class ActionNote { Compacter, CacheExpire }

data class OptionQuestion(val libelle: String, val description: String)
data class QuestionClaude(val question: String, val entete: String, val plusieurs: Boolean, val options: List<OptionQuestion>)

/** Sous-agent : pastille au-dessus du fil et sa vue (ses textes et outils). */
data class VueAgent(val id: String, val nom: String, val statut: StatutAgent, val arrierePlan: Boolean)

/**
 * Barre des sous-agents (`tidyPills` / `toggleAgentHistory` de `web/chat.js`) : un sous-agent qui
 * travaille a sa pastille ; fini, il la quitte (sauf si on le regarde) et passe dans « Terminés (n) »,
 * le plus récent en tête. `agents` : dans l'ordre de lancement.
 */
object BarreAgents {
    fun pastilles(agents: List<VueAgent>, vu: String?): List<VueAgent> =
        agents.filter { it.statut == StatutAgent.Travaille || it.id == vu }

    fun termines(agents: List<VueAgent>): List<VueAgent> =
        agents.filter { it.statut != StatutAgent.Travaille }.asReversed()
}

/** Ce que l'écran doit faire après un événement. */
enum class Effet { DemanderContexte, TourFini, SessionConnue, NouveauHello, MesureContexte, AutorisationArrivee }

/**
 * Fil d'un chat : reçoit les événements numérotés du pont (`receive()` de `web/chat.js`) et tient
 * la liste des éléments à montrer, les sous-agents, la liste de tâches, l'état, le contexte.
 * Sans Android, utilisé depuis un seul fil (celui de l'écran).
 */
class FilChat {
    /** Liste avec index par clé : mise à jour d'un élément en O(1). */
    class Liste {
        private val items = ArrayList<ElementFil>()
        private val pos = HashMap<String, Int>()
        val elements: List<ElementFil> get() = items
        val taille: Int get() = items.size

        fun ajouter(e: ElementFil) {
            pos[e.cle]?.let { items[it] = e; return }
            pos[e.cle] = items.size
            items.add(e)
        }

        operator fun get(cle: String): ElementFil? = pos[cle]?.let { items[it] }

        fun maj(cle: String, f: (ElementFil) -> ElementFil) {
            val i = pos[cle] ?: return
            items[i] = f(items[i])
        }

        fun retirer(cle: String) {
            val i = pos.remove(cle) ?: return
            items.removeAt(i)
            reindexer()
        }

        fun prefixer(avant: List<ElementFil>) {
            val neufs = avant.filter { it.cle !in pos }
            items.addAll(0, neufs)
            reindexer()
        }

        fun vider() { items.clear(); pos.clear() }

        private fun reindexer() {
            pos.clear()
            items.forEachIndexed { i, e -> pos[e.cle] = i }
        }
    }

    private class Agent(val id: String, val nom: String, val arrierePlan: Boolean) {
        var statut = StatutAgent.Travaille
        val fil = Liste()
    }

    val fil = Liste()
    private val agents = LinkedHashMap<String, Agent>()
    private val outilDans = HashMap<String, Liste>()      // tool_id → liste qui montre sa carte
    private val textes = HashMap<String, Liste>()         // msg_id → liste qui montre le texte
    private val demandes = LinkedHashSet<String>()        // request_id en attente
    private val propres = HashSet<String>()               // nonces de nos envois (écho ignoré)
    private var compteur = 0L

    var seq = 0L; private set
    var sessionId: String? = null; private set
    var etat = "starting"; private set
    var reflechit = false; private set
    var taches: List<Tache> = emptyList(); private set
    var contexte: EvChat.Contexte? = null; private set
    var commandes: List<CommandeSlash> = emptyList(); private set
    var modeles: List<ModeleIa> = emptyList(); private set
    /** Droits annoncés par Claude (Status, Maj+Tab au bureau) ; null : pas d'annonce. */
    var droitsAnnonces: String? = null; private set
    /** Usage du dernier tour (`TurnResult.usage`), pour l'indicateur de contexte. */
    var dernierUsage: UsageTour? = null; private set
    /** Cache expiré sans tour depuis : le prochain message relira tout le contexte au prix fort. */
    var cacheExpire: EvChat.CacheExpire? = null; private set
    /** Dernier coût de tour connu (dollars). */
    var coutTours = 0.0; private set

    val vuesAgents: List<VueAgent> get() = agents.values.map { VueAgent(it.id, it.nom, it.statut, it.arrierePlan) }
    fun filAgent(id: String): List<ElementFil> = agents[id]?.fil?.elements ?: emptyList()

    private fun cle(prefixe: String) = "$prefixe${++compteur}"

    /** Nos propres envois : leur écho (UserSent) n'est pas montré deux fois. */
    fun retenirEnvoi(nonce: String) { propres.add(nonce) }
    fun oublierEnvoi(nonce: String) { propres.remove(nonce) }

    fun definirSession(id: String?) { if (!id.isNullOrEmpty()) sessionId = id }

    /** Fil remis à zéro (le pont a redémarré, ou une autre conversation). */
    fun remettreAZero() {
        seq = 0
        fil.vider(); agents.clear(); outilDans.clear(); textes.clear(); demandes.clear()
        taches = emptyList(); contexte = null; reflechit = false
        dernierUsage = null; cacheExpire = null
    }

    // ---- envois et notes de l'écran ---------------------------------------------------------

    fun bulleToi(texte: String, images: Int = 0, msgId: String = ""): String {
        val c = cle("u")
        fil.ajouter(ElementFil.MsgToi(c, texte, images, msgId))
        return c
    }

    fun note(texte: String, genre: String = "info", action: ActionNote? = null): String {
        val c = cle("n")
        fil.ajouter(ElementFil.Note(c, texte, genre, action))
        return c
    }

    fun commande(commande: String): String {
        val c = cle("s")
        fil.ajouter(ElementFil.Commande(c, commande))
        return c
    }

    fun majCommande(cle: String, f: (ElementFil.Commande) -> ElementFil.Commande) =
        fil.maj(cle) { if (it is ElementFil.Commande) f(it) else it }

    fun arrete(reprenable: Boolean) {
        if (fil["arret"] == null) fil.ajouter(ElementFil.Arrete("arret", reprenable))
        etat = "stopped"
    }

    fun repris() { fil.retirer("arret") }

    fun changerEtat(e: String?) {
        if (e.isNullOrEmpty()) return
        etat = e
        if (e != "busy") reflechit = false
    }

    fun retirerDemande(requestId: String) {
        demandes.remove(requestId)
        fil.retirer(requestId)
    }

    // ---- événements du pont ----------------------------------------------------------------

    /** Événement numéroté : ignoré s'il est déjà vu (rattachement). */
    fun recevoir(numero: Long, ev: EvChat): Set<Effet> {
        if (numero > 0) {
            if (numero <= seq) return emptySet()
            seq = numero
        }
        val p = ev.parent
        val agent = if (p != null) agents[p] else null
        if (agent != null) { evenementAgent(agent, ev); return emptySet() }
        val effets = HashSet<Effet>()
        when (ev) {
            is EvChat.Init -> { definirSession(ev.sessionId); effets.add(Effet.SessionConnue) }
            is EvChat.Hello -> {
                commandes = ev.commandes
                modeles = ev.modeles
                effets.add(Effet.NouveauHello)
            }
            is EvChat.Statut -> if (ev.droits.isNotEmpty()) droitsAnnonces = if (ev.droits == "default") "manual" else ev.droits
            is EvChat.CommandeLocale -> {
                if (ev.texte.isNotEmpty()) note(ev.texte)
                effets.add(Effet.DemanderContexte)
            }
            is EvChat.Delta -> texteClaude(ev.msgId, (texteDe(ev.msgId) ?: "") + ev.texte, false)
            is EvChat.Texte -> texteClaude(ev.msgId, ev.texte, true)
            is EvChat.Reflexion -> reflechit = true
            is EvChat.OutilLance -> outil(ev, fil, imbrique = ev.parentId != null)
            is EvChat.OutilFini -> { resultat(ev); agentFini(ev.toolId) }
            is EvChat.AvisTache -> {
                outilDans[ev.toolId]?.maj(ev.toolId) { if (it is ElementFil.Outil) it.copy(fini = true) else it }
                agentFini(ev.toolId, avis = true)
                if (ev.resume.isNotEmpty()) note(ev.resume)
            }
            is EvChat.Taches -> taches = ev.taches
            is EvChat.Autorisation -> { demande(ev); effets.add(Effet.AutorisationArrivee) }
            is EvChat.Envoye -> if (!propres.remove(ev.nonce)) bulleToi(ev.texte, ev.images, ev.uuid)
            is EvChat.Reglee -> retirerDemande(ev.requestId)
            is EvChat.Tour -> {
                when {
                    ev.interrompu -> { note("Arrêté."); arreterAgents() }
                    ev.limite -> note("Limite d'usage atteinte : ${ev.texte.ifEmpty { "attends la fin de la période ou change de compte." }}", "warning")
                    !ev.ok -> note(ev.texte.ifEmpty { "Claude n'a pas pu finir sa réponse." }, "error")
                }
                coutTours += ev.coutUsd
                cacheExpire = null
                ev.usage?.let { u ->
                    dernierUsage = u
                    Consommation.resume(u).takeIf(String::isNotEmpty)?.let { fil.ajouter(ElementFil.Usage(cle("t"), it)) }
                }
                demandes.toList().forEach { fil.retirer(it) }
                demandes.clear()
                effets.add(Effet.TourFini); effets.add(Effet.DemanderContexte)
            }
            is EvChat.Compacte -> { cacheExpire = null; note("Conversation compactée.") }
            is EvChat.Reinitialise -> {
                cacheExpire = null; dernierUsage = null
                fil.ajouter(ElementFil.Separateur(cle("r"), ev.auto))
            }
            is EvChat.CacheExpire -> {
                cacheExpire = ev
                note(ev.texte.ifEmpty { "Cache expiré : le prochain message relira tout le contexte au prix fort." }, "warning", ActionNote.CacheExpire)
            }
            is EvChat.Note -> note(ev.texte, if (ev.genre == "warning" || ev.genre == "error") ev.genre else "info")
            is EvChat.NouvelEssai -> note("Nouvel essai (${ev.tentative}) dans ${Math.round(ev.delaiS)} s…", "warning")
            is EvChat.Etat -> changerEtat(ev.etat)
            is EvChat.Contexte -> { contexte = ev; effets.add(Effet.MesureContexte) }
            is EvChat.OptionRefusee -> note("Réglage refusé (${ev.quoi}) : ${ev.erreur}", "warning")
            is EvChat.DemandeInconnue -> note("Demande non prise en charge : ${ev.sousType}", "warning")
            is EvChat.Fin -> {
                arreterAgents()
                if (!ev.demande && ev.code != null && ev.code != 0) note("Claude s'est arrêté (code ${ev.code}).", "error")
            }
            is EvChat.EtiquettesChangees, is EvChat.Autre -> Unit
        }
        return effets
    }

    private fun texteDe(msgId: String): String? = (textes[msgId]?.get("m$msgId") as? ElementFil.MsgClaude)?.texte

    private fun texteClaude(msgId: String, texte: String, fini: Boolean, liste: Liste = fil) {
        val l = textes.getOrPut(msgId) { liste }
        val c = "m$msgId"
        if (l[c] == null) l.ajouter(ElementFil.MsgClaude(c, texte, msgId, fini))
        else l.maj(c) { (it as ElementFil.MsgClaude).copy(texte = texte, fini = fini || it.fini) }
    }

    private fun outil(ev: EvChat.OutilLance, liste: Liste, imbrique: Boolean) {
        if (liste === fil && ev.nom in Outils.AGENTS) { carteAgent(ev); return }
        outilDans[ev.toolId] = liste
        liste.ajouter(
            ElementFil.Outil(
                ev.toolId, ev.nom, Outils.cible(ev.nom, ev.entree), Outils.details(ev.entree),
                Diff.deOutil(ev.nom, ev.entree), imbrique = imbrique,
            ),
        )
    }

    private fun resultat(ev: EvChat.OutilFini) {
        outilDans[ev.toolId]?.maj(ev.toolId) {
            when (it) {
                is ElementFil.Outil -> it.copy(resultat = ev.texte, erreur = ev.erreur, fini = true)
                is ElementFil.Agent -> it.copy(resultat = ev.texte)
                else -> it
            }
        }
    }

    private fun carteAgent(ev: EvChat.OutilLance) {
        val e = ev.entree
        fun t(k: String) = (e[k] as? JsonPrimitive)?.contentOrNull.orEmpty()
        val nom = t("description").ifEmpty { t("subagent_type") }.ifEmpty { "Sous-agent" }.take(60)
        val fond = (e["run_in_background"] as? JsonPrimitive)?.booleanOrNull ?: false
        agents[ev.toolId] = Agent(ev.toolId, nom, fond)
        outilDans[ev.toolId] = fil
        fil.ajouter(ElementFil.Agent(ev.toolId, nom, t("prompt").ifEmpty { Outils.details(e) }, fond))
    }

    private fun evenementAgent(a: Agent, ev: EvChat) {
        when (ev) {
            is EvChat.OutilLance -> if (ev.nom != "TodoWrite") outil(ev, a.fil, imbrique = false)
            is EvChat.OutilFini -> resultat(ev)
            is EvChat.Texte -> if (ev.texte.isNotEmpty()) texteClaude(ev.msgId, ev.texte, true, a.fil)
            is EvChat.Delta -> texteClaude(ev.msgId, (texteDe(ev.msgId) ?: "") + ev.texte, false, a.fil)
            else -> Unit
        }
    }

    /** Fin d'un sous-agent : son résultat (premier plan) ou son avis de fin (arrière-plan). */
    private fun agentFini(id: String, avis: Boolean = false, arret: Boolean = false) {
        val a = agents[id] ?: return
        if (a.statut != StatutAgent.Travaille || (a.arrierePlan && !avis && !arret)) return
        a.statut = if (arret) StatutAgent.Arrete else StatutAgent.Fini
        fil.maj(id) { if (it is ElementFil.Agent) it.copy(statut = a.statut) else it }
    }

    private fun arreterAgents() { agents.keys.toList().forEach { agentFini(it, arret = true) } }

    private fun demande(ev: EvChat.Autorisation) {
        demandes.add(ev.requestId)
        if (ev.outil == "AskUserQuestion") {
            fil.ajouter(ElementFil.Questions(ev.requestId, questions(ev.entree)))
            return
        }
        fil.ajouter(
            ElementFil.Demande(
                ev.requestId, ev.affiche.ifEmpty { ev.outil }, Outils.cible(ev.outil, ev.entree),
                Outils.details(ev.entree), ev.description,
            ),
        )
    }

    // ---- historique ----------------------------------------------------------------------------

    /** Messages du journal d'avant le tampon du pont, ajoutés en tête du fil. */
    fun prefixerHistorique(messages: List<MessageHistorique>) {
        var n = 0
        val avant = messages.mapNotNull { m ->
            n++
            when (m.role) {
                "user", "utilisateur" -> ElementFil.MsgToi("h$n-${m.uuid}", m.text, 0, m.uuid)
                "assistant" -> ElementFil.MsgClaude("h$n-${m.msgId}", m.text, m.msgId, true)
                "tool", "outil" -> m.tool?.let { t ->
                    ElementFil.Outil("h$n-${t.toolId}", t.name, t.target, resultat = t.result, erreur = t.erreur, fini = true)
                }
                else -> if (m.text.isNotBlank()) ElementFil.Note("h$n", m.text) else null
            }
        }
        // les clés « hN » doivent rester uniques d'un chargement à l'autre (tout le journal après les 200 derniers)
        fil.prefixer(avant.map { renommer(it, "${++compteur}") })
    }

    private fun renommer(e: ElementFil, s: String): ElementFil = when (e) {
        is ElementFil.MsgToi -> e.copy(cle = "${e.cle}:$s")
        is ElementFil.MsgClaude -> e.copy(cle = "${e.cle}:$s")
        is ElementFil.Outil -> e.copy(cle = "${e.cle}:$s")
        is ElementFil.Note -> e.copy(cle = "${e.cle}:$s")
        else -> e
    }

    companion object {
        fun questions(e: JsonObject): List<QuestionClaude> = (e["questions"] as? JsonArray).orEmpty().mapNotNull { q ->
            val o = q as? JsonObject ?: return@mapNotNull null
            fun t(x: JsonObject, k: String) = (x[k] as? JsonPrimitive)?.contentOrNull.orEmpty()
            QuestionClaude(
                t(o, "question"), t(o, "header"), (o["multiSelect"] as? JsonPrimitive)?.booleanOrNull ?: false,
                (o["options"] as? JsonArray).orEmpty().mapNotNull { (it as? JsonObject)?.let { op -> OptionQuestion(t(op, "label"), t(op, "description")) } },
            )
        }
    }
}

/** Ligne de l'écran : un élément, ou plusieurs actions qui se suivent réunies (« 3 actions »). */
sealed interface LigneFil {
    val cle: String
    /** Avant un « Nouvelle conversation » : Claude ne le voit plus (grisé). */
    val grise: Boolean

    data class Seul(val element: ElementFil, override val grise: Boolean) : LigneFil {
        override val cle: String get() = element.cle
    }

    data class Groupe(val outils: List<ElementFil.Outil>, override val grise: Boolean) : LigneFil {
        override val cle: String get() = "g:" + outils.first().cle
    }

    companion object {
        /** Lignes à montrer : actions consécutives regroupées, éléments d'avant le dernier séparateur grisés. */
        fun de(elements: List<ElementFil>): List<LigneFil> {
            val dernier = elements.indexOfLast { it is ElementFil.Separateur }
            val out = ArrayList<LigneFil>(elements.size)
            var suite = ArrayList<ElementFil.Outil>()
            var suiteGrise = false
            fun vider() {
                if (suite.size >= 2) out.add(Groupe(suite, suiteGrise))
                else suite.forEach { out.add(Seul(it, suiteGrise)) }
                suite = ArrayList()
            }
            elements.forEachIndexed { i, e ->
                val grise = i < dernier
                if (e is ElementFil.Outil) {
                    if (suite.isNotEmpty() && suiteGrise != grise) vider()
                    suite.add(e); suiteGrise = grise
                } else {
                    vider()
                    out.add(Seul(e, grise))
                }
            }
            vider()
            return out
        }

        /** Texte d'une ligne pour la recherche dans le fil. */
        fun texte(l: LigneFil): String = when (l) {
            is Groupe -> l.outils.joinToString("\n") { texte(it) }
            is Seul -> texte(l.element)
        }

        fun texte(e: ElementFil): String = when (e) {
            is ElementFil.MsgToi -> e.texte
            is ElementFil.MsgClaude -> e.texte
            is ElementFil.Outil -> listOf(Outils.libelle(e.nom), e.cible, e.resultat.orEmpty()).joinToString(" ")
            is ElementFil.Agent -> e.nom + " " + e.consigne + " " + e.resultat.orEmpty()
            is ElementFil.Note -> e.texte
            is ElementFil.Demande -> e.outil + " " + e.cible
            is ElementFil.Questions -> e.questions.joinToString(" ") { it.question }
            is ElementFil.Commande -> e.commande + " " + e.sortie.orEmpty()
            is ElementFil.Separateur, is ElementFil.Arrete, is ElementFil.Usage -> ""
        }
    }
}
