import SwiftUI
import UIKit

/**
 * Calcul réparti, affiché dans l'onglet Réseau comme sur le web (`calcul.js`) : le bloc « calcul »
 * de chaque fiche (charge, mémoire, outils, places, limite), les travaux distants (en cours, à
 * venir, finis) avec leur journal et « Arrêter », « Lancer une commande », l'ajout d'un PC par un
 * lien Ricochet et le secours Ricochet (réglages du relais). Les `machines.*` sont toujours traités
 * par le serveur, même quand on pilote une autre machine.
 */
@MainActor
@Observable
final class Calcul {
    var liste: ListeMachines? = nil
    var erreurMachines: String? = nil
    var travaux: [TravailDistant] = []
    var erreurTravaux: String? = nil
    var reglages: ReglagesRelais? = nil
    var home = ""
    var charge = false

    var machines: [Machine] { return liste?.machines ?? [] }

    /// Dossier personnel du serveur et réglages du relais, lus une fois.
    func preparer(_ client: CcsClient) async {
        if home.isEmpty, let e = try? await client.appeler("accounts.state", en: EtatComptes.self) { home = e.home }
        await lireReglages(client)
    }

    func rafraichir(_ client: CcsClient) async {
        do {
            liste = try await client.appeler("machines.list", delai: 15, en: ListeMachines.self)
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

    func lireReglages(_ client: CcsClient) async {
        guard let r = try? await client.appeler("machines.settings", en: ReglagesRelais.self) else { return }
        reglages = r
    }

    func changerLimite(_ m: Machine, _ n: Int, _ modele: ModeleAppli) async {
        if n == m.limit { return }
        do {
            _ = try await modele.client.appeler("machines.limit", ["machine": .chaine(m.id), "limit": .nombre(Double(n))])
            modele.avis.dire("Limite enregistrée.")
            await rafraichir(modele.client)
        } catch {
            modele.avis.dire(texteErreur(error))
        }
    }

    func arreter(_ j: TravailDistant, _ modele: ModeleAppli) async {
        do {
            _ = try await modele.client.appeler("machines.stop", ["id": .chaine(j.id)])
            modele.avis.dire("Travail arrêté.")
        } catch {
            modele.avis.dire(texteErreur(error))
        }
        await rafraichir(modele.client)
    }
}

/// Fond des cartes de l'onglet Réseau.
extension View {
    func enCarte() -> some View {
        return self
            .padding(14)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Color(.secondarySystemGroupedBackground), in: RoundedRectangle(cornerRadius: 16))
    }
}

/// Titre d'une section de l'onglet Réseau.
@MainActor
struct TitreReseau: View {
    let titre: String
    let icone: String

    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: icone)
            Text(titre).font(.title2.bold())
            Spacer()
        }
        .padding(.top, 4)
    }
}

// MARK: bloc « calcul » d'une fiche

@MainActor
struct BlocCalcul: View {
    let machine: Machine
    let calcul: Calcul
    @Environment(ModeleAppli.self) private var modele

    var body: some View {
        let m = machine
        VStack(alignment: .leading, spacing: 8) {
            ForEach(Reseau.barres(m), id: \.libelle) { b in
                HStack(spacing: 8) {
                    Text(b.libelle).font(.caption.weight(.semibold)).frame(width: 70, alignment: .leading)
                    ProgressView(value: b.part).tint(b.chaude ? Color.red : Color.accentCcs)
                    Text(b.valeur).font(.caption.monospacedDigit()).foregroundStyle(.secondary)
                }
                .accessibilityElement(children: .combine)
            }
            if m.tools.isEmpty {
                Text("outils pas encore inventoriés").font(.caption).foregroundStyle(.secondary)
            } else {
                FlowLayout(espacement: 6) {
                    ForEach(m.tools, id: \.self) { t in
                        Text(t).font(.caption2.weight(.semibold))
                            .padding(.horizontal, 8).padding(.vertical, 3)
                            .background(Color(.tertiarySystemFill), in: Capsule())
                    }
                }
                .accessibilityLabel("Outils : " + m.tools.joined(separator: ", "))
            }
            HStack {
                Text(m.places).font(.footnote)
                Spacer()
                Text("Limite").font(.footnote).foregroundStyle(.secondary)
                Picker("Limite", selection: Binding(get: { m.limit }, set: { n in
                    Task { await calcul.changerLimite(m, n, modele) }
                })) {
                    ForEach(Travaux.limites, id: \.self) { n in Text("\(n)").tag(n) }
                }
                .pickerStyle(.menu)
                .accessibilityLabel("Limite de travaux sur \(m.nom)")
            }
            if Reseau.injoignable(m) {
                Text("Ni réseau maillé ni tunnel SSH Ricochet sur cette machine.").font(.caption).foregroundStyle(.secondary)
            }
        }
        .padding(10)
        .background(Color(.tertiarySystemFill).opacity(0.5), in: RoundedRectangle(cornerRadius: 12))
        .accessibilityElement(children: .contain)
        .accessibilityLabel("Calcul sur \(m.nom)")
    }
}

