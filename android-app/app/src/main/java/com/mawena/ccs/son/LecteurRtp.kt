package com.mawena.ccs.son

import android.media.AudioAttributes
import android.media.AudioFormat
import android.media.AudioTrack
import android.media.MediaCodec
import android.media.MediaFormat
import android.os.SystemClock
import android.util.Log
import com.mawena.ccs.logique.Audio
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetSocketAddress
import java.net.SocketTimeoutException
import java.nio.ByteBuffer

/**
 * Joue un flux RTP/Opus reçu en UDP sur [port] : un fil reçoit les paquets dans le tampon de gigue,
 * un autre prend une trame à chaque tic (10 ou 20 ms selon la durée lue dans le paquet), la décode
 * (MediaCodec `audio/opus`) et l'écrit dans un AudioTrack en mode faible latence. Le tampon de gigue
 * est adaptatif ([Audio.GigueAdaptative], 20 à 150 ms). [fin] est appelé (une fois) quand la lecture s'arrête d'elle-même : 10 s sans
 * paquet, port déjà pris, décodeur introuvable.
 */
class LecteurRtp(private val port: Int, private val canaux: Int, private val fin: (String?) -> Unit) {
    @Volatile private var actif = true
    @Volatile private var dernierPaquet = SystemClock.elapsedRealtime()
    private val gigue = Audio.GigueAdaptative()
    private var ssrc: Long? = null
    private var socket: DatagramSocket? = null
    private var filReception: Thread? = null
    private var filLecture: Thread? = null
    private var finie = false

    fun demarrer() {
        val s = try {
            DatagramSocket(null).apply {
                reuseAddress = true
                soTimeout = 250
                receiveBufferSize = 256 * 1024
                bind(InetSocketAddress(port))
            }
        } catch (e: Exception) {
            Log.w(TAG, "port $port", e)
            terminer("Port UDP $port indisponible : ${e.message}")
            return
        }
        socket = s
        filReception = Thread({ recevoir(s) }, "ccs-son-reception").apply { start() }
        filLecture = Thread(::jouer, "ccs-son-lecture").apply {
            priority = Thread.MAX_PRIORITY
            start()
        }
    }

    fun arreter() {
        actif = false
        socket?.close()
        filReception?.join(500)
        filLecture?.join(500)
    }

    @Synchronized
    private fun terminer(erreur: String?) {
        if (finie) return
        finie = true
        actif = false
        fin(erreur)
    }

    private fun recevoir(s: DatagramSocket) {
        val tampon2 = ByteArray(4096)
        val dp = DatagramPacket(tampon2, tampon2.size)
        while (actif) {
            try {
                dp.length = tampon2.size
                s.receive(dp)
            } catch (_: SocketTimeoutException) {
                if (SystemClock.elapsedRealtime() - dernierPaquet > Audio.SILENCE_MAX_MS) terminer(null)
                continue
            } catch (e: Exception) {
                if (actif) terminer("Réception coupée : ${e.message}")
                break
            }
            val p = Audio.lireRtp(tampon2, dp.length) ?: continue
            if (p.donnees.isEmpty()) continue
            dernierPaquet = SystemClock.elapsedRealtime()
            synchronized(gigue) {
                if (ssrc != p.ssrc) {
                    gigue.vider()        // autre émetteur, ou émetteur relancé
                    ssrc = p.ssrc
                }
                gigue.ajouter(p.sequence, p.donnees)
            }
        }
        runCatching { s.close() }
    }

