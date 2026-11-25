package com.mawena.ccs.jarvis

import android.annotation.SuppressLint
import android.media.AudioAttributes
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.AudioTrack
import android.media.MediaRecorder
import android.util.Log
import com.mawena.ccs.donnees.CoffreJarvis
import com.mawena.ccs.donnees.Identifiants
import com.mawena.ccs.logique.AppairageJarvis
import com.mawena.ccs.logique.CibleAppairage
import com.mawena.ccs.logique.ErreurJarvis
import com.mawena.ccs.logique.Jarvis
import com.mawena.ccs.logique.MessageCerveau
import com.mawena.ccs.logique.PhraseJarvis
import com.mawena.ccs.logique.Reechantillonneur
import com.mawena.ccs.logique.VoixJarvis
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Deferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.async
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import okhttp3.OkHttpClient
import kotlin.random.Random

/**
 * Oreille « bouton » de Jarvis : appairage (gardé chiffré), un lien gardé ouvert tant qu'on s'en
 * sert (fermé après 2 min sans phrase), une phrase à la fois. Le micro tourne dès l'appui ; son
 * son attend le lien (tunnel Ricochet ouvert par le serveur) puis part en trames de 100 ms. La
 * réponse s'affiche et la voix de Jarvis est jouée ; s'il attend un oui / non, l'écoute reprend
 * toute seule (fin au silence). Tout l'état vit sur le fil principal.
 */
