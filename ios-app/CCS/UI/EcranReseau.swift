import SwiftUI

/**
 * Onglet « Réseau », comme celui du web (`reseau.js`) et d'Android : le réseau maillé de tous les
 * appareils (Headscale sur network.mawena.cloud). Carte du réseau, fiche de chaque appareil
 * (adresses publiées, trafic, ping réel, renommer, retirer), ajout d'un appareil. Méthodes
 * `network.*`, toujours traitées par le serveur. Rechargé toutes les 10 s tant qu'il est affiché.
 */
@MainActor
struct EcranReseau: View {
    @Environment(ModeleAppli.self) private var modele

    @State private var etat: EtatReseau? = nil
    @State private var erreur: String? = nil
    @State private var pings: [String: PingReseau] = [:]
    @State private var aRenommer: Appareil? = nil
    @State private var nouveauNom = ""
    @State private var aRetirer: Appareil? = nil

    private var client: CcsClient { return modele.client }

    var body: some View {
        ScrollView {
            VStack(spacing: 14) {
                EnteteReseau(etat: etat, erreur: erreur)
                if let e = etat {
                    if e.ici != nil || !e.peers.isEmpty { CarteReseau(etat: e) }
                    HStack(spacing: 8) {
                        Image(systemName: "point.3.connected.trianglepath.dotted")
                        Text("Appareils").font(.title2.bold())
                        Spacer()
                    }
                    .padding(.top, 4)
                    ForEach(Reseau.appareils(e), id: \.0.name) { paire in
                        FicheAppareil(
                            appareil: paire.0, ici: paire.1, etat: e, ping: pings[paire.0.name],
                            lancerPing: { Task { await ping(paire.0) } },
                            renommer: { nouveauNom = paire.0.name; aRenommer = paire.0 },
                            retirer: { aRetirer = paire.0 })
                    }
                    if e.server {
                        AjoutAppareil(etat: e, creerCle: creerCle, valider: valider)
                    }
                } else if erreur == nil {
                    ProgressView().padding()
                }
            }
            .padding(14)
        }
        .background(Color(.systemGroupedBackground))
        .navigationTitle("Réseau")
        .navigationBarTitleDisplayMode(.inline)
        .refreshable { await recharger() }
        .task(id: client.etat.estConnecte) {
            guard client.etat.estConnecte else { return }
            while !Task.isCancelled {
                await recharger()
                try? await Task.sleep(nanoseconds: 10_000_000_000)
            }
        }
        .alert("Renommer \(aRenommer?.name ?? "")", isPresented: Binding(get: { aRenommer != nil }, set: { if !$0 { aRenommer = nil } })) {
            TextField("Nouveau nom", text: $nouveauNom)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
            Button("Renommer") {
                if let a = aRenommer { Task { await renommer(a, nouveauNom.trimmingCharacters(in: .whitespaces).lowercased()) } }
            }
            Button("Annuler", role: .cancel) {}
        } message: {
            Text("Lettres minuscules, chiffres et tirets.")
        }
        .confirmationDialog("Retirer \(aRetirer?.name ?? "") du réseau ?",
                            isPresented: Binding(get: { aRetirer != nil }, set: { if !$0 { aRetirer = nil } }),
                            titleVisibility: .visible, presenting: aRetirer) { a in
            Button("Retirer", role: .destructive) { Task { await retirer(a) } }
            Button("Garder", role: .cancel) {}
        } message: { _ in
            Text("L'appareil perd l'accès au réseau. Il faudra l'inscrire à nouveau.")
        }
    }

    // MARK: actions

    private func recharger() async {
        do {
            etat = try await client.appeler("network.status", en: EtatReseau.self)
            erreur = nil
        } catch {
            erreur = texteErreur(error)
        }
    }

    private func ping(_ a: Appareil) async {
        do {
            pings[a.name] = try await client.appeler("network.ping", ["name": .chaine(a.name)], delai: 40, en: PingReseau.self)
        } catch {
            pings[a.name] = PingReseau(erreur: texteErreur(error))
        }
    }

    private func renommer(_ a: Appareil, _ nom: String) async {
        guard Reseau.nomValide(nom) else { modele.avis.dire("Nom invalide : lettres minuscules, chiffres et tirets."); return }
        guard nom != a.name else { return }
        do {
            _ = try await client.appeler("network.rename", ["name": .chaine(a.name), "new": .chaine(nom)])
            modele.avis.dire("Renommé.")
            await recharger()
        } catch { modele.avis.dire(texteErreur(error)) }
    }

