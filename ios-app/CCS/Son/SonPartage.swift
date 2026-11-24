import Foundation
import Observation
import UIKit
import UserNotifications

/**
 * Son partagé sur le réseau maillé (phase 42, `docs/audio.md`) côté appli : annonce de l'iPhone
 * au pont toutes les 30 s tant que l'appli est connectée (sortie et source, système « ios »),
 * événements `audio` qui le nomment (écouter, émettre, arrêter), liste des appareils et des flux
 * pour l'écran Son. Le son reçu est joué par `RecepteurSon` ; le son émis part de l'extension de
 * diffusion ReplayKit (`Diffusion/`), à qui la cible est passée par le groupe d'applis.
 *
 * « Rester à l'écoute » (réglage gardé, désactivé par défaut) : tant que l'appli tourne, le
 * récepteur reste ouvert sur le port annoncé en mode permanent (silence joué, tout paquet RTP
 * joué tout de suite, même sans événement « receive ») ; rouvert à l'annonce suivante s'il tombe.
 */
@MainActor
@Observable
final class SonPartage {
    /// Nom de l'iPhone sur le réseau maillé (vide tant qu'il n'est pas connu).
    private(set) var moi = ""
    /// Adresse 100.64.x de l'iPhone (nil : Tailscale pas connecté).
    private(set) var ip: String? = nil
    /// Dernière annonce acceptée par le pont.
    private(set) var annonceLe: Date? = nil
    /// Pourquoi l'annonce échoue (pas de réseau maillé, refus du pont…).
    private(set) var probleme: String? = nil
    private(set) var liste = ListeSon()
    /// Flux joué par l'iPhone : identifiant et nom de la source.
    private(set) var ecoute: (flux: String, de: String)? = nil
    /// Cible de la diffusion demandée à l'extension (nom affiché).
    private(set) var cibleDiffusion: String? = nil
    /// Monte de 1 à chaque fois qu'il faut montrer le sélecteur de diffusion de ReplayKit.
    private(set) var demandeDiffusion = 0
    /// Réglage « Rester à l'écoute » (`Prefs.resterALEcoute`).
    var resterALEcoute: Bool = Prefs.resterALEcoute {
        didSet {
            guard resterALEcoute != oldValue else { return }
            Prefs.resterALEcoute = resterALEcoute
            appliquerEcoute()
        }
    }
    /// À l'écoute en permanence : un son arrive (reçu depuis moins de 10 s).
    private(set) var sonRecu = false

    @ObservationIgnored private let client: CcsClient
    @ObservationIgnored private let dire: (String) -> Void
    @ObservationIgnored private let recepteur = RecepteurSon()
    @ObservationIgnored private var boucle: Task<Void, Never>? = nil
    @ObservationIgnored private var abonnements: [UUID] = []
    @ObservationIgnored private var etatReseau: (EtatReseau, Date)? = nil
    /// Flux lancé depuis cet écran (pas de notification pour son `emit`).
    @ObservationIgnored private var envoiLocal: String? = nil
    @ObservationIgnored private var demandeTraitee = 0

    init(client: CcsClient, dire: @escaping (String) -> Void) {
        self.client = client
        self.dire = dire
        recepteur.surFin = { [weak self] raison in
            guard let s = self else { return }
            s.sonRecu = false
            if let e = s.ecoute {
                s.ecoute = nil
                s.dire("Son de \(e.de) arrêté : \(raison)")
            } else if s.resterALEcoute {
                s.dire("Écoute permanente coupée : \(raison) Nouvel essai à la prochaine annonce.")
            }
        }
        recepteur.surSon = { [weak self] recu in self?.sonRecu = recu }
    }

    // MARK: cycle

    /// Annonce tant que l'appli est connectée (première annonce dans les 2 s qui suivent la connexion).
    func demarrer() {
        guard boucle == nil else { return }
        abonnements.append(client.ecouter("audio") { [weak self] d in
            guard let s = self, let ev = EvenementSon.lire(d), ev.concerne(s.moi) else { return }
            s.traiter(ev)
        })
        abonnements.append(client.ecouterReconnexions { [weak self] in
            Task { await self?.annoncer() }
        })
        boucle = Task { @MainActor [weak self] in
            while !Task.isCancelled {
                guard let s = self else { return }
                var attente: Double = 2
                if s.client.etat.estConnecte {
                    await s.annoncer()
                    attente = Son.periodeAnnonce
                }
                try? await Task.sleep(nanoseconds: UInt64(attente * 1_000_000_000))
            }
        }
        appliquerEcoute()
    }

    /// Déconnexion volontaire : le pont oublie l'iPhone (`audio.forget`), tout s'arrête.
    func quitter() async {
        if client.etat.estConnecte, !moi.isEmpty {
            _ = try? await client.appeler("audio.forget", ["device": .chaine(moi)], delai: 2)
        }
        arreter()
    }