// MARK: travaux

@MainActor
struct SectionTravaux: View {
    let calcul: Calcul
    @Environment(ModeleAppli.self) private var modele
    @State private var journal: TravailDistant? = nil
    @State private var aArreter: TravailDistant? = nil

    var body: some View {
        let actifs = calcul.travaux.filter { Travaux.actif($0) }
        let finis = calcul.travaux.filter { !Travaux.actif($0) }
        VStack(alignment: .leading, spacing: 10) {
            Text("En cours et à venir (\(actifs.count))").font(.subheadline.weight(.semibold))
            if let e = calcul.erreurTravaux {
                Text(e).font(.footnote).foregroundStyle(.red)
            } else if actifs.isEmpty {
                Text(calcul.charge ? "Rien en cours." : "Chargement…").font(.footnote).foregroundStyle(.secondary)
            }
            ForEach(actifs) { j in ligneTravail(j) }
            if !finis.isEmpty {
                Divider()
                Text("Finis (\(finis.count))").font(.subheadline.weight(.semibold))
                ForEach(finis) { j in ligneTravail(j) }
            }
        }
        .enCarte()
        .sheet(item: $journal) { j in
            FeuilleJournal(travail: j, home: calcul.home).environment(modele)
        }
        .confirmationDialog("Arrêter ce travail ?", isPresented: Binding(get: { aArreter != nil }, set: { if !$0 { aArreter = nil } }),
                            titleVisibility: .visible, presenting: aArreter) { j in
            Button("Arrêter", role: .destructive) { Task { await calcul.arreter(j, modele) } }
            Button("Garder", role: .cancel) {}
        } message: { j in
            Text(texteArret(j))
        }
    }

    private func ligneTravail(_ j: TravailDistant) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(alignment: .firstTextBaseline) {
                Text(j.text).font(.system(.subheadline, design: .monospaced)).lineLimit(2)
                Spacer()
                PastilleEtat(travail: j)
            }
            Text(Travaux.ligne(j, home: calcul.home)).font(.caption).foregroundStyle(.secondary)
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

    private func texteArret(_ j: TravailDistant) -> String {
        if Travaux.enCours(j) { return "« \(j.text) » sera arrêtée sur \(j.machine ?? "la machine")." }
        return "« \(j.text) » ne sera pas lancée."
    }
}

// MARK: lancer une commande

@MainActor
struct SectionLancer: View {
    let calcul: Calcul
    @Environment(ModeleAppli.self) private var modele

    @State private var commande = ""
    @State private var dossier = ""
    @State private var cible = ""
    @State private var quand = ""
    @State private var heure = Date()
    @State private var erreurLancer: String? = nil
    @State private var lance = false

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            TextField("flutter build apk", text: $commande)
                .font(.system(.body, design: .monospaced))
                .textInputAutocapitalization(.never).autocorrectionDisabled()
                .textFieldStyle(.roundedBorder)
            TextField("Dossier (~/Work/mon-projet)", text: $dossier)
                .textInputAutocapitalization(.never).autocorrectionDisabled()
                .textFieldStyle(.roundedBorder)
            LabeledContent("Machine") {
                Picker("Machine", selection: $cible) {
                    Text("La moins chargée").tag("")
                    ForEach(calcul.machines.filter { !$0.local || $0.online }) { m in
                        Text(nomCible(m)).tag(m.id)
                    }
                }
                .pickerStyle(.menu)
            }
            LabeledContent("Quand") {
                Picker("Quand", selection: $quand) {
                    Text("Maintenant").tag("")
                    Text("Cette nuit").tag("nuit")
                    Text("À une heure…").tag("heure")
                }
                .pickerStyle(.menu)
            }
            if quand == "heure" {
                DatePicker("Heure", selection: $heure, displayedComponents: .hourAndMinute)
            }
            if let e = erreurLancer { Text(e).font(.footnote).foregroundStyle(.red) }
            Button { Task { await lancer() } } label: {
                Label(lance ? "Envoi…" : "Lancer", systemImage: "play.fill")
            }
            .buttonStyle(.borderedProminent)
            .disabled(lance)
            Text("Une ligne de shell, lancée dans le dossier (dans le dossier personnel du serveur), envoyée à la machine choisie.")
                .font(.caption).foregroundStyle(.secondary)
        }
        .enCarte()
    }

    private func nomCible(_ m: Machine) -> String {
        return m.online ? m.nom : m.nom + " (hors ligne)"
    }

    private func lancer() async {
        erreurLancer = nil
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "HH:mm"
        let d = Travaux.demande(commande: commande, dossier: dossier, home: calcul.home, machine: cible, quand: quand, heure: f.string(from: heure))
        guard let p = d.params else {
            erreurLancer = d.erreur
            return
        }
        lance = true
        defer { lance = false }
        do {
            _ = try await modele.client.appeler("machines.start", p, delai: 30)
            commande = ""
            modele.avis.dire(quand.isEmpty ? "Commande lancée." : "Commande programmée.")
            await calcul.rafraichir(modele.client)
        } catch {
            erreurLancer = texteErreur(error)
        }
    }
}

