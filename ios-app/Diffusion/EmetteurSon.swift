import AVFoundation
import CoreMedia
import Network

/**
 * Source audio de l'iPhone, dans l'extension de diffusion : son des applis (`.audioApp`) →
 * flottants stéréo → 48 kHz (`AVAudioConverter`) → trames de 10 ms → Opus 96 kb/s → RTP en UDP
 * vers la cible du réseau maillé. Rien n'est encodé tant qu'il n'y a pas de cible. Peu de
 * mémoire (limite de 50 Mo des extensions) et peu de retard : au plus 100 ms en attente.
 *
 * Tout se passe sur la file passée à `init`.
 */
final class EmetteurSon {
    /// Plus de 100 ms en attente d'encodage (retard qui s'accumule) : on jette le plus vieux…
    static let attenteMaxMs = 100
    /// … pour ne garder que les 20 ms les plus récentes.
    static let attenteGardeeMs = 20

    private let file: DispatchQueue
    private let encodeur: EncodeurOpus?
    private var paqueteur = PaqueteurRtp()
    private var connexion: NWConnection?
    private(set) var cible: GroupeSon.Cible?
    private var reechantillonneur: AVAudioConverter?
    private var frequenceSource: Double = 0
    private var gauche: [Float] = []
    private var droite: [Float] = []
    /// Dernière trame envoyée (pour l'entretien pendant les silences).
    private(set) var dernierEnvoi = Date.distantPast

    init(file: DispatchQueue) {
        self.file = file
        encodeur = EncodeurOpus(debit: 96_000, echantillons: Rtp.echantillonsParTrame)
    }

    var pret: Bool { return encodeur != nil }

    /// Nouvelle cible (ou plus aucune) : la connexion UDP est refaite.
    func viser(_ c: GroupeSon.Cible?) {
        guard c != cible else { return }
        cible = c
        connexion?.cancel()
        connexion = nil
        gauche = []
        droite = []
        guard let c = c, let port = NWEndpoint.Port(rawValue: UInt16(clamping: c.port)) else { return }
        let n = NWConnection(host: NWEndpoint.Host(c.ip), port: port, using: .udp)
        n.start(queue: file)
        connexion = n
    }

    func fermer() {
        viser(nil)
    }

    // MARK: son capté

    func ajouter(_ sb: CMSampleBuffer) {
        guard cible != nil, encodeur != nil,
              let desc = CMSampleBufferGetFormatDescription(sb),
              let asbd = CMAudioFormatDescriptionGetStreamBasicDescription(desc)?.pointee,
              asbd.mFormatID == kAudioFormatLinearPCM else { return }
        let n = CMSampleBufferGetNumSamples(sb)
        guard n > 0 else { return }
        var taille = 0
        CMSampleBufferGetAudioBufferListWithRetainedBlockBuffer(
            sb, bufferListSizeNeededOut: &taille, bufferListOut: nil, bufferListSize: 0,
            blockBufferAllocator: nil, blockBufferMemoryAllocator: nil,
            flags: kCMSampleBufferFlag_AudioBufferList_Assure16ByteAlignment, blockBufferOut: nil)
        guard taille > 0 else { return }
        let brut = UnsafeMutableRawPointer.allocate(byteCount: taille, alignment: MemoryLayout<AudioBufferList>.alignment)
        defer { brut.deallocate() }
        let liste = brut.bindMemory(to: AudioBufferList.self, capacity: 1)
        var bloc: CMBlockBuffer?
        let statut = CMSampleBufferGetAudioBufferListWithRetainedBlockBuffer(
            sb, bufferListSizeNeededOut: nil, bufferListOut: liste, bufferListSize: taille,
            blockBufferAllocator: nil, blockBufferMemoryAllocator: nil,
            flags: kCMSampleBufferFlag_AudioBufferList_Assure16ByteAlignment, blockBufferOut: &bloc)
        guard statut == noErr else { return }
        let tampons = UnsafeMutableAudioBufferListPointer(liste).map { b in
            UnsafeRawBufferPointer(start: b.mData, count: Int(b.mDataByteSize))
        }
        let f = Pcm.Format(
            canaux: Int(asbd.mChannelsPerFrame), octets: Int(asbd.mBitsPerChannel / 8),
            flottant: asbd.mFormatFlags & kAudioFormatFlagIsFloat != 0,
            grandBoutien: asbd.mFormatFlags & kAudioFormatFlagIsBigEndian != 0,
            entrelace: asbd.mFormatFlags & kAudioFormatFlagIsNonInterleaved == 0)
        let (g, d) = Pcm.stereo(tampons, f, trames: n)
        guard !g.isEmpty else { return }
        reechantillonner(g, d, frequence: asbd.mSampleRate)
        envoyerTrames()
    }