    private fun jouer() {
        runCatching { android.os.Process.setThreadPriority(android.os.Process.THREAD_PRIORITY_URGENT_AUDIO) }
        // en-tête OpusHead (csd-0), délai du codec (csd-1) et pré-roulage (csd-2), comme l'exige MediaCodec
        val decodeur: MediaCodec = try {
            MediaCodec.createDecoderByType(MediaFormat.MIMETYPE_AUDIO_OPUS).also { d ->
                val format = MediaFormat.createAudioFormat(MediaFormat.MIMETYPE_AUDIO_OPUS, Audio.FREQUENCE, canaux).apply {
                    setByteBuffer("csd-0", ByteBuffer.wrap(Audio.opusHead(canaux)))
                    setByteBuffer("csd-1", ByteBuffer.wrap(Audio.csdNanos(Audio.delaiCodecNanos(0))))
                    setByteBuffer("csd-2", ByteBuffer.wrap(Audio.csdNanos(Audio.PREROULAGE_NANOS)))
                }
                try {
                    d.configure(format, null, null, 0)
                    d.start()
                } catch (e: Exception) {
                    d.release()
                    throw e
                }
            }
        } catch (e: Exception) {
            Log.w(TAG, "décodeur Opus", e)
            terminer("Décodeur Opus indisponible : ${e.message}")
            return
        }
        val octetsEchantillon = canaux * 2
        val piste: AudioTrack = try {
            val masque = if (canaux == 1) AudioFormat.CHANNEL_OUT_MONO else AudioFormat.CHANNEL_OUT_STEREO
            val min = AudioTrack.getMinBufferSize(Audio.FREQUENCE, masque, AudioFormat.ENCODING_PCM_16BIT)
            AudioTrack.Builder()
                .setAudioAttributes(
                    AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_MEDIA)
                        .setContentType(AudioAttributes.CONTENT_TYPE_MUSIC).build(),
                )
                .setAudioFormat(
                    AudioFormat.Builder().setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                        .setSampleRate(Audio.FREQUENCE).setChannelMask(masque).build(),
                )
                // tampon minimal : le tampon de gigue absorbe déjà les retards du réseau
                .setBufferSizeInBytes(maxOf(min, Audio.FREQUENCE / 1000 * PISTE_MS * octetsEchantillon))
                .setPerformanceMode(AudioTrack.PERFORMANCE_MODE_LOW_LATENCY)
                .setTransferMode(AudioTrack.MODE_STREAM)
                .build()
                .also { it.play() }
        } catch (e: Exception) {
            Log.w(TAG, "AudioTrack", e)
            runCatching { decodeur.stop(); decodeur.release() }
            terminer("Sortie audio indisponible : ${e.message}")
            return
        }
        val silence = ByteArray(Audio.FREQUENCE / 1000 * maxOf(AVANCE_MS, 20) * octetsEchantillon)
        val info = MediaCodec.BufferInfo()
        var pcm = ByteArray(Audio.ECHANTILLONS_ANCIENNE_TRAME * octetsEchantillon * 2)
        var pts = 0L
        var enLecture = false

        // sorties du décodeur prêtes : écrites dans l'AudioTrack
        fun vider(attenteUs: Long) {
            var attente = attenteUs
            while (actif) {
                val o = decodeur.dequeueOutputBuffer(info, attente)
                attente = 0
                when {
                    o >= 0 -> {
                        if (info.size > 0) {
                            val b = decodeur.getOutputBuffer(o)
                            if (b != null) {
                                if (pcm.size < info.size) pcm = ByteArray(info.size)
                                b.position(info.offset)
                                b.get(pcm, 0, info.size)
                                piste.write(pcm, 0, info.size)
                            }
                        }
                        decodeur.releaseOutputBuffer(o, false)
                    }
                    o == MediaCodec.INFO_OUTPUT_FORMAT_CHANGED -> Unit
                    else -> return
                }
            }
        }

        try {
            var tic = System.nanoTime()
            while (actif) {
                val maintenant = System.nanoTime()
                if (maintenant < tic) {
                    val ms = (tic - maintenant) / 1_000_000
                    if (ms > 0) Thread.sleep(ms) else Thread.yield()
                    continue
                }
                // durée d'un tic : celle des trames reçues (10 ms, ou 20 ms d'un ancien émetteur)
                var echantillons = 0
                val s = synchronized(gigue) {
                    echantillons = gigue.echantillons
                    gigue.prendre()
                }
                val trameNs = echantillons * 1_000_000_000L / Audio.FREQUENCE
                val octetsTrame = minOf(silence.size, echantillons * octetsEchantillon)
                tic += trameNs
                if (tic < maintenant - 5 * trameNs) tic = maintenant + trameNs     // fil en retard : on se recale
                when (s) {
                    Audio.Sortie.Attente -> enLecture = false
                    Audio.Sortie.Perte -> piste.write(silence, 0, octetsTrame)
                    is Audio.Sortie.Trame -> {
                        if (!enLecture) {
                            // départ : un peu de marge dans l'AudioTrack contre les retards du fil
                            piste.write(silence, 0, Audio.FREQUENCE / 1000 * AVANCE_MS * octetsEchantillon)
                            enLecture = true
                        }
                        val i = decodeur.dequeueInputBuffer(10_000)
                        if (i >= 0) {
                            val b = decodeur.getInputBuffer(i)
                            if (b != null) {
                                b.clear()
                                b.put(s.donnees)
                                decodeur.queueInputBuffer(i, 0, s.donnees.size, pts, 0)
                                pts += (Audio.echantillonsOpus(s.donnees) ?: echantillons) * 1_000_000L / Audio.FREQUENCE
                            } else {
                                decodeur.queueInputBuffer(i, 0, 0, pts, 0)
                            }
                        }
                        vider(5_000)
                    }
                }
            }
        } catch (e: InterruptedException) {
            // arrêt
        } catch (e: Exception) {
            Log.w(TAG, "lecture", e)
            terminer("Lecture interrompue : ${e.message}")
        } finally {
            runCatching { piste.pause(); piste.flush(); piste.release() }
            runCatching { decodeur.stop(); decodeur.release() }
        }
    }

    private companion object {
        const val TAG = "LecteurRtp"
        /** Tampon de l'AudioTrack (au moins le minimum du matériel). */
        const val PISTE_MS = 40
        /** Silence écrit au départ d'un flux, contre les retards du fil de lecture. */
        const val AVANCE_MS = 20
    }
}
