import AVFoundation
import AudioToolbox

/// Formats du son partagé : PCM flottant 48 kHz stéréo (non entrelacé) et Opus 20 ms.
enum FormatsSon {
    static let pcm = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: Double(Rtp.frequence),
                                   channels: AVAudioChannelCount(Rtp.canaux), interleaved: false)!

    static let opus: AVAudioFormat = {
        var d = AudioStreamBasicDescription(
            mSampleRate: Double(Rtp.frequence), mFormatID: kAudioFormatOpus, mFormatFlags: 0,
            mBytesPerPacket: 0, mFramesPerPacket: UInt32(Rtp.echantillonsParTrame), mBytesPerFrame: 0,
            mChannelsPerFrame: UInt32(Rtp.canaux), mBitsPerChannel: 0, mReserved: 0)
        return AVAudioFormat(streamDescription: &d)!
    }()

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

/// Encodeur Opus d'Apple (`kAudioFormatOpus`) : 960 échantillons PCM 48 kHz stéréo → une trame.
final class EncodeurOpus {
    private let convertisseur: AVAudioConverter
    private let sortie: AVAudioCompressedBuffer

    init?(debit: Int = 96_000) {
        guard let c = AVAudioConverter(from: FormatsSon.pcm, to: FormatsSon.opus) else { return nil }
        c.bitRate = debit
        convertisseur = c
        let taille = max(c.maximumOutputPacketSize, FormatsSon.trameMax)
        sortie = AVAudioCompressedBuffer(format: FormatsSon.opus, packetCapacity: 4, maximumPacketSize: taille)
    }

    /// Encode 20 ms (`entree.frameLength` = 960) ; rend les trames produites (souvent une).
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

/// Décodeur Opus d'Apple : une trame RTP → PCM 48 kHz stéréo (une trame mono est aussi acceptée).
final class DecodeurOpus {
    private let convertisseur: AVAudioConverter
    private let entree: AVAudioCompressedBuffer

    init?() {
        guard let c = AVAudioConverter(from: FormatsSon.opus, to: FormatsSon.pcm) else { return nil }
        convertisseur = c
        entree = AVAudioCompressedBuffer(format: FormatsSon.opus, packetCapacity: 1, maximumPacketSize: FormatsSon.trameMax)
    }

    func decoder(_ trame: Data) -> AVAudioPCMBuffer? {
        guard !trame.isEmpty, trame.count <= FormatsSon.trameMax,
              let sortie = AVAudioPCMBuffer(pcmFormat: FormatsSon.pcm, frameCapacity: 5760) else { return nil }
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
            return self.entree
        }
        guard etat != .error, sortie.frameLength > 0 else { return nil }
        return sortie
    }
}
