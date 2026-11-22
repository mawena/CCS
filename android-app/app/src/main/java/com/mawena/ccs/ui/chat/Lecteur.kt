package com.mawena.ccs.ui.chat

import android.content.Context
import android.os.Bundle
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import com.mawena.ccs.logique.Vocal
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import java.util.Locale

/**
 * Lecture à voix haute des réponses de Claude (phase 35) par la synthèse vocale d'Android, en
 * français. Créée au premier usage (la synthèse met un moment à démarrer : le texte attend), une
 * seule lecture à la fois. [lu] : clé du message en cours de lecture (null : rien). À [fermer]
 * quand le chat disparaît.
 */
class Lecteur(private val ctx: Context, private val dire: (String) -> Unit) {
    private var tts: TextToSpeech? = null
    private var pret = false
    private var attente: Pair<String, String>? = null      // (clé, texte) demandé avant la fin du démarrage
    @Volatile private var dernier: String? = null          // identifiant du dernier morceau de la lecture en cours

    private val _lu = MutableStateFlow<String?>(null)
    val lu: StateFlow<String?> = _lu.asStateFlow()

    /** Lit le message (Markdown) ; s'il est déjà en cours de lecture, l'arrête. */
    fun basculer(cle: String, markdown: String) {
        if (_lu.value == cle) arreter() else lire(cle, markdown)
    }

    /** Lit le message (Markdown), en coupant la lecture en cours. */
    fun lire(cle: String, markdown: String) {
        val texte = Vocal.pourLecture(markdown)
        if (texte.isEmpty()) return
        _lu.value = cle
        val t = tts
        if (t == null || !pret) {
            attente = cle to texte
            if (t == null) demarrer()
            return
        }
        parler(t, cle, texte)
    }

    fun arreter() {
        attente = null
        dernier = null
        _lu.value = null
        if (pret) tts?.stop()
    }

    /** Libère la synthèse vocale (écran du chat fermé pour de bon). */
    fun fermer() {
        attente = null
        dernier = null
        _lu.value = null
        tts?.stop()
        tts?.shutdown()
        tts = null
        pret = false
    }

    /** Crée la synthèse ; son démarrage est signalé plus tard (rarement tout de suite, en cas d'échec). */
    private fun demarrer() {
        var synchrone = true
        var statutImmediat: Int? = null
        val t = TextToSpeech(ctx.applicationContext) { statut ->
            if (synchrone) {
                statutImmediat = statut
            } else {
                initialiser(statut)
            }
        }
        tts = t
        synchrone = false
        statutImmediat?.let { initialiser(it) }
    }

    private fun initialiser(statut: Int) {
        val t = tts ?: return                                  // fermé entre-temps
        if (statut != TextToSpeech.SUCCESS) {
            echec("Synthèse vocale indisponible sur ce téléphone.")
            return
        }
        val langue = t.setLanguage(Locale.FRENCH)
        if (langue == TextToSpeech.LANG_MISSING_DATA || langue == TextToSpeech.LANG_NOT_SUPPORTED) {
            echec("Voix française absente : installe-la dans les réglages d'Android (Synthèse vocale).")
            return
        }
        t.setOnUtteranceProgressListener(object : UtteranceProgressListener() {
            override fun onStart(utteranceId: String?) {}
            override fun onDone(utteranceId: String?) = fin(utteranceId)
            @Deprecated("Remplacée par onError(String, Int) dans Android, mais toujours abstraite")
            override fun onError(utteranceId: String?) = fin(utteranceId)
            override fun onError(utteranceId: String?, errorCode: Int) = fin(utteranceId)
        })
        pret = true
        attente?.let { (cle, texte) -> attente = null; parler(t, cle, texte) }
    }

    private fun echec(message: String) {
        tts?.shutdown()
        tts = null
        pret = false
        attente = null
        _lu.value = null
        dire(message)
    }

    /** Fin d'un morceau (appelé par la synthèse, sur un autre fil) : la lecture est finie après le dernier. */
    private fun fin(id: String?) {
        if (id != null && id == dernier) {
            dernier = null
            _lu.value = null
        }
    }

    private fun parler(t: TextToSpeech, cle: String, texte: String) {
        val max = (TextToSpeech.getMaxSpeechInputLength() - 1).coerceAtLeast(100)
        val morceaux = Vocal.decouper(texte, max)
        val jeton = "$cle#${System.nanoTime()}"
        dernier = "$jeton/${morceaux.size - 1}"
        morceaux.forEachIndexed { i, m ->
            val mode = if (i == 0) TextToSpeech.QUEUE_FLUSH else TextToSpeech.QUEUE_ADD
            if (t.speak(m, mode, Bundle(), "$jeton/$i") == TextToSpeech.ERROR) {
                arreter()
                dire("La lecture n'a pas pu démarrer.")
                return
            }
        }
    }
}