    func arreter() {
        boucle?.cancel()
        boucle = nil
        for a in abonnements { client.oublier(a) }
        abonnements = []
        arreterEcoute(tout: true)
        if GroupeSon.diffusionActive { GroupeSon.demanderArret() } else { GroupeSon.ecrireCible(nil) }
        cibleDiffusion = nil
        liste = ListeSon()
        annonceLe = nil
    }

    // MARK: annonce

    func annoncer() async {
        // écoute permanente tombée (port pris, son coupé par iOS) : on la rouvre
        if resterALEcoute && recepteur.ecoute == nil { appliquerEcoute(signaler: false) }
        let ip = SonPartage.adresseMaillee()
        self.ip = ip
        guard let ip = ip else {
            probleme = "Pas d'adresse 100.64.x : ouvre Tailscale et connecte-le au réseau maillé."
            return
        }
        // nom du pair qui porte cette adresse (`network.status`), relu toutes les 5 min
        if etatReseau == nil || Date().timeIntervalSince(etatReseau!.1) > 300 || moi.isEmpty {
            if let e = try? await client.appeler("network.status", delai: 15, en: EtatReseau.self) {
                etatReseau = (e, Date())
            }
        }
        let nom = Son.nomAppareil(ip: ip, etat: etatReseau?.0, modele: UIDevice.current.model)
        if !moi.isEmpty && nom != moi {
            _ = try? await client.appeler("audio.forget", ["device": .chaine(moi)], delai: 5)
        }
        moi = nom
        var params: [String: JSON] = [
            "device": .chaine(nom), "ip": .chaine(ip), "port": .nombre(Double(Rtp.portParDefaut)),
            "play": .booleen(true), "capture": .booleen(true), "system": .chaine("ios")]
        let label = UIDevice.current.name
        if !label.isEmpty && label != UIDevice.current.model { params["label"] = .chaine(label) }
        do {
            let r = try await client.appeler("audio.announce", params, delai: 10)
            annonceLe = Date()
            probleme = nil
            // flux qui joue déjà vers l'iPhone (reconnexion, appli relancée) : on se remet à écouter
            for f in r.liste("streams").map({ FluxSon(json: $0) }) where f.target == nom && ecoute?.flux != f.stream {
                ecouter(flux: f.stream, de: liste.nom(f.source), port: Rtp.portParDefaut)
            }
        } catch {
            probleme = texteErreur(error)
        }
    }

    /// Adresse 100.64.x des interfaces de l'iPhone (`utun*` : le tunnel de Tailscale).
    static func adresseMaillee() -> String? {
        var tete: UnsafeMutablePointer<ifaddrs>?
        guard getifaddrs(&tete) == 0, let premiere = tete else { return nil }
        defer { freeifaddrs(tete) }
        var trouvees: [(nom: String, ip: String)] = []
        var p: UnsafeMutablePointer<ifaddrs>? = premiere
        while let i = p {
            defer { p = i.pointee.ifa_next }
            guard let a = i.pointee.ifa_addr, a.pointee.sa_family == UInt8(AF_INET) else { continue }
            var hote = [CChar](repeating: 0, count: Int(NI_MAXHOST))
            if getnameinfo(a, socklen_t(a.pointee.sa_len), &hote, socklen_t(hote.count), nil, 0, NI_NUMERICHOST) == 0 {
                trouvees.append((String(cString: i.pointee.ifa_name), String(cString: hote)))
            }
        }
        return Son.adresseMaillee(trouvees)
    }

    // MARK: liste et commandes (écran Son)

    func rafraichir() async {
        do {
            liste = try await client.appeler("audio.list", delai: 10, en: ListeSon.self)
        } catch {
            dire(texteErreur(error))
        }
    }

    /// Envoie le son de `source` vers `cible` ; depuis cet iPhone, la diffusion ReplayKit suit.
    func envoyer(source: String, vers cible: AppareilSon) async {
        if source == moi { await envoyerDepuisIci(vers: cible); return }
        do {
            _ = try await client.appeler("audio.send", ["source": .chaine(source), "target": .chaine(cible.device)], delai: 10)
            dire("Son de \(liste.nom(source)) envoyé vers \(cible.nom).")
        } catch { dire(texteErreur(error)) }
        await rafraichir()
    }

    /// « Envoyer le son de cet iPhone vers… » : `audio.send`, cible passée à l'extension, puis le
    /// sélecteur de diffusion (l'utilisateur lance la diffusion, iOS l'exige).
    func envoyerDepuisIci(vers cible: AppareilSon) async {
        guard !moi.isEmpty else { dire(probleme ?? "iPhone pas encore annoncé."); return }
        guard GroupeSon.disponible else {
            dire("Groupe d'applis indisponible : réinstalle CCS par SideStore pour activer l'envoi du son.")
            return
        }
        do {
            let r = try await client.appeler("audio.send", ["source": .chaine(moi), "target": .chaine(cible.device)], delai: 10)
            let flux = r.texte("stream")
            envoiLocal = flux
            GroupeSon.ecrireCible(GroupeSon.Cible(ip: r.texte("ip").isEmpty ? cible.ip : r.texte("ip"),
                                                  port: r.entier("port", cible.port), nom: cible.nom, flux: flux))
            cibleDiffusion = cible.nom
            if !GroupeSon.diffusionActive { demandeDiffusion += 1 }
        } catch { dire(texteErreur(error)) }
        await rafraichir()
    }