class OreilleJarvis(
    private val http: OkHttpClient,
    private val coffre: CoffreJarvis,
    private val identifiants: () -> Identifiants?,
) {
    enum class Genre { Moi, Jarvis, Erreur }

    data class Ligne(val id: Long, val qui: String, val texte: String, val genre: Genre)

    private val portee = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)

    private val _appairage = MutableStateFlow(coffre.lire())
    val appairage: StateFlow<AppairageJarvis?> = _appairage.asStateFlow()

    /** Texte d'état (vide : « Prêt. »). */
    private val _etat = MutableStateFlow("")
    val etat: StateFlow<String> = _etat.asStateFlow()

    /** Le micro écoute (de l'appui à la fin de la phrase). */
    private val _ecoute = MutableStateFlow(false)
    val ecoute: StateFlow<Boolean> = _ecoute.asStateFlow()

    private val _journal = MutableStateFlow<List<Ligne>>(emptyList())
    val journal: StateFlow<List<Ligne>> = _journal.asStateFlow()

    /** Raccourci « Parler à Jarvis », `ccs://jarvis` : l'écran Jarvis se met à écouter. */
    val demandeEcoute = MutableStateFlow(false)

    /** Adresse `jarvis://pair?…` reçue (QR code scanné) : le formulaire d'appairage la reprend. */
    val adresseRecue = MutableStateFlow<String?>(null)

    private var lien: LienJarvis? = null
    private var connexion: Deferred<LienJarvis>? = null
    private var phrase: PhraseJarvis? = null
    private var numero = Random.nextLong(0, 0x7FFF_FFFF)
    private var micro: Micro? = null
    private var piste: AudioTrack? = null
    private var lecture: Job? = null
    private var inactivite: Job? = null
    private var compteurLignes = 0L

    val nomCerveau: String get() = _appairage.value?.brainName?.takeIf { it.isNotEmpty() } ?: "Jarvis"

    // ── appairage ──

    /** `pair` avec le code de `jarvis pair` : le cerveau répond `paired` (jeton donné une fois) puis ferme. */
    suspend fun appairer(cible: CibleAppairage, nom: String) {
        val i = identifiants() ?: throw ErreurJarvis("Connecte d'abord l'appli au serveur CCS.")
        val l = LienJarvis(http, i, cible.empreinte, Jarvis.pair(cible.code, nom), portee)
        val m = l.ouvrir()
        l.fermer()
        if (m !is MessageCerveau.Appaire || m.earId.isEmpty() || m.jeton.isEmpty()) throw ErreurJarvis("Réponse inattendue de Jarvis.")
        val a = AppairageJarvis(m.earId, m.jeton, cible.empreinte, m.nom.ifEmpty { "Jarvis" }, m.cerveauId)
        coffre.ecrire(a)
        fermer()
        _journal.value = emptyList()
        _appairage.value = a
    }

    /** Oublie l'appairage sur ce téléphone (« jarvis unpair » le retire aussi côté Jarvis). */
    fun oublier() {
        fermer()
        coffre.ecrire(null)
        _appairage.value = null
        _journal.value = emptyList()
    }

    // ── phrase ──

    /**
     * Début d'une phrase (permission du micro déjà accordée). `auto` : fin au silence (appui court) ;
     * sinon [finir] au relâché. `suite` : réponse à une question de Jarvis (`listen_start`).
     */
    fun commencer(auto: Boolean, suite: Boolean = false) {
        if (phrase != null || _appairage.value == null) return
        arreterLecture()
        numero = (numero + 1) and 0xFFFF_FFFFL
        val n = numero
        phrase = PhraseJarvis(n, auto, suite, System.currentTimeMillis())
        _ecoute.value = true
        _etat.value = "Écoute…"
        micro = Micro(n).also { it.start() }
        portee.launch {
            val l = try {
                connecter()
            } catch (e: Exception) {
                if (phrase?.numero != n) return@launch
                abandonner()
                if (e is ErreurJarvis && (e.refus == "unknown_ear" || e.refus == "bad_token")) {
                    coffre.ecrire(null)
                    _appairage.value = null
                }
                signaler(e.message ?: "Jarvis est injoignable.")
                return@launch
            }
            val p = phrase
            if (p == null || p.numero != n) return@launch
            inactivite?.cancel()
            l.envoyer(if (suite) Jarvis.listenStart(n) else Jarvis.wake(n))
            p.prete = true
            envoyerTrames(toutes = false)
            if (p.finie) terminer()
        }
    }

    /** Appui court : l'écoute s'arrêtera au silence. */
    fun passerEnAuto() {
        val p = phrase ?: return
        if (p.finie) return
        p.auto = true
        _etat.value = "Écoute… (fin au silence, ou touche encore)"
    }

    /** Fin de la phrase (relâché, second appui, silence, 14 s) : `listen_end` dès que le lien est prêt. */
    fun finir() {
        val p = phrase ?: return
        if (p.finie) return
        p.finie = true
        couperMicro()
        _ecoute.value = false
        if (p.prete) terminer() else _etat.value = "Connexion à Jarvis…"
    }

    /** Écran quitté, appli en arrière-plan, déconnexion : tout s'arrête. */
    fun fermer() {
        inactivite?.cancel()
        inactivite = null
        abandonner()
        arreterLecture()
        connexion?.cancel()
        connexion = null
        lien?.fermer()
        lien = null
        _etat.value = ""
    }

    // ── lien ──

    private suspend fun connecter(): LienJarvis {
        lien?.takeIf { it.pret }?.let { return it }
        connexion?.let { return it.await() }
        val a = _appairage.value ?: throw ErreurJarvis("Appairage manquant.")
        val i = identifiants() ?: throw ErreurJarvis("Connecte d'abord l'appli au serveur CCS.")
        val l = LienJarvis(http, i, a.fingerprint, Jarvis.hello(a), portee)
        l.surMessage = { recu(it) }
        l.surFin = { fin(l, it) }
        val d = portee.async {
            val premier = try {
                l.ouvrir()
            } catch (e: kotlinx.coroutines.CancellationException) {
                l.fermer()                      // oreille fermée pendant l'ouverture
                throw e
            }
            if (premier is MessageCerveau.Bienvenue && premier.nom.isNotEmpty() && premier.nom != _appairage.value?.brainName) {
                _appairage.value?.copy(brainName = premier.nom)?.let { coffre.ecrire(it); _appairage.value = it }
            }
            l
        }
        connexion = d
        try {
            val pret = d.await()
            lien = pret
            armerInactivite()                   // annulé dès qu'une phrase part
            return pret
        } finally {
            if (connexion === d) connexion = null
        }
    }

    private fun fin(l: LienJarvis, texte: String?) {
        if (l !== lien) return
        lien = null
        val attendait = phrase != null || _etat.value == "Jarvis réfléchit…"
        abandonner()
        _etat.value = ""
        if (texte != null) signaler(texte) else if (attendait) signaler("Lien avec Jarvis fermé.")
    }

    private fun recu(m: MessageCerveau) {
        when (m) {
            is MessageCerveau.Stop -> if (phrase?.numero == m.phrase) {
                abandonner()
                signaler("Jarvis est occupé par une autre phrase : réessaie dans un instant.")
            }
            is MessageCerveau.Entendu -> {
                armerInactivite()
                _etat.value = ""
                ajouter("Toi", m.texte, Genre.Moi)
                ajouter(nomCerveau, m.voix, Genre.Jarvis)
                jouer(m.audio, m.attendReponse)
            }
            is MessageCerveau.Reponse -> {
                armerInactivite()
                _etat.value = ""
                ajouter(nomCerveau, m.voix, Genre.Jarvis)
            }
            is MessageCerveau.Erreur -> {
                armerInactivite()
                _etat.value = ""
                signaler(m.message)
            }
            is MessageCerveau.Refus -> signaler(Jarvis.texteRefus(m.motif, m.essais))
            else -> Unit
        }
    }

    private fun armerInactivite() {
        inactivite?.cancel()
        inactivite = portee.launch {
            delay(Jarvis.INACTIVITE_MS)
            if (phrase != null) return@launch
            lien?.fermer()
            lien = null
        }
    }

    // ── son de la phrase ──

    private fun morceau(n: Long, e: ShortArray, fort: Boolean) {
        val p = phrase ?: return
        if (p.numero != n || p.finie) return
        val stop = p.ajouter(e, fort, System.currentTimeMillis())
        envoyerTrames(toutes = false)
        if (stop) finir()
    }

    private fun envoyerTrames(toutes: Boolean) {
        val p = phrase ?: return
        for (t in p.trames(toutes)) lien?.envoyer(t)
    }

    private fun terminer() {
        val p = phrase ?: return
        envoyerTrames(toutes = true)
        val vide = p.sansParole
        lien?.envoyer(Jarvis.listenEnd(p.numero, vide))
        phrase = null
        _ecoute.value = false
        _etat.value = if (vide) "" else "Jarvis réfléchit…"
        if (vide) signaler("Rien entendu.")
        armerInactivite()
    }

    /** Phrase abandonnée (erreur, lien coupé, autre oreille) : `listen_end` sans parole si elle avait commencé. */
    private fun abandonner() {
        val p = phrase ?: return
        phrase = null
        _ecoute.value = false
        couperMicro()
        if (p.prete && !p.finie) lien?.envoyer(Jarvis.listenEnd(p.numero, true))
        _etat.value = ""
    }

    private fun couperMicro() {
        micro?.actif = false
        micro = null
    }

    private fun microIndisponible(n: Long) {
        if (phrase?.numero != n) return
        abandonner()
        signaler("Micro indisponible (autorise-le pour CCS, ou une autre appli s'en sert).")
    }

    /** Micro : `AudioRecord` en flottants, lu par blocs de 20 ms sur son propre fil. */
    private inner class Micro(private val n: Long) : Thread("jarvis-micro") {
        @Volatile var actif = true

        @SuppressLint("MissingPermission")         // vérifiée par l'écran avant chaque phrase
        private fun ouvrir(): Pair<AudioRecord, Int>? {
            for (frequence in intArrayOf(16_000, 48_000, 44_100)) {
                val min = AudioRecord.getMinBufferSize(frequence, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_FLOAT)
                if (min <= 0) continue
                try {
                    val r = AudioRecord(
                        MediaRecorder.AudioSource.VOICE_RECOGNITION, frequence,
                        AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_FLOAT, maxOf(min, frequence / 5 * 4),
                    )
                    if (r.state == AudioRecord.STATE_INITIALIZED) return r to frequence
                    r.release()
                } catch (e: Exception) {
                    Log.w(TAG, "AudioRecord à $frequence Hz", e)
                }
            }
            return null
        }

        override fun run() {
            val (r, frequence) = ouvrir() ?: run {
                portee.launch { microIndisponible(n) }
                return
            }
            try {
                r.startRecording()
                if (r.recordingState != AudioRecord.RECORDSTATE_RECORDING) {
                    portee.launch { microIndisponible(n) }
                    return
                }
                val reech = Reechantillonneur(frequence)
                val bloc = FloatArray(frequence / 50)
                while (actif) {
                    val lu = r.read(bloc, 0, bloc.size, AudioRecord.READ_BLOCKING)
                    if (lu < 0) {
                        portee.launch { microIndisponible(n) }
                        return
                    }
                    if (lu == 0 || !actif) continue
                    val fort = Jarvis.rms(bloc, lu) > Jarvis.SEUIL_PAROLE
                    val e = reech.pousser(bloc, lu)
                    portee.launch { morceau(n, e, fort) }
                }
            } catch (e: Exception) {
                Log.w(TAG, "micro", e)
                portee.launch { microIndisponible(n) }
            } finally {
                try { r.stop() } catch (_: IllegalStateException) { }
                r.release()
            }
        }
    }

    // ── voix de Jarvis ──

    private fun jouer(audio: VoixJarvis?, puisEcouter: Boolean) {
        arreterLecture()
        val pcm = audio?.let { Jarvis.decoderPcm(it.pcm) } ?: ShortArray(0)
        val t = if (audio != null && pcm.isNotEmpty()) piste(pcm, audio.frequence) else null
        if (t == null) {
            if (puisEcouter) commencer(auto = true, suite = true)
            return
        }
        piste = t
        t.play()
        lecture = portee.launch {
            delay(pcm.size * 1000L / audio!!.frequence + 150)
            if (piste !== t) return@launch
            arreterLecture()
            if (puisEcouter) commencer(auto = true, suite = true)
        }
    }

    private fun piste(pcm: ShortArray, frequence: Int): AudioTrack? = try {
        val t = AudioTrack.Builder()
            .setAudioAttributes(
                AudioAttributes.Builder()
                    .setUsage(AudioAttributes.USAGE_ASSISTANT)
                    .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
                    .build(),
            )
            .setAudioFormat(
                AudioFormat.Builder()
                    .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                    .setSampleRate(frequence)
                    .setChannelMask(AudioFormat.CHANNEL_OUT_MONO)
                    .build(),
            )
            .setTransferMode(AudioTrack.MODE_STATIC)
            .setBufferSizeInBytes(pcm.size * 2)
            .build()
        t.write(pcm, 0, pcm.size)
        t
    } catch (e: Exception) {
        Log.w(TAG, "voix", e)
        null
    }

    private fun arreterLecture() {
        lecture?.cancel()
        lecture = null
        val t = piste ?: return
        piste = null
        try { t.stop() } catch (_: IllegalStateException) { }
        t.release()
    }

    // ── journal ──

    private fun ajouter(qui: String, texte: String, genre: Genre) {
        if (texte.isEmpty()) return
        _journal.value = (listOf(Ligne(compteurLignes++, qui, texte, genre)) + _journal.value).take(HISTORIQUE)
    }

    private fun signaler(texte: String) {
        ajouter("", texte, Genre.Erreur)
        if (!_ecoute.value) _etat.value = ""
    }

    private companion object {
        const val TAG = "JarvisCcs"
        const val HISTORIQUE = 20
    }
}