    private func retirer(_ a: Appareil) async {
        do {
            _ = try await client.appeler("network.remove", ["name": .chaine(a.name)])
            modele.avis.dire("Retiré.")
            await recharger()
        } catch { modele.avis.dire(texteErreur(error)) }
    }

    private func creerCle(_ nom: String) async -> CleReseau? {
        do {
            return try await client.appeler("network.key", nom.isEmpty ? [:] : ["name": .chaine(nom)], en: CleReseau.self)
        } catch {
            modele.avis.dire(texteErreur(error))
            return nil
        }
    }

    private func valider(_ cle: String) async -> Bool {
        do {
            let r = try await client.appeler("network.register", ["key": .chaine(cle)])
            modele.avis.dire("\(r.texte("name")) ajouté au réseau.")
            await recharger()
            return true
        } catch {
            modele.avis.dire(texteErreur(error))
            return false
        }
    }
}

// MARK: couleurs (les mêmes que le web)

extension Reseau.Chemin {
    var couleur: Color {
        switch self {
        case .lan: return Color(red: 0.18, green: 0.76, blue: 0.49)
        case .direct: return Color(red: 0.21, green: 0.52, blue: 0.89)
        case .relais: return Color(red: 0.90, green: 0.65, blue: 0.04)
        case .ici: return Color(red: 0.57, green: 0.25, blue: 0.67)
        case .veille, .horsLigne: return Color(red: 0.60, green: 0.60, blue: 0.64)
        }
    }
}

extension Reseau.SorteAdresse {
    var couleur: Color {
        switch self {
        case .locale: return Reseau.Chemin.lan.couleur
        case .publique: return Reseau.Chemin.direct.couleur
        case .v6, .maille: return Reseau.Chemin.ici.couleur
        }
    }
}

// MARK: en-tête

@MainActor
private struct EnteteReseau: View {
    let etat: EtatReseau?
    let erreur: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(spacing: 12) {
                Image(systemName: "globe")
                    .font(.system(size: 28, weight: .medium))
                    .frame(width: 52, height: 52)
                    .background(.white.opacity(0.16), in: RoundedRectangle(cornerRadius: 15))
                VStack(alignment: .leading, spacing: 2) {
                    Text("Réseau").font(.title.bold())
                    Text((etat?.url ?? "network.mawena.cloud").replacingOccurrences(of: "https://", with: ""))
                        .font(.footnote).opacity(0.85)
                }
                Spacer()
                HStack(spacing: 6) {
                    Circle().fill(connecte ? Color(red: 0.34, green: 0.89, blue: 0.54) : Color(red: 1, green: 0.48, blue: 0.48))
                        .frame(width: 8, height: 8)
                    Text(texteEtat).font(.footnote.weight(.semibold))
                }
                .padding(.horizontal, 10).padding(.vertical, 5)
                .background(.black.opacity(0.22), in: Capsule())
            }
            if let e = etat {
                let b = Reseau.bilan(e)
                HStack(spacing: 8) {
                    chiffre("point.3.connected.trianglepath.dotted", "\(b.enLigne)/\(b.total)", "en ligne")
                    chiffre("house.fill", "\(b.lan)", "en local")
                    chiffre("bolt.fill", "\(b.direct)", "en direct")
                    chiffre("arrow.triangle.swap", "\(b.relais)", "relais")
                }
            }
            if let m = erreur ?? etat?.error {
                Text(m).font(.footnote).padding(10).frame(maxWidth: .infinity, alignment: .leading)
                    .background(.black.opacity(0.25), in: RoundedRectangle(cornerRadius: 10))
            }
        }
        .foregroundStyle(.white)
        .padding(16)
        .background(
            LinearGradient(colors: [Color(red: 0.11, green: 0.44, blue: 0.85), Color(red: 0.38, green: 0.21, blue: 0.51),
                                    Color(red: 0.15, green: 0.64, blue: 0.41)],
                           startPoint: .topLeading, endPoint: .bottomTrailing),
            in: RoundedRectangle(cornerRadius: 20))
        .shadow(color: Color(red: 0.21, green: 0.52, blue: 0.89).opacity(0.25), radius: 14, y: 6)
    }

    private var connecte: Bool { return etat?.state == "Running" }

    private var texteEtat: String {
        guard let e = etat else { return "…" }
        if !e.installed { return "Hors réseau" }
        return connecte ? "Connecté" : (e.state.isEmpty ? "Arrêté" : e.state)
    }

    private func chiffre(_ icone: String, _ valeur: String, _ libelle: String) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Image(systemName: icone).font(.footnote)
            Text(valeur).font(.title3.bold())
            Text(libelle).font(.caption2).opacity(0.85).lineLimit(1)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(10)
        .background(.white.opacity(0.13), in: RoundedRectangle(cornerRadius: 12))
    }
}

