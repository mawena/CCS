package com.mawena.ccs.son

import android.annotation.SuppressLint
import android.media.AudioAttributes
import android.media.AudioFormat
import android.media.AudioPlaybackCaptureConfiguration
import android.media.AudioRecord
import android.media.MediaCodec
import android.media.MediaFormat
import android.media.projection.MediaProjection
import android.os.Build
import android.util.Log
import androidx.annotation.RequiresApi
import com.mawena.ccs.logique.Audio
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress
import java.net.InetSocketAddress

/**
 * Capte le son des autres applis (AudioPlaybackCapture, Android 10+, avec l'accord
 * MediaProjection), l'encode en Opus (MediaCodec, 96 kb/s, trames de 20 ms) et l'envoie en RTP
 * vers [viser]. Tant qu'aucune destination n'est fixée, les trames sont jetées. [fin] est appelé
 * (une fois) si la capture s'arrête d'elle-même.
 */
@RequiresApi(Build.VERSION_CODES.Q)
class CaptureSon(private val projection: MediaProjection, private val fin: (String?) -> Unit) {
    private class Cible(val adresse: InetSocketAddress, val numeroteur: Audio.Numeroteur)

    @Volatile private var actif = true
    @Volatile private var cible: Cible? = null
    private var fil: Thread? = null
    private var finie = false

    /** Nouvelle destination (nouveau flux : nouvelle numérotation RTP). */
    fun viser(ip: String, port: Int) {
        // adresse littérale : pas de résolution DNS
        cible = Cible(InetSocketAddress(InetAddress.getByName(ip), port), Audio.Numeroteur.auHasard())
    }

    fun demarrer() {
        fil = Thread(::tourner, "ccs-son-capture").apply { start() }
    }

    fun arreter() {
        actif = false
        fil?.interrupt()
        fil?.join(1_000)
    }

    @Synchronized
    private fun terminer(erreur: String?) {
        if (finie) return
        finie = true
        actif = false
        fin(erreur)
    }

    @SuppressLint("MissingPermission")     // RECORD_AUDIO demandée avant l'accord de capture
    private fun ouvrirCapture(): AudioRecord {
        val config = AudioPlaybackCaptureConfiguration.Builder(projection)
            .addMatchingUsage(AudioAttributes.USAGE_MEDIA)
            .addMatchingUsage(AudioAttributes.USAGE_GAME)
            .addMatchingUsage(AudioAttributes.USAGE_UNKNOWN)
            .build()
        val format = AudioFormat.Builder().setEncoding(AudioFormat.ENCODING_PCM_16BIT)
            .setSampleRate(Audio.FREQUENCE).setChannelMask(AudioFormat.CHANNEL_IN_STEREO).build()
        val min = AudioRecord.getMinBufferSize(Audio.FREQUENCE, AudioFormat.CHANNEL_IN_STEREO, AudioFormat.ENCODING_PCM_16BIT)
        val r = AudioRecord.Builder()
            .setAudioFormat(format)
            .setBufferSizeInBytes(maxOf(min, OCTETS_TRAME * 8))
            .setAudioPlaybackCaptureConfig(config)
            .build()
        if (r.state != AudioRecord.STATE_INITIALIZED) {
            r.release()
            throw IllegalStateException("capture du son refusée")
        }
        return r
    }

    private fun ouvrirEncodeur(): MediaCodec {
        val format = MediaFormat.createAudioFormat(MediaFormat.MIMETYPE_AUDIO_OPUS, Audio.FREQUENCE, Audio.CANAUX).apply {
            setInteger(MediaFormat.KEY_BIT_RATE, Audio.DEBIT)
            setInteger(MediaFormat.KEY_MAX_INPUT_SIZE, OCTETS_TRAME * 2)
        }
        val e = MediaCodec.createEncoderByType(MediaFormat.MIMETYPE_AUDIO_OPUS)
        try {
            e.configure(format, null, null, MediaCodec.CONFIGURE_FLAG_ENCODE)
            e.start()
        } catch (x: Exception) {
            e.release()
            throw x
        }
        return e
    }

    private fun tourner() {
        runCatching { android.os.Process.setThreadPriority(android.os.Process.THREAD_PRIORITY_URGENT_AUDIO) }
        var capture: AudioRecord? = null
        var encodeur: MediaCodec? = null
        var socket: DatagramSocket? = null
        try {
            val cap = ouvrirCapture().also { capture = it }
            val enc = ouvrirEncodeur().also { encodeur = it }
            val sock = DatagramSocket().also { socket = it }
            cap.startRecording()
            val bloc = ByteArray(OCTETS_TRAME)
            val info = MediaCodec.BufferInfo()
            var trame = ByteArray(1500)
            var echantillons = 0L

            // trames Opus prêtes (hors en-têtes de configuration) : un paquet RTP chacune
            fun vider() {
                while (true) {
                    val o = enc.dequeueOutputBuffer(info, 0)
                    if (o == MediaCodec.INFO_OUTPUT_FORMAT_CHANGED) continue
                    if (o < 0) return
                    val c = cible
                    if (c != null && info.size > 0 && info.flags and MediaCodec.BUFFER_FLAG_CODEC_CONFIG == 0) {
                        val b = enc.getOutputBuffer(o)
                        if (b != null) {
                            if (trame.size < info.size) trame = ByteArray(info.size)
                            b.position(info.offset)
                            b.get(trame, 0, info.size)
                            val p = c.numeroteur.paquet(trame.copyOf(info.size))
                            try {
                                sock.send(DatagramPacket(p, p.size, c.adresse))
                            } catch (e: Exception) {
                                Log.d(TAG, "envoi UDP : ${e.message}")     // réseau maillé coupé un instant
                            }
                        }
                    }
                    enc.releaseOutputBuffer(o, false)
                }
            }

            while (actif) {
                val lu = cap.read(bloc, 0, bloc.size)
                if (lu < 0) throw IllegalStateException("lecture de la capture ($lu)")
                var debut = 0
                while (debut < lu && actif) {
                    val i = enc.dequeueInputBuffer(10_000)
                    if (i < 0) { vider(); continue }
                    val b = enc.getInputBuffer(i) ?: continue
                    b.clear()
                    val n = minOf(b.remaining(), lu - debut)
                    b.put(bloc, debut, n)
                    enc.queueInputBuffer(i, 0, n, echantillons * 1_000_000L / Audio.FREQUENCE, 0)
                    echantillons += n / (2 * Audio.CANAUX)
                    debut += n
                }
                vider()
            }
        } catch (e: InterruptedException) {
            // arrêt
        } catch (e: Exception) {
            Log.w(TAG, "capture", e)
            if (actif) terminer("Capture du son impossible : ${e.message}")
        } finally {
            runCatching { capture?.stop() }
            runCatching { capture?.release() }
            runCatching { encodeur?.stop() }
            runCatching { encodeur?.release() }
            runCatching { socket?.close() }
        }
    }

    private companion object {
        const val TAG = "CaptureSon"
        /** 20 ms de PCM 16 bits stéréo à 48 kHz. */
        const val OCTETS_TRAME = Audio.ECHANTILLONS_TRAME * Audio.CANAUX * 2
    }
}
