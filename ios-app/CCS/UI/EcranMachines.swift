import SwiftUI
import UIKit

/**
 * Page « Machines » (Plus → Machines), comme celle du web (`pages-machines.js`) : machines du
 * relais Ricochet (charge, outils, places), travaux distants (en cours, à venir, finis) avec leur
 * journal et « Arrêter », formulaire « Lancer une commande », réglages du relais. Les `machines.*`
 * sont toujours traités par le serveur, même quand on pilote une autre machine.
 */
@MainActor
struct EcranMachines: View {
    @Environment(ModeleAppli.self) private var modele

    @State private var liste: ListeMachines? = nil
    @State private var erreurMachines: String? = nil
    @State private var travaux: [TravailDistant] = []
    @State private var erreurTravaux: String? = nil
    @State private var reglages: ReglagesRelais? = nil
    @State private var home = ""
    @State private var charge = false

    @State private var journal: TravailDistant? = nil
    @State private var aArreter: TravailDistant? = nil

    // formulaire « Lancer une commande »
    @State private var commande = ""
    @State private var dossier = ""
    @State private var cible = ""
    @State private var quand = ""
    @State private var heure = Date()
    @State private var erreurLancer: String? = nil
    @State private var lance = false

    // relais
    @State private var relais = ""
    @State private var jeton = ""
    @State private var erreurRelais: String? = nil

    private var client: CcsClient { return modele.client }

    var body: some View {
        List {
            sectionMachines
            sectionTravaux
            sectionLancer
            sectionRelais
        }
        .navigationTitle("Machines")
        .refreshable { await rafraichir() }
        .task(id: client.etat.estConnecte) {
            guard client.etat.estConnecte else { return }
            if home.isEmpty, let e = try? await client.appeler("accounts.state", en: EtatComptes.self) { home = e.home }
            await lireReglages()
            // rafraîchi toutes les 5 s tant que la page est affichée
            while !Task.isCancelled {
                await rafraichir()
                try? await Task.sleep(nanoseconds: 5_000_000_000)
            }
        }
        .sheet(item: $journal) { j in
            FeuilleJournal(travail: j, home: home).environment(modele)
        }
        .confirmationDialog("Arrêter ce travail ?", isPresented: Binding(get: { aArreter != nil }, set: { if !$0 { aArreter = nil } }),
                            titleVisibility: .visible, presenting: aArreter) { j in
            Button("Arrêter", role: .destructive) { Task { await arreter(j) } }
            Button("Garder", role: .cancel) {}
        } message: { j in
            Text(texteArret(j))
        }
    }

    // MARK: sections

    @ViewBuilder
    private var sectionMachines: some View {
        Section("Machines") {
            if let e = erreurMachines {
                Text(e).font(.footnote).foregroundStyle(.red)
            } else if let l = liste {
                if let m = l.message, !m.isEmpty {
                    Text(m).font(.footnote).foregroundStyle(l.configured ? Color.red : Color.secondary)
                } else if !l.configured {
                    Text("Relais Ricochet non configuré : remplis ses réglages plus bas.").font(.footnote).foregroundStyle(.secondary)
                }
                if l.machines.isEmpty && l.configured {
                    Text("Aucune machine sur le relais.").foregroundStyle(.secondary)
                }
                ForEach(l.machines) { m in carteMachine(m) }
            } else {
                HStack {
                    ProgressView()
                    Text("Chargement…").foregroundStyle(.secondary)
                }
            }
        }
    }

