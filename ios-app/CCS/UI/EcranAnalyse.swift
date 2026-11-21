import SwiftUI

/// Analyse (`analysis.js`) : usage pondéré par projet, modèle, compte et heure.
@MainActor
struct EcranAnalyse: View {
    @Environment(ModeleAppli.self) private var modele
    @State private var jours = 7
    @State private var rapport: Rapport? = nil
    @State private var erreur: String? = nil
    @State private var essai = 0

    private struct Cle: Equatable {
        let jours: Int
        let essai: Int
    }

    var body: some View {
        ScrollView {
            VStack(spacing: 12) {
                Picker("Période", selection: $jours) {
                    ForEach(periodesAnalyse, id: \.jours) { p in Text(p.libelle).tag(p.jours) }
                }
                .pickerStyle(.segmented)
                if let e = erreur {
                    EtatErreur(message: e) { essai += 1 }
                } else if let r = rapport {
                    if r.responses == 0 {
                        EtatVide("Aucune activité sur cette période.") {
                            if jours != 30 { Button("Essayer 30 jours") { jours = 30 }.buttonStyle(.bordered) }
                        }
                    } else {
                        CarteFond {
                            Text(Format.nombreCourt(r.total))
                                .font(.system(size: 40, weight: .bold))
                                .foregroundStyle(Color.accentCcs)
                            Text("jetons pondérés · \(r.responses) réponses").foregroundStyle(.secondary)
                        }
                        GrosConsommateurs(liste: r.top)
                        Barres(titre: "Par projet", donnees: r.parProjet, total: r.total)
                        Barres(titre: "Par modèle", donnees: r.parModele, total: r.total)
                        Barres(titre: "Par compte", donnees: r.parCompte, total: r.total)
                        Heures(parHeure: r.parHeure)
                    }
                } else {
                    Chargement(texte: "Lecture des journaux…")
                }
            }
            .padding(16)
        }
        .background(Color.fondGroupe)
        .navigationTitle("Analyse")
        .navigationBarTitleDisplayMode(.inline)
        .task(id: Cle(jours: jours, essai: essai)) {
            rapport = nil
            erreur = nil
            do {
                rapport = try await modele.client.appeler("analysis.report", ["days": .de(jours)], delai: 90, en: Rapport.self)
            } catch {
                if !Task.isCancelled { erreur = texteErreur(error) }
            }
        }
    }
}

@MainActor
private struct Barres: View {
    let titre: String
    let donnees: [String: Double]
    let total: Double

    var body: some View {
        let lignes = Format.barres(donnees, total: total)
        if !lignes.isEmpty {
            CarteFond {
                Text(titre).font(.headline)
                ForEach(lignes, id: \.nom) { l in
                    VStack(alignment: .leading, spacing: 3) {
                        HStack {
                            Text(l.nom).font(.subheadline).lineLimit(1).truncationMode(.middle)
                            Spacer()
                            Text(String(format: "%.1f %%", l.part)).font(.subheadline.weight(.semibold))
                        }
                        BarreJauge(pourcent: l.part, couleur: .accentCcs)
                    }
                }
            }
        }
    }
}

/// Conversations qui pèsent le plus : titre, projet, part de l'usage, causes probables.
@MainActor
private struct GrosConsommateurs: View {
    let liste: [GrosConsommateur]

    var body: some View {
        if !liste.isEmpty {
            CarteFond {
                Text("Gros consommateurs").font(.headline)
                ForEach(liste) { c in
                    VStack(alignment: .leading, spacing: 3) {
                        HStack(alignment: .firstTextBaseline) {
                            VStack(alignment: .leading, spacing: 1) {
                                Text(c.titre.isEmpty ? "Sans titre" : c.titre).font(.subheadline).lineLimit(2)
                                if !c.projet.isEmpty {
                                    Text(c.projet).font(.caption).foregroundStyle(.secondary).lineLimit(1).truncationMode(.middle)
                                }
                            }
                            Spacer()
                            Text(String(format: "%.1f %%", c.part).replacingOccurrences(of: ".", with: ","))
                                .font(.subheadline.weight(.semibold))
                        }
                        BarreJauge(pourcent: c.part, couleur: .accentCcs)
                        ForEach(Array(c.causes.enumerated()), id: \.offset) { _, cause in
                            Text("• " + cause).font(.caption).foregroundStyle(.secondary)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                    }
                }
            }
        }
    }
}

@MainActor
private struct Heures: View {
    let parHeure: [Double]

    var body: some View {
        if !parHeure.isEmpty {
            let pic = max(1, parHeure.max() ?? 1)
            CarteFond {
                Text("Par heure").font(.headline)
                HStack(alignment: .bottom, spacing: 2) {
                    ForEach(Array(parHeure.enumerated()), id: \.offset) { _, v in
                        GeometryReader { g in
                            VStack(spacing: 0) {
                                Spacer(minLength: 0)
                                UnevenRoundedRectangle(topLeadingRadius: 2, topTrailingRadius: 2)
                                    .fill(Color.accentCcs)
                                    .frame(height: max(1, g.size.height * min(1, v / pic)))
                            }
                        }
                    }
                }
                .frame(height: 120)
                HStack {
                    ForEach(["0 h", "6 h", "12 h", "18 h", "23 h"], id: \.self) { t in
                        Text(t).font(.caption2).foregroundStyle(.secondary)
                        if t != "23 h" { Spacer() }
                    }
                }
            }
        }
    }
}