// MARK: ajouter un PC par Ricochet

/// Avec le jeton opérateur de Ricochet : un seul lien installe SSH, l'agent Ricochet (secours) et
/// inscrit le PC au réseau maillé (`machines.add`). Placé dans « Ajouter un appareil » → PC Linux.
@MainActor
struct FormulairePcRicochet: View {
    let calcul: Calcul
    @Environment(ModeleAppli.self) private var modele

    @State private var identifiant = ""
    @State private var compte = ""
    @State private var nom = ""
    @State private var complet = false
    @State private var erreur: String? = nil
    @State private var occupe = false
    @State private var resultat: AjoutMachine? = nil

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            champ("Identifiant", "pc-salon", $identifiant, aide: "lettres, chiffres, - et _")
            champ("Ton compte sur ce PC", "charles", $compte, aide: "terminal, fichiers et travaux tournent sous ce compte")
            champ("Nom affiché (facultatif)", "PC du salon", $nom, aide: nil)
            Toggle(isOn: $complet) {
                VStack(alignment: .leading, spacing: 2) {
                    Text("Installer aussi CCS et Claude Code").font(.subheadline)
                    Text("pour ouvrir des sessions entières sur ce PC").font(.caption2).foregroundStyle(.secondary)
                }
            }
            if let e = erreur { Text(e).font(.footnote).foregroundStyle(.red) }
            Button { Task { await creer() } } label: { Label("Créer le lien", systemImage: "link") }
                .buttonStyle(.borderedProminent)
                .disabled(occupe || identifiant.trimmingCharacters(in: .whitespaces).isEmpty || compte.trimmingCharacters(in: .whitespaces).isEmpty)
            if let r = resultat {
                Text("Colle cette commande dans un terminal de « \(r.id) » (Ubuntu ou Debian). Le lien ne sert qu'une fois, pendant \(max(1, Int((Double(r.expiresS) / 60).rounded()))) min.")
                    .font(.footnote)
                HStack(alignment: .top) {
                    Text(r.command).font(.caption2.monospaced()).foregroundStyle(Color(white: 0.9)).textSelection(.enabled)
                    Spacer(minLength: 4)
                    Button { copier(r.command); modele.avis.dire("Copié.") } label: { Image(systemName: "doc.on.doc") }
                        .foregroundStyle(Color(white: 0.9))
                }
                .padding(10)
                .background(Color(white: 0.12), in: RoundedRectangle(cornerRadius: 10))
                Text("Elle installe le serveur SSH et l'agent Ricochet (secours), autorise la clé de ce serveur"
                     + (r.mesh ? " et inscrit la machine au réseau maillé" : "")
                     + (r.full ? ", puis installe CCS et Claude Code" : "")
                     + " ; elle apparaît ensuite ici, avec sa charge et ses outils.")
                    .font(.caption).foregroundStyle(.secondary)
            }
        }
    }

    private func champ(_ titre: String, _ exemple: String, _ texte: Binding<String>, aide: String?) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(titre).font(.caption.weight(.semibold))
            TextField(exemple, text: texte)
                .textInputAutocapitalization(.never).autocorrectionDisabled()
                .textFieldStyle(.roundedBorder)
            if let a = aide { Text(a).font(.caption2).foregroundStyle(.secondary) }
        }
    }

    private func creer() async {
        erreur = nil
        resultat = nil
        var p: [String: JSON] = ["machine": .chaine(identifiant.trimmingCharacters(in: .whitespaces)),
                                 "user": .chaine(compte.trimmingCharacters(in: .whitespaces))]
        let n = nom.trimmingCharacters(in: .whitespaces)
        if !n.isEmpty { p["name"] = .chaine(n) }
        if complet { p["full"] = .booleen(true) }
        occupe = true
        defer { occupe = false }
        do {
            resultat = try await modele.client.appeler("machines.add", p, delai: 60, en: AjoutMachine.self)
            identifiant = ""
            nom = ""
            await calcul.rafraichir(modele.client)
        } catch {
            erreur = texteErreur(error)
        }
    }
}