// MARK: carte

@MainActor
private struct CarteReseau: View {
    let etat: EtatReseau

    var body: some View {
        VStack(spacing: 8) {
            GeometryReader { g in
                let l = g.size.width
                let h = g.size.height
                let centre = CGPoint(x: l / 2, y: h / 2 - 8)
                let n = max(etat.peers.count, 1)
                let rx = max(l / 2 - 50, 60)
                let ry = h / 2 - 44
                let points: [(Appareil, CGPoint)] = etat.peers.enumerated().map { i, a in
                    let ang = -Double.pi / 2 + 2 * Double.pi * Double(i) / Double(n)
                    return (a, CGPoint(x: centre.x + rx * cos(ang), y: centre.y + ry * sin(ang)))
                }
                ZStack {
                    ForEach(points, id: \.0.name) { paire in
                        let c = Reseau.Chemin.de(paire.0.path)
                        Path { path in path.move(to: centre); path.addLine(to: paire.1) }
                            .stroke(c.couleur.opacity(c == .veille || c == .horsLigne ? 0.5 : 0.9),
                                    style: StrokeStyle(lineWidth: 3, lineCap: .round,
                                                       dash: c == .relais ? [9, 6] : (c == .lan || c == .direct ? [] : [2, 7])))
                    }
                    ForEach(points, id: \.0.name) { paire in noeud(paire.0, principal: false).position(paire.1) }
                    if let i = etat.ici { noeud(i, principal: true).position(centre) }
                }
            }
            .frame(height: 250)
            HStack(spacing: 12) {
                ForEach([Reseau.Chemin.lan, .direct, .relais, .horsLigne], id: \.self) { c in
                    HStack(spacing: 5) {
                        RoundedRectangle(cornerRadius: 2).fill(c.couleur).frame(width: 16, height: 3)
                        Text(c.libelle).font(.caption2).foregroundStyle(.secondary)
                    }
                }
            }
        }
        .padding(12)
        .background(Color(.secondarySystemGroupedBackground), in: RoundedRectangle(cornerRadius: 16))
    }

    private func noeud(_ a: Appareil, principal: Bool) -> some View {
        let taille: CGFloat = principal ? 56 : 42
        return VStack(spacing: 3) {
            Image(systemName: Reseau.icone(a))
                .font(.system(size: principal ? 24 : 18))
                .foregroundStyle(principal ? Color.white : Color.primary)
                .frame(width: taille, height: taille)
                .background(principal ? Reseau.Chemin.ici.couleur : Color(.systemBackground), in: Circle())
                .overlay(Circle().stroke(Color(.separator), lineWidth: principal ? 0 : 1))
                .shadow(color: .black.opacity(0.12), radius: 3, y: 2)
            Text(a.name).font(.caption.weight(.semibold)).lineLimit(1).frame(width: 100)
        }
        .opacity(a.online || principal ? 1 : 0.45)
    }
}

// MARK: fiche d'un appareil

@MainActor
private struct FicheAppareil: View {
    let appareil: Appareil
    let ici: Bool
    let etat: EtatReseau
    let ping: PingReseau?
    let lancerPing: () -> Void
    let renommer: () -> Void
    let retirer: () -> Void
    @Environment(ModeleAppli.self) private var modele