    func arreter(flux: String) async {
        do {
            _ = try await client.appeler("audio.stop", ["stream": .chaine(flux)], delai: 10)
        } catch { dire(texteErreur(error)) }
        await rafraichir()
    }

    /// Arrête tout ce qui touche l'iPhone (écoute et diffusion).
    func arreterIci() async {
        if !moi.isEmpty { _ = try? await client.appeler("audio.stop", ["device": .chaine(moi)], delai: 10) }
        arreterEcoute()
        if GroupeSon.diffusionActive { GroupeSon.demanderArret() }
        cibleDiffusion = nil
        await rafraichir()
    }

    /// Toucher la notification « Touchez pour envoyer le son vers X » : sélecteur de diffusion.
    func demanderDiffusion() {
        demandeDiffusion += 1
    }

    /// Une demande de sélecteur pas encore montrée ? (lue une fois par l'écran Son)
    func prendreDemande() -> Bool {
        guard demandeDiffusion != demandeTraitee else { return false }
        demandeTraitee = demandeDiffusion
        return true
    }

    // MARK: événements

    private func traiter(_ ev: EvenementSon) {
        switch ev {
        case .recevoir(_, let flux, _, let deNom, let port):
            ecouter(flux: flux, de: deNom, port: port)
        case .emettre(_, let flux, _, let versNom, let ip, let port):
            GroupeSon.ecrireCible(GroupeSon.Cible(ip: ip, port: port, nom: versNom, flux: flux))
            cibleDiffusion = versNom
            // diffusion déjà lancée : l'extension change de cible d'elle-même ; envoi fait ici :
            // le sélecteur est déjà montré ; sinon (envoi lancé d'un autre appareil) : notification
            if !GroupeSon.diffusionActive && flux != envoiLocal {
                if UIApplication.shared.applicationState == .active {
                    dire("Lance la diffusion pour envoyer le son vers \(versNom).")
                    demandeDiffusion += 1
                } else {
                    SonPartage.notifierEmission(versNom)
                }
            }
        case .arret(let flux, _, _):
            if ecoute?.flux == flux { arreterEcoute() }
            if let c = GroupeSon.lireCible(), c.flux == flux {
                if GroupeSon.diffusionActive { GroupeSon.demanderArret() } else { GroupeSon.ecrireCible(nil) }
                cibleDiffusion = nil
            }
        }
        Task { await rafraichir() }
    }

    private func ecouter(flux: String, de: String, port: Int) {
        // déjà à l'écoute en permanence sur ce port : le son joue déjà, on le nomme seulement
        if let e = recepteur.ecoute, e.permanent, e.port == port {
            ecoute = (flux, de)
            return
        }
        do {
            try recepteur.demarrer(port: port, permanent: resterALEcoute && boucle != nil)
            ecoute = (flux, de)
        } catch {
            ecoute = nil
            dire("Impossible de jouer le son de \(de) : \(error.localizedDescription)")
        }
    }

    /// Arrête le son joué ; en écoute permanente le récepteur reste ouvert, sauf si `tout`.
    private func arreterEcoute(tout: Bool = false) {
        ecoute = nil
        if tout || !(recepteur.ecoute?.permanent ?? false) {
            recepteur.arreter()
            sonRecu = false
        }
    }

    /// Ouvre ou referme l'écoute permanente selon le réglage (seulement tant que l'appli annonce).
    /// Un échec est dit, sauf aux nouveaux essais (`signaler` faux : toutes les 30 s).
    private func appliquerEcoute(signaler: Bool = true) {
        let ouverte = recepteur.ecoute
        if resterALEcoute && boucle != nil {
            if let o = ouverte {
                if !o.permanent { recepteur.changerMode(permanent: true) }
                return
            }
            do {
                try recepteur.demarrer(port: Rtp.portParDefaut, permanent: true)
            } catch {
                if signaler { dire("Impossible de rester à l'écoute : \(error.localizedDescription)") }
            }
        } else if let o = ouverte, o.permanent {
            sonRecu = false
            if ecoute != nil { recepteur.changerMode(permanent: false) } else { recepteur.arreter() }
        }
    }

    static let idNotification = "son|emit"

    private static func notifierEmission(_ vers: String) {
        let n = UNMutableNotificationContent()
        n.title = "Son partagé"
        n.body = "Touchez pour envoyer le son vers \(vers)"
        n.sound = .default
        n.userInfo = ["son": "emit", "vers": vers]
        UNUserNotificationCenter.current().add(UNNotificationRequest(identifier: idNotification, content: n, trigger: nil))
    }
}