// MARK: secours Ricochet

/// Réglages du relais Ricochet, repliés en bas de l'onglet : le réseau maillé passe d'abord.
@MainActor
struct SecoursRicochet: View {
    let calcul: Calcul
    @Environment(ModeleAppli.self) private var modele

    @State private var ouvert = false
    @State private var relais = ""
    @State private var jeton = ""
    @State private var erreurRelais: String? = nil

    var body: some View {
        DisclosureGroup(isExpanded: $ouvert) {
            VStack(alignment: .leading, spacing: 10) {
                Text("Le réseau maillé passe d'abord ; Ricochet prend le relais quand il ne joint pas une machine.")
                    .font(.footnote).foregroundStyle(.secondary)
                if let e = calcul.erreurMachines {
                    Text(e).font(.footnote).foregroundStyle(.red)
                } else if let l = calcul.liste {
                    if let m = l.message, !m.isEmpty {
                        Text(m).font(.footnote).foregroundStyle(l.configured ? Color.red : Color.secondary)
                    } else if !l.configured {
                        Text("Relais Ricochet non configuré : remplis ses réglages ci-dessous.").font(.footnote).foregroundStyle(.secondary)
                    }
                }
                TextField("https://ricochet.exemple", text: $relais)
                    .keyboardType(.URL).textInputAutocapitalization(.never).autocorrectionDisabled()
                    .textFieldStyle(.roundedBorder)
                SecureField(calcul.reglages?.jetonDefini == true ? "Jeton (laisser vide pour le garder)" : "Jeton du relais", text: $jeton)
                    .textFieldStyle(.roundedBorder)
                if let e = erreurRelais { Text(e).font(.footnote).foregroundStyle(.red) }
                Button("Enregistrer") { Task { await enregistrerRelais() } }
                    .buttonStyle(.borderedProminent)
                    .disabled(calcul.reglages == nil)
                if let r = calcul.reglages {
                    Text(piedRelais(r)).font(.caption).foregroundStyle(.secondary)
                }
            }
            .padding(.top, 8)
        } label: {
            Label("Secours Ricochet", systemImage: "lifepreserver").font(.headline)
        }
        .enCarte()
        .onAppear { remplir() }
        .onChange(of: calcul.reglages?.relais) { _, _ in remplir() }
    }

    private func remplir() {
        if relais.isEmpty, let r = calcul.reglages { relais = r.relais }
    }

    private func piedRelais(_ r: ReglagesRelais) -> String {
        let j: String = r.jetonDefini ? "Jeton enregistré." : "Aucun jeton."
        let f: String = Format.court(r.chemin, home: calcul.home)
        return "\(j) Fichier : \(f) · limite par défaut : \(r.limiteDefaut) travaux à la fois par machine."
    }

    private func enregistrerRelais() async {
        erreurRelais = nil
        var p: [String: JSON] = [:]
        let r = relais.trimmingCharacters(in: .whitespaces)
        if r != (calcul.reglages?.relais ?? "") { p["relay"] = .chaine(r) }
        if !jeton.isEmpty { p["token"] = .chaine(jeton) }
        if p.isEmpty {
            erreurRelais = "Rien à enregistrer."
            return
        }
        do {
            _ = try await modele.client.appeler("machines.configure", p)
            jeton = ""
            modele.avis.dire("Réglages du relais enregistrés.")
            await calcul.lireReglages(modele.client)
            await calcul.rafraichir(modele.client)
        } catch {
            erreurRelais = texteErreur(error)
        }
    }
}

// MARK: pastille et journal

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
        Text(Travaux.libelle(travail))
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
                        Text("\(Travaux.libelle(t)) · \(Travaux.ligne(t, home: home))").font(.caption).foregroundStyle(.secondary)
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