    var body: some View {
        let a = appareil
        let c = Reseau.Chemin.de(a.path)
        HStack(spacing: 0) {
            Rectangle().fill(c.couleur).frame(width: 4)
            VStack(alignment: .leading, spacing: 8) {
                HStack(spacing: 12) {
                    Image(systemName: Reseau.icone(a))
                        .font(.system(size: 20))
                        .foregroundStyle(.white)
                        .frame(width: 44, height: 44)
                        .background(LinearGradient(colors: [c.couleur.opacity(0.85), c.couleur], startPoint: .topLeading, endPoint: .bottomTrailing),
                                    in: RoundedRectangle(cornerRadius: 13))
                    VStack(alignment: .leading, spacing: 3) {
                        Text(a.name).font(.headline).lineLimit(1)
                        HStack(spacing: 6) {
                            Label(c.libelle, systemImage: c.icone)
                                .font(.caption.weight(.semibold))
                                .foregroundStyle(c.couleur)
                                .padding(.horizontal, 8).padding(.vertical, 3)
                                .background(c.couleur.opacity(0.15), in: Capsule())
                            if !a.os.isEmpty { Text(a.os).font(.caption).foregroundStyle(.secondary) }
                        }
                    }
                    Spacer(minLength: 0)
                }
                let ip = a.ips.first ?? ""
                HStack(spacing: 6) {
                    Text(ip.isEmpty ? "—" : ip).font(.body.monospaced().weight(.semibold))
                    if !ip.isEmpty {
                        Button { copier(ip); modele.avis.dire("Copié.") } label: { Image(systemName: "doc.on.doc") }
                            .buttonStyle(.borderless).font(.footnote)
                    }
                }
                Text("\(a.name).\(etat.domain)").font(.caption.monospaced()).foregroundStyle(.secondary)
                if !a.endpoint.isEmpty && !ici {
                    Label(a.endpoint, systemImage: "arrow.left.arrow.right").font(.caption).foregroundStyle(.secondary)
                }
                let adresses = Reseau.adressesPubliees(a)
                if !adresses.isEmpty {
                    FlowLayout(espacement: 6) {
                        ForEach(adresses, id: \.ip) { ad in
                            HStack(spacing: 4) {
                                Text(ad.sorte.rawValue).font(.system(size: 10, weight: .bold)).foregroundStyle(.white)
                                    .padding(.horizontal, 5).padding(.vertical, 1)
                                    .background(ad.sorte.couleur, in: RoundedRectangle(cornerRadius: 6))
                                Text(ad.ip).font(.caption2.monospaced())
                            }
                            .padding(2).padding(.trailing, 6)
                            .background(Color(.tertiarySystemFill), in: RoundedRectangle(cornerRadius: 8))
                        }
                    }
                }
                if a.rx > 0 || a.tx > 0 {
                    Text("↓ \(Reseau.octets(a.rx)) · ↑ \(Reseau.octets(a.tx))").font(.caption).foregroundStyle(.secondary)
                }
                if let p = ping {
                    let cp = p.ok ? Reseau.Chemin.de(p.path).couleur : Color.red
                    HStack(spacing: 6) {
                        Image(systemName: "waveform.path.ecg").foregroundStyle(cp)
                        Text(p.ok ? "\(Int(p.ms.rounded())) ms · \(Reseau.Chemin.de(p.path).libelle) · \(p.via)" : (p.error ?? "pas de réponse"))
                            .font(.caption)
                    }
                    .padding(.horizontal, 10).padding(.vertical, 6)
                    .background(Color(.tertiarySystemFill), in: RoundedRectangle(cornerRadius: 10))
                }
                HStack(spacing: 14) {
                    if !ici && a.online { Button(action: lancerPing) { Label("Ping", systemImage: "waveform.path.ecg") } }
                    if etat.server {
                        Button(action: renommer) { Label("Renommer", systemImage: "pencil") }
                        if !ici { Button(role: .destructive, action: retirer) { Label("Retirer", systemImage: "trash") } }
                    }
                }
                .font(.subheadline.weight(.semibold))
                .buttonStyle(.borderless)
                .padding(.top, 2)
            }
            .padding(14)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .background(Color(.secondarySystemGroupedBackground))
        .clipShape(RoundedRectangle(cornerRadius: 16))
        .opacity(a.online || ici ? 1 : 0.7)
    }
}

/// Étiquettes qui passent à la ligne (adresses publiées).
private struct FlowLayout: Layout {
    var espacement: CGFloat = 6

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let largeur = proposal.width ?? .infinity
        var x: CGFloat = 0, y: CGFloat = 0, ligne: CGFloat = 0, maxX: CGFloat = 0
        for s in subviews {
            let t = s.sizeThatFits(.unspecified)
            if x > 0 && x + t.width > largeur { x = 0; y += ligne + espacement; ligne = 0 }
            x += t.width + espacement
            ligne = max(ligne, t.height)
            maxX = max(maxX, x)
        }
        return CGSize(width: min(maxX, largeur), height: y + ligne)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        var x = bounds.minX, y = bounds.minY, ligne: CGFloat = 0
        for s in subviews {
            let t = s.sizeThatFits(.unspecified)
            if x > bounds.minX && x + t.width > bounds.maxX { x = bounds.minX; y += ligne + espacement; ligne = 0 }
            s.place(at: CGPoint(x: x, y: y), proposal: ProposedViewSize(t))
            x += t.width + espacement
            ligne = max(ligne, t.height)
        }
    }
}

