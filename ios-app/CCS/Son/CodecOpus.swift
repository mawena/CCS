import AVFoundation
import AudioToolbox

/// Formats du son partagé : PCM flottant 48 kHz stéréo (non entrelacé) et Opus (10 ms émis,
/// 10 ou 20 ms reçus).
enum FormatsSon {
    static let pcm = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: Double(Rtp.frequence),
                                   channels: AVAudioChannelCount(Rtp.canaux), interleaved: false)!

    /// Opus 48 kHz stéréo dont chaque paquet fait `echantillons` (480 = 10 ms, 960 = 20 ms).
    static func opus(_ echantillons: Int = Rtp.echantillonsParTrame) -> AVAudioFormat? {
        var d = AudioStreamBasicDescription(
            mSampleRate: Double(Rtp.frequence), mFormatID: kAudioFormatOpus, mFormatFlags: 0,
            mBytesPerPacket: 0, mFramesPerPacket: UInt32(echantillons), mBytesPerFrame: 0,
            mChannelsPerFrame: UInt32(Rtp.canaux), mBitsPerChannel: 0, mReserved: 0)
        return AVAudioFormat(streamDescription: &d)
    }

    /// Taille maximale d'une trame Opus (RFC 6716 : 1275 octets par trame).
    static let trameMax = 1500

    static func silence(_ trames: AVAudioFrameCount = AVAudioFrameCount(Rtp.echantillonsParTrame)) -> AVAudioPCMBuffer? {
        guard let b = AVAudioPCMBuffer(pcmFormat: pcm, frameCapacity: trames) else { return nil }
        b.frameLength = trames
        if let c = b.floatChannelData {
            for k in 0..<Int(pcm.channelCount) { memset(c[k], 0, Int(trames) * MemoryLayout<Float>.size) }
        }
        return b
    }
}

/**
 * Encodeur Opus d'Apple (`kAudioFormatOpus`) : `echantillons` PCM 48 kHz stéréo → une trame.
 * Trames de 10 ms (480) par défaut ; si le système les refuse, repli sur 20 ms (960). Apple
 * n'expose pas d'équivalent de `restricted-lowdelay` (CELT seul) : à 96 kb/s stéréo et 10 ms,
 * Opus choisit de lui-même le mode CELT, le plus court.
 */
final class EncodeurOpus {
    private let convertisseur: AVAudioConverter
    private let sortie: AVAudioCompressedBuffer
    /// Échantillons (par canal) d'une trame : à donner à chaque `encoder`, et pas de l'horodatage.
    let echantillons: Int

    init?(debit: Int = 96_000, echantillons voulu: Int = Rtp.echantillonsParTrame) {
        let essais = voulu == Rtp.echantillonsAncienneTrame ? [voulu] : [voulu, Rtp.echantillonsAncienneTrame]
        var trouve: (Int, AVAudioFormat, AVAudioConverter)? = nil
        for n in essais {
            if let f = FormatsSon.opus(n), let c = AVAudioConverter(from: FormatsSon.pcm, to: f) {
                trouve = (n, f, c)
                break
            }
        }
        guard let (n, f, c) = trouve else { return nil }
        c.bitRate = debit
        convertisseur = c
        echantillons = n
        let taille = max(c.maximumOutputPacketSize, FormatsSon.trameMax)
        sortie = AVAudioCompressedBuffer(format: f, packetCapacity: 4, maximumPacketSize: taille)
    }

    /// Encode une trame (`entree.frameLength` = `echantillons`) ; rend les trames produites (souvent une).
    func encoder(_ entree: AVAudioPCMBuffer) -> [Data] {
        var donne = false
        sortie.packetCount = 0
        sortie.byteLength = 0
        var erreur: NSError?
        let etat = convertisseur.convert(to: sortie, error: &erreur) { _, statut in
            if donne { statut.pointee = .noDataNow; return nil }
            donne = true
            statut.pointee = .haveData
            return entree
        }
        guard etat != .error, let descs = sortie.packetDescriptions else { return [] }
        var trames: [Data] = []
        for i in 0..<Int(sortie.packetCount) {
            let d = descs[i]
            guard d.mDataByteSize > 0 else { continue }
            trames.append(Data(bytes: sortie.data.advanced(by: Int(d.mStartOffset)), count: Int(d.mDataByteSize)))
        }
        return trames
    }
}

/**
 * Décodeur Opus d'Apple : une trame RTP → PCM 48 kHz stéréo (une trame mono est aussi acceptée).
 * Un convertisseur par durée de trame (lue dans l'octet TOC : 10 ms, 20 ms…), créé au besoin ;
 * repli sur celui de 20 ms si une durée n'est pas prise en charge.
 */
final class DecodeurOpus {
    private struct Voie { let convertisseur: AVAudioConverter; let entree: AVAudioCompressedBuffer }
    private var voies: [Int: Voie] = [:]

    init?() {
        guard voie(Rtp.echantillonsAncienneTrame) != nil else { return nil }
    }

    private func voie(_ n: Int) -> Voie? {
        if let v = voies[n] { return v }
        guard let f = FormatsSon.opus(n), let c = AVAudioConverter(from: f, to: FormatsSon.pcm) else { return nil }
        let v = Voie(convertisseur: c, entree: AVAudioCompressedBuffer(format: f, packetCapacity: 1,
                                                                     maximumPacketSize: FormatsSon.trameMax))
        voies[n] = v
        return v
    }

    func decoder(_ trame: Data) -> AVAudioPCMBuffer? {
        let n = Rtp.echantillonsOpus(trame) ?? Rtp.echantillonsAncienneTrame
        guard !trame.isEmpty, trame.count <= FormatsSon.trameMax,
              let v = voie(n) ?? voie(Rtp.echantillonsAncienneTrame),
              let sortie = AVAudioPCMBuffer(pcmFormat: FormatsSon.pcm,
                                            frameCapacity: AVAudioFrameCount(Rtp.echantillonsMax)) else { return nil }
        let entree = v.entree
        let convertisseur = v.convertisseur
        trame.withUnsafeBytes { (p: UnsafeRawBufferPointer) in
            if let b = p.baseAddress { entree.data.copyMemory(from: b, byteCount: trame.count) }
        }
        entree.byteLength = UInt32(trame.count)
        entree.packetCount = 1
        entree.packetDescriptions?.pointee = AudioStreamPacketDescription(
            mStartOffset: 0, mVariableFramesInPacket: 0, mDataByteSize: UInt32(trame.count))
        var donne = false
        var erreur: NSError?
        let etat = convertisseur.convert(to: sortie, error: &erreur) { _, statut in
            if donne { statut.pointee = .noDataNow; return nil }
            donne = true
            statut.pointee = .haveData
            return entree
        }
        guard etat != .error, sortie.frameLength > 0 else { return nil }
        return sortie
    }
}