    /// Le son de `frequence` Hz passe en 48 kHz et rejoint la file d'attente des trames.
    private func reechantillonner(_ g: [Float], _ d: [Float], frequence: Double) {
        if frequence == Double(Rtp.frequence) {
            gauche += g
            droite += d
            return
        }
        if reechantillonneur == nil || frequenceSource != frequence {
            guard let depart = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: frequence, channels: 2, interleaved: false)
            else { return }
            reechantillonneur = AVAudioConverter(from: depart, to: FormatsSon.pcm)
            frequenceSource = frequence
        }
        guard let r = reechantillonneur,
              let entree = AVAudioPCMBuffer(pcmFormat: r.inputFormat, frameCapacity: AVAudioFrameCount(g.count)),
              let ce = entree.floatChannelData else { return }
        entree.frameLength = AVAudioFrameCount(g.count)
        g.withUnsafeBufferPointer { p in ce[0].update(from: p.baseAddress!, count: g.count) }
        d.withUnsafeBufferPointer { p in ce[1].update(from: p.baseAddress!, count: d.count) }
        let capacite = AVAudioFrameCount(Double(g.count) * Double(Rtp.frequence) / frequence) + 64
        guard let sortie = AVAudioPCMBuffer(pcmFormat: FormatsSon.pcm, frameCapacity: capacite) else { return }
        var donne = false
        var erreur: NSError?
        let etat = r.convert(to: sortie, error: &erreur) { _, statut in
            if donne { statut.pointee = .noDataNow; return nil }
            donne = true
            statut.pointee = .haveData
            return entree
        }
        guard etat != .error, let cs = sortie.floatChannelData else { return }
        let k = Int(sortie.frameLength)
        gauche += UnsafeBufferPointer(start: cs[0], count: k)
        droite += UnsafeBufferPointer(start: cs[1], count: k)
    }

    /// Chaque bloc de 480 échantillons (10 ms ; 960 si l'encodeur s'est replié sur 20 ms) devient
    /// une trame Opus, envoyée dans un paquet RTP.
    private func envoyerTrames() {
        guard let e = encodeur else { return }
        let t = e.echantillons
        let parMs = Rtp.frequence / 1000
        if gauche.count > EmetteurSon.attenteMaxMs * parMs {
            let trop = gauche.count - max(t, EmetteurSon.attenteGardeeMs * parMs)
            gauche.removeFirst(trop)
            droite.removeFirst(trop)
        }
        while gauche.count >= t {
            guard let b = AVAudioPCMBuffer(pcmFormat: FormatsSon.pcm, frameCapacity: AVAudioFrameCount(t)),
                  let c = b.floatChannelData else { return }
            b.frameLength = AVAudioFrameCount(t)
            gauche.withUnsafeBufferPointer { p in c[0].update(from: p.baseAddress!, count: t) }
            droite.withUnsafeBufferPointer { p in c[1].update(from: p.baseAddress!, count: t) }
            gauche.removeFirst(t)
            droite.removeFirst(t)
            envoyer(b)
        }
    }

    private func envoyer(_ b: AVAudioPCMBuffer) {
        guard let e = encodeur, let n = connexion else { return }
        for trame in e.encoder(b) {
            let echantillons = Rtp.echantillonsOpus(trame) ?? e.echantillons
            n.send(content: paqueteur.paquet(trame, echantillons: echantillons), completion: .idempotent)
            dernierEnvoi = Date()
        }
    }

    /// Pendant un silence (ReplayKit ne donne plus rien), une trame muette par seconde garde
    /// le flux vivant : le récepteur n'abandonne qu'après 10 s sans paquet.
    func entretenir() {
        guard cible != nil, Date().timeIntervalSince(dernierEnvoi) > 1, let e = encodeur,
              let s = FormatsSon.silence(AVAudioFrameCount(e.echantillons)) else { return }
        envoyer(s)
    }
}