// MARK: ajout d'un appareil

@MainActor
private struct AjoutAppareil: View {
    let etat: EtatReseau
    let creerCle: (String) async -> CleReseau?
    let valider: (String) async -> Bool
    @Environment(ModeleAppli.self) private var modele

    @State private var onglet = 0
    @State private var nom = ""
    @State private var ligne: String? = nil
    @State private var cle = ""
    @State private var occupe = false

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Label("Ajouter un appareil", systemImage: "plus.circle.fill").font(.headline)
            Picker("Appareil", selection: $onglet) {
                Text("PC Linux").tag(0)
                Text("Android").tag(1)
                Text("iPhone").tag(2)
            }
            .pickerStyle(.segmented)
            if onglet == 0 {
                etapes(["Choisis un nom pour la machine, puis crée la ligne.",
                        "Colle-la dans un terminal du PC : elle installe le client et l'inscrit.",
                        "Il apparaît ici en quelques secondes."])
                TextField("Nom (facultatif) : laptop-maison", text: $nom)
                    .textInputAutocapitalization(.never).autocorrectionDisabled()
                    .textFieldStyle(.roundedBorder)
                Button {
                    let n = nom.trimmingCharacters(in: .whitespaces).lowercased()
                    guard n.isEmpty || Reseau.nomValide(n) else { modele.avis.dire("Nom : lettres minuscules, chiffres et tirets."); return }
                    occupe = true
                    Task {
                        if let c = await creerCle(n) { ligne = Reseau.ligneLinux(c.linux) }
                        occupe = false
                    }
                } label: { Label("Créer la ligne d'inscription", systemImage: "key.fill") }
                    .buttonStyle(.borderedProminent).disabled(occupe)
                if let l = ligne {
                    Text("Clé valable 15 min, pour une seule machine :").font(.caption).foregroundStyle(.secondary)
                    HStack(alignment: .top) {
                        Text(l).font(.caption2.monospaced()).foregroundStyle(Color(white: 0.9)).textSelection(.enabled)
                        Spacer(minLength: 4)
                        Button { copier(l); modele.avis.dire("Copié.") } label: { Image(systemName: "doc.on.doc") }
                            .foregroundStyle(Color(white: 0.9))
                    }
                    .padding(10)
                    .background(Color(white: 0.12), in: RoundedRectangle(cornerRadius: 10))
                }
            } else {
                let iphone = onglet == 2
                etapes(["Installe l'appli Tailscale (\(iphone ? "App Store" : "Play Store")).",
                        iphone ? "Réglages de l'appli → Comptes → « Utiliser un serveur personnalisé » :"
                               : "Écran de connexion → menu ⋮ → « Changer de serveur » :",
                        "Connecte-toi : une page affiche une clé « hskey-authreq-… ». Colle-la ici."])
                Button { copier(etat.url); modele.avis.dire("Adresse du serveur copiée.") } label: {
                    Label(etat.url, systemImage: "doc.on.doc").font(.footnote.monospaced())
                }
                if iphone, let u = URL(string: "https://apps.apple.com/app/tailscale/id1470499037") {
                    Link(destination: u) { Label("Ouvrir Tailscale dans l'App Store", systemImage: "arrow.down.app") }.font(.footnote)
                }
                TextField("Clé ou lien affiché", text: $cle)
                    .textInputAutocapitalization(.never).autocorrectionDisabled()
                    .textFieldStyle(.roundedBorder)
                Button {
                    occupe = true
                    Task {
                        if await valider(cle.trimmingCharacters(in: .whitespaces)) { cle = "" }
                        occupe = false
                    }
                } label: { Label("Valider l'appareil", systemImage: "checkmark.circle.fill") }
                    .buttonStyle(.borderedProminent).disabled(occupe || cle.count < 8)
            }
        }
        .padding(14)
        .background(Color(.secondarySystemGroupedBackground), in: RoundedRectangle(cornerRadius: 16))
    }

    private func etapes(_ lignes: [String]) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            ForEach(Array(lignes.enumerated()), id: \.offset) { e in
                HStack(alignment: .top, spacing: 10) {
                    Text("\(e.offset + 1)").font(.caption.bold()).foregroundStyle(.white)
                        .frame(width: 24, height: 24).background(Color.accentColor, in: Circle())
                    Text(e.element).font(.subheadline)
                }
            }
        }
    }
}
