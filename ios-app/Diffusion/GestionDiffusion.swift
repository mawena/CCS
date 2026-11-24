import Foundation
import ReplayKit

/**
 * Extension de diffusion ReplayKit de CCS (« CCS » dans le sélecteur de diffusion et le centre de
 * contrôle) : envoie le son de l'iPhone vers une sortie du réseau maillé (phase 42). La cible est
 * écrite par l'appli dans le groupe d'applis ; relue chaque seconde, comme la demande d'arrêt.
 * La vidéo de l'écran est ignorée.
 */
final class GestionDiffusion: RPBroadcastSampleHandler {
    private let file = DispatchQueue(label: "ccs.diffusion", qos: .userInteractive)
    private var emetteur: EmetteurSon?
    private var minuteur: DispatchSourceTimer?

    override func broadcastStarted(withSetupInfo setupInfo: [String: NSObject]?) {
        _ = GroupeSon.prendreArret()          // demande d'arrêt restée d'une diffusion précédente
        GroupeSon.ecrireErreur(nil)
        file.sync {
            let e = EmetteurSon(file: file)
            emetteur = e
            if !e.pret { GroupeSon.ecrireErreur("Encodeur Opus indisponible sur cet iPhone.") }
            e.viser(GroupeSon.lireCible())
        }
        GroupeSon.battre(true)
        let t = DispatchSource.makeTimerSource(queue: file)
        t.schedule(deadline: .now() + 1, repeating: 1)
        t.setEventHandler { [weak self] in self?.tic() }
        t.resume()
        minuteur = t
    }

    private func tic() {
        GroupeSon.battre(true)
        if GroupeSon.prendreArret() {
            let e = NSError(domain: "CCS", code: 1, userInfo: [NSLocalizedDescriptionKey: "Son arrêté depuis CCS."])
            finir()
            finishBroadcastWithError(e)
            return
        }
        emetteur?.viser(GroupeSon.lireCible())
        emetteur?.entretenir()
    }

    override func processSampleBuffer(_ sampleBuffer: CMSampleBuffer, with sampleBufferType: RPSampleBufferType) {
        guard sampleBufferType == .audioApp else { return }
        file.sync { emetteur?.ajouter(sampleBuffer) }
    }

    override func broadcastFinished() {
        finir()
    }

    private func finir() {
        minuteur?.cancel()
        minuteur = nil
        file.async { [weak self] in
            self?.emetteur?.fermer()
            self?.emetteur = nil
        }
        GroupeSon.battre(false)
    }
}