    private func carteMachine(_ m: Machine) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Image(systemName: m.local ? "cloud" : "desktopcomputer")
                Text(m.nom).font(.headline)
                if m.local { Text("ce serveur").font(.caption).foregroundStyle(.secondary) }
                Spacer()
                Circle().fill(m.online ? Color.green : Color.gray).frame(width: 8, height: 8)
            }
            Text(m.description).font(.footnote).foregroundStyle(.secondary)
            Text(m.tools.isEmpty ? "outils pas encore inventoriés" : m.tools.joined(separator: " · "))
                .font(.caption).foregroundStyle(.secondary)
            HStack {
                Text(m.places).font(.footnote)
                Spacer()
                Picker("Limite", selection: Binding(get: { m.limit }, set: { n in
                    Task { await changerLimite(m, n) }
                })) {
                    ForEach(Travaux.limites, id: \.self) { n in Text("\(n)").tag(n) }
                }
                .pickerStyle(.menu)
                .accessibilityLabel("Limite de travaux sur \(m.nom)")
            }
        }
        .padding(.vertical, 2)
    }

    @ViewBuilder
    private var sectionTravaux: some View {
        let actifs = travaux.filter { Travaux.actif($0) }
        let finis = travaux.filter { !Travaux.actif($0) }
        Section("En cours et à venir (\(actifs.count))") {
            if let e = erreurTravaux {
                Text(e).font(.footnote).foregroundStyle(.red)
            } else if actifs.isEmpty {
                Text(charge ? "Rien en cours." : "Chargement…").foregroundStyle(.secondary)
            }
            ForEach(actifs) { j in ligneTravail(j) }
        }
        if !finis.isEmpty {
            Section("Finis (\(finis.count))") {
                ForEach(finis) { j in ligneTravail(j) }
            }
        }
    }

    private func ligneTravail(_ j: TravailDistant) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(alignment: .firstTextBaseline) {
                Text(j.text).font(.system(.subheadline, design: .monospaced)).lineLimit(2)
                Spacer()
                PastilleEtat(travail: j)
            }
            Text(Travaux.ligne(j, home: home)).font(.caption).foregroundStyle(.secondary)
            if !j.why.isEmpty { Text(j.why).font(.caption).foregroundStyle(.orange) }
            HStack(spacing: 16) {
                Button("Journal") { journal = j }
                if Travaux.actif(j) {
                    Button("Arrêter", role: .destructive) { aArreter = j }
                }
            }
            .buttonStyle(.borderless)
            .font(.subheadline)
        }
        .padding(.vertical, 2)
    }

    @ViewBuilder
    private var sectionLancer: some View {
        Section {
            TextField("flutter build apk", text: $commande)
                .font(.system(.body, design: .monospaced))
                .textInputAutocapitalization(.never).autocorrectionDisabled()
            TextField("Dossier (~/Work/mon-projet)", text: $dossier)
                .textInputAutocapitalization(.never).autocorrectionDisabled()
            Picker("Machine", selection: $cible) {
                Text("La moins chargée").tag("")
                ForEach((liste?.machines ?? []).filter { !$0.local || $0.online }) { m in
                    Text(nomCible(m)).tag(m.id)
                }
            }
            Picker("Quand", selection: $quand) {
                Text("Maintenant").tag("")
                Text("Cette nuit").tag("nuit")
                Text("À une heure…").tag("heure")
            }
            if quand == "heure" {
                DatePicker("Heure", selection: $heure, displayedComponents: .hourAndMinute)
            }
            if let e = erreurLancer { Text(e).font(.footnote).foregroundStyle(.red) }
            Button(lance ? "Envoi…" : "Lancer") { Task { await lancer() } }
                .disabled(lance)
        } header: {
            Text("Lancer une commande")
        } footer: {
            Text("Une ligne de shell, lancée dans le dossier (dans le dossier personnel du serveur), envoyée à la machine choisie.")
        }
    }

    @ViewBuilder
    private var sectionRelais: some View {
        Section {
            TextField("https://ricochet.exemple", text: $relais)
                .keyboardType(.URL).textInputAutocapitalization(.never).autocorrectionDisabled()
            SecureField(reglages?.jetonDefini == true ? "Jeton (laisser vide pour le garder)" : "Jeton du relais", text: $jeton)
            if let e = erreurRelais { Text(e).font(.footnote).foregroundStyle(.red) }
            Button("Enregistrer") { Task { await enregistrerRelais() } }
                .disabled(reglages == nil)
        } header: {
            Text("Relais Ricochet")
        } footer: {
            if let r = reglages {
                Text(piedRelais(r))
            }
        }
    }

    private func nomCible(_ m: Machine) -> String {
        return m.online ? m.nom : m.nom + " (hors ligne)"
    }

    private func piedRelais(_ r: ReglagesRelais) -> String {
        let j: String = r.jetonDefini ? "Jeton enregistré." : "Aucun jeton."
        let f: String = Format.court(r.chemin, home: home)
        return "\(j) Fichier : \(f) · limite par défaut : \(r.limiteDefaut) travaux à la fois par machine."
    }

    private func texteArret(_ j: TravailDistant) -> String {
        if Travaux.enCours(j) { return "« \(j.text) » sera arrêtée sur \(j.machine ?? "la machine")." }
        return "« \(j.text) » ne sera pas lancée."
    }

    // MARK: actions

    private func rafraichir() async {
        do {
            let l = try await client.appeler("machines.list", delai: 15, en: ListeMachines.self)
            liste = l
            erreurMachines = nil
        } catch {
            if liste == nil { erreurMachines = texteErreur(error) }
        }
        do {
            travaux = try await client.appeler("machines.jobs", delai: 15, en: ListeTravaux.self).jobs
            erreurTravaux = nil
        } catch {
            if travaux.isEmpty { erreurTravaux = texteErreur(error) }
        }
        charge = true
    }

    private func lireReglages() async {
        guard let r = try? await client.appeler("machines.settings", en: ReglagesRelais.self) else { return }
        reglages = r
        if relais.isEmpty { relais = r.relais }
    }

    private func changerLimite(_ m: Machine, _ n: Int) async {
        if n == m.limit { return }
        do {
            _ = try await client.appeler("machines.limit", ["machine": .chaine(m.id), "limite": .nombre(Double(n))])
            await rafraichir()
        } catch {
            modele.avis.dire(texteErreur(error))
        }
    }

    private func arreter(_ j: TravailDistant) async {
        do {
            _ = try await client.appeler("machines.stop", ["id": .chaine(j.id)])
            modele.avis.dire("Travail arrêté.")
        } catch {
            modele.avis.dire(texteErreur(error))
        }
        await rafraichir()
    }

    private func lancer() async {
        erreurLancer = nil
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "HH:mm"
        let d = Travaux.demande(commande: commande, dossier: dossier, home: home, machine: cible, quand: quand, heure: f.string(from: heure))
        guard let p = d.params else {
            erreurLancer = d.erreur
            return
        }
        lance = true
        defer { lance = false }
        do {
            _ = try await client.appeler("machines.start", p, delai: 30)
            commande = ""
            modele.avis.dire(quand.isEmpty ? "Commande lancée." : "Commande programmée.")
            await rafraichir()
        } catch {
            erreurLancer = texteErreur(error)
        }
    }

    private func enregistrerRelais() async {
        erreurRelais = nil
        var p: [String: JSON] = [:]
        let r = relais.trimmingCharacters(in: .whitespaces)
        if r != (reglages?.relais ?? "") { p["relais"] = .chaine(r) }
        if !jeton.isEmpty { p["jeton"] = .chaine(jeton) }
        if p.isEmpty {
            erreurRelais = "Rien à enregistrer."
            return
        }
        do {
            _ = try await client.appeler("machines.configure", p)
            jeton = ""
            modele.avis.dire("Réglages du relais enregistrés.")
            await lireReglages()
            await rafraichir()
        } catch {
            erreurRelais = texteErreur(error)
        }
    }
}

/// Pastille d'état d'un travail (attente, en cours, fini, échec…).
@MainActor
private struct PastilleEtat: View {
    let travail: TravailDistant

    var body: some View {
        let c: Color = {
            switch Travaux.teinte(travail) {
            case .attente: return .orange
            case .enCours: return .blue
            case .fini: return .green
            case .echec: return .red
            case .neutre: return .gray
            }
        }()
        Text(travail.state)
            .font(.caption.weight(.semibold))
            .padding(.horizontal, 8)
            .padding(.vertical, 2)
            .background(Capsule().fill(c.opacity(0.18)))
            .foregroundStyle(c)
    }
}

/// Journal d'un travail (`machines.log`), relu toutes les 3 s tant qu'il est ouvert.
@MainActor
private struct FeuilleJournal: View {
    @Environment(ModeleAppli.self) private var modele
    @Environment(\.dismiss) private var fermer
    let travail: TravailDistant
    let home: String
    @State private var texte = "Chargement…"
    @State private var etat: TravailDistant? = nil

    var body: some View {
        NavigationStack {
            ScrollViewReader { proxy in
                ScrollView([.vertical, .horizontal]) {
                    VStack(alignment: .leading, spacing: 8) {
                        Text(travail.text).font(.system(.subheadline, design: .monospaced).weight(.semibold))
                        let t = etat ?? travail
                        Text("\(t.state) · \(Travaux.ligne(t, home: home))").font(.caption).foregroundStyle(.secondary)
                        Text(texte)
                            .font(.system(size: 11, design: .monospaced))
                            .textSelection(.enabled)
                            .fixedSize(horizontal: true, vertical: false)
                        Color.clear.frame(height: 1).id("fin")
                    }
                    .padding()
                }
                .onChange(of: texte) { _, _ in proxy.scrollTo("fin", anchor: .bottom) }
            }
            .navigationTitle("Journal")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Fermer") { fermer() } }
                ToolbarItem(placement: .primaryAction) {
                    Button { UIPasteboard.general.string = texte } label: { Label("Copier", systemImage: "doc.on.doc") }
                }
            }
            .task {
                while !Task.isCancelled {
                    await lire()
                    try? await Task.sleep(nanoseconds: 3_000_000_000)
                }
            }
        }
    }

    private func lire() async {
        do {
            let r = try await modele.client.appeler("machines.log", ["id": .chaine(travail.id), "tail": .nombre(20000)], delai: 15)
            let t = r.texte("text")
            let nouveau = t.isEmpty ? "Pas encore de journal." : t
            if nouveau != texte { texte = nouveau }
        } catch {
            texte = texteErreur(error)
        }
        if let l = try? await modele.client.appeler("machines.jobs", delai: 15, en: ListeTravaux.self),
           let j = l.jobs.first(where: { $0.id == travail.id }) {
            etat = j
        }
    }
}
