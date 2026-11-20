import SwiftUI

/// Ce que le fil peut demander à l'écran.
struct ActionsFil {
    var citer: (Citation.Auteur, String) -> Void
    var passage: (MessageChoisi) -> Void
    var etiqueter: (MessageChoisi) -> Void
    var voirAgent: (String) -> Void
    var repondre: (String, String, String) -> Void
    var questions: (String, [String: JSON]) -> Void
    var arreterShell: (String) -> Void
    var reprendre: () -> Void
    var compacter: () -> Void
    var voirEtiquette: (String) -> Void
}

/// Auteur, texte d'origine et identifiant d'un message du fil (actions « Répondre », « Étiqueter »).
struct MessageChoisi: Identifiable, Equatable {
    let auteur: Citation.Auteur
    let brut: String
    let msgId: String
    var id: String { return msgId + "|" + String(brut.count) }

    /// Texte cité ou étiqueté : pour un message qui citait, sa réponse.
    var texte: String { return auteur == .moi ? Citation.texteSource(brut) : brut }
}

let vertDiff = Color(red: 0x2E / 255.0, green: 0xA0 / 255.0, blue: 0x43 / 255.0)
let rougeDiff = Color(red: 0xE5 / 255.0, green: 0x53 / 255.0, blue: 0x4B / 255.0)

/// Une ligne du fil. `etiquettes` : celles du message montré (s'il en a).
@MainActor
struct LigneVue: View {
    let ligne: LigneFil
    let etiquettes: [String]?
    let surligne: Bool
    let actions: ActionsFil

    var body: some View {
        Group {
            switch ligne {
            case .groupe(let outils, _):
                GroupeOutils(outils: outils)
            case .seul(let e, _):
                switch e {
                case .toi(let m): MessageToi(m: m, etiquettes: etiquettes, actions: actions)
                case .claude(let m): MessageClaude(m: m, etiquettes: etiquettes, actions: actions)
                case .outil(let o): CarteOutil(e: o)
                case .agent(let a): CarteAgent(e: a, actions: actions)
                case .note(let n): NoteVue(e: n, actions: actions)
                case .separateur(let s): SeparateurVue(e: s)
                case .demande(let d): CarteDemande(e: d, actions: actions)
                case .questions(let q): CarteQuestions(e: q, actions: actions)
                case .commande(let c): CarteCommande(e: c, actions: actions)
                case .arrete(let a): CarteArret(e: a, actions: actions)
                }
            }
        }
        .overlay {
            if surligne { RoundedRectangle(cornerRadius: 12).stroke(Color.avertissement, lineWidth: 2) }
        }
        .opacity(ligne.grise ? 0.55 : 1)
    }
}

/// Étiquettes d'un message, touchables (ouvrent le volet filtré).
@MainActor
private struct Pastilles: View {
    let etiquettes: [String]?
    let actions: ActionsFil
    let fin: Bool

    var body: some View {
        if let t = etiquettes, !t.isEmpty {
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 4) {
                    ForEach(t, id: \.self) { e in
                        Button {
                            actions.voirEtiquette(e)
                        } label: {
                            Label(e, systemImage: "tag").font(.caption2)
                        }
                        .buttonStyle(.bordered)
                        .controlSize(.mini)
                    }
                }
            }
            .frame(maxWidth: .infinity, alignment: fin ? .trailing : .leading)
        }
    }
}

/// Menu d'un message (appui long) : Répondre, Citer un passage, Copier, Étiqueter.
@MainActor
private struct MenuMessage: View {
    @Environment(ModeleAppli.self) private var modele
    let m: MessageChoisi
    let actions: ActionsFil

    var body: some View {
        Button {
            actions.citer(m.auteur, m.brut)
        } label: {
            Label("Répondre", systemImage: "arrowshape.turn.up.left")
        }
        Button {
            actions.passage(m)
        } label: {
            Label("Citer un passage…", systemImage: "text.quote")
        }
        Button {
            copier(m.texte)
            modele.avis.dire("Message copié.")
        } label: {
            Label("Copier", systemImage: "doc.on.doc")
        }
        Button {
            actions.etiqueter(m)
        } label: {
            Label("Étiqueter", systemImage: "tag")
        }
    }
}

@MainActor
private struct MessageToi: View {
    let m: ElementFil.MsgToi
    let etiquettes: [String]?
    let actions: ActionsFil

    var body: some View {
        let d = Citation.decouper(m.texte)
        VStack(alignment: .trailing, spacing: 2) {
            VStack(alignment: .leading, spacing: 6) {
                if let c = d { BlocCite(auteur: c.auteur, texte: c.texte) }
                Text(d?.corps ?? m.texte)
                    .font(.system(size: tailleTexteChat))
                    .fixedSize(horizontal: false, vertical: true)
                if m.images > 0 {
                    Text("\(m.images) image(s) jointe(s)").font(.caption).foregroundStyle(.secondary)
                }
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 8)
            .background(UnevenRoundedRectangle(topLeadingRadius: 16, bottomLeadingRadius: 16, bottomTrailingRadius: 4, topTrailingRadius: 16)
                .fill(Color.accentCcs.opacity(0.18)))
            .contextMenu { MenuMessage(m: MessageChoisi(auteur: .moi, brut: m.texte, msgId: m.msgId), actions: actions) }
            Pastilles(etiquettes: etiquettes, actions: actions, fin: true)
        }
        .frame(maxWidth: .infinity, alignment: .trailing)
        .padding(.leading, 40)
    }
}

/// Citation dans une bulle : l'auteur et le passage, replié sur trois lignes (toucher le déplie).
@MainActor
struct BlocCite: View {
    let auteur: Citation.Auteur
    let texte: String
    @State private var ouvert = false

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(auteur.affiche).font(.caption.weight(.semibold)).foregroundStyle(Color.accentCcs)
            if auteur == .claude && ouvert {
                MarkdownVue(texte: texte)
            } else {
                Text(texte).font(.footnote).lineLimit(ouvert ? nil : 3)
            }
        }
        .padding(8)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 8).fill(Color(UIColor.systemBackground).opacity(0.5)))
        .contentShape(Rectangle())
        .onTapGesture { withAnimation { ouvert.toggle() } }
    }
}

@MainActor
private struct MessageClaude: View {
    let m: ElementFil.MsgClaude
    let etiquettes: [String]?
    let actions: ActionsFil

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            MarkdownVue(texte: m.texte)
                .padding(.horizontal, 12)
                .padding(.vertical, 10)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(UnevenRoundedRectangle(topLeadingRadius: 16, bottomLeadingRadius: 4, bottomTrailingRadius: 16, topTrailingRadius: 16)
                    .fill(Color.carte))
                .contextMenu { MenuMessage(m: MessageChoisi(auteur: .claude, brut: m.texte, msgId: m.msgId), actions: actions) }
            Pastilles(etiquettes: etiquettes, actions: actions, fin: false)
        }
    }
}

@MainActor
private struct Marque: View {
    let fini: Bool
    let erreur: Bool

    var body: some View {
        if !fini {
            ProgressView().controlSize(.mini)
        } else if erreur {
            Image(systemName: "xmark").font(.caption.bold()).foregroundStyle(.red).accessibilityLabel("erreur")
        } else {
            Image(systemName: "checkmark").font(.caption.bold()).foregroundStyle(Color.reussite).accessibilityLabel("fini")
        }
    }
}

/// Carte d'un outil : repliée sur une ligne (nom, cible, état), dépliée : diff ou paramètres, puis résultat.
@MainActor
struct CarteOutil: View {
    let e: ElementFil.Outil
    @State private var ouvert = false

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Button {
                withAnimation(.easeOut(duration: 0.15)) { ouvert.toggle() }
            } label: {
                HStack(spacing: 6) {
                    Image(systemName: e.nom == "Bash" ? "terminal" : "wrench.and.screwdriver")
                        .font(.caption).foregroundStyle(.secondary)
                    Text(Outils.libelle(e.nom)).font(.subheadline.weight(.semibold))
                    Text(e.cible)
                        .font(e.nom == "Bash" ? .system(.caption, design: .monospaced) : .caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                        .truncationMode(.middle)
                        .frame(maxWidth: .infinity, alignment: .leading)
                    if let d = e.diff {
                        Text("+\(d.ajouts)").font(.caption2).foregroundStyle(vertDiff)
                        Text("−\(d.retraits)").font(.caption2).foregroundStyle(rougeDiff)
                    }
                    Marque(fini: e.fini, erreur: e.erreur)
                }
                .padding(.horizontal, 10)
                .padding(.vertical, 8)
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            if ouvert {
                Divider()
                VStack(alignment: .leading, spacing: 6) {
                    if let d = e.diff {
                        VueDiff(d: d)
                    } else if !e.details.isEmpty {
                        TexteMono(texte: e.details, lignes: 30)
                    }
                    if let r = e.resultat {
                        TexteMono(texte: r.isEmpty ? "(aucune sortie)" : r, lignes: 40, erreur: e.erreur)
                    }
                }
                .padding(8)
            }
        }
        .background(RoundedRectangle(cornerRadius: 10).fill(Color.carte.opacity(0.6)))
        .overlay(RoundedRectangle(cornerRadius: 10).stroke(e.erreur ? Color.red.opacity(0.5) : Color.secondary.opacity(0.25), lineWidth: 1))
        .padding(.leading, e.imbrique ? 16 : 0)
    }
}

/// Texte à chasse fixe, coupé à `lignes` lignes avec « Tout afficher ».
@MainActor
struct TexteMono: View {
    let texte: String
    let lignes: Int
    var erreur = false
    @State private var tout = false

    var body: some View {
        let long = texte.filter { $0 == "\n" }.count >= lignes || texte.count > 4000
        let montre = (!long || tout) ? texte : String(texte.components(separatedBy: "\n").prefix(lignes).joined(separator: "\n").prefix(4000))
        VStack(alignment: .leading, spacing: 0) {
            ScrollView(.horizontal, showsIndicators: false) {
                Text(montre)
                    .font(.system(size: 12, design: .monospaced))
                    .foregroundStyle(erreur ? Color.red : Color.primary)
                    .textSelection(.enabled)
                    .fixedSize(horizontal: true, vertical: true)
                    .padding(8)
            }
            if long {
                Button(tout ? "Réduire" : "Tout afficher") { tout.toggle() }
                    .font(.caption)
                    .padding(.horizontal, 8)
                    .padding(.bottom, 6)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 6).fill(Color.fondCode))
    }
}

@MainActor
struct VueDiff: View {
    @Environment(\.liensFichiers) private var liens
    @Environment(\.naviguer) private var naviguer
    let d: Diff.Fichier

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            if liens != nil && d.chemin.hasPrefix("/") {
                // dans un chat : le fichier modifié s'ouvre d'un toucher
                Button { naviguer(.fichier(chemin: d.chemin, ligne: nil)) } label: {
                    Text(d.chemin).font(.caption2).underline().foregroundStyle(Color.accentCcs)
                        .lineLimit(2).truncationMode(.head)
                }
                .buttonStyle(.plain)
            } else {
                Text(d.chemin).font(.caption2).foregroundStyle(.secondary).lineLimit(2).truncationMode(.head)
            }
            CorpsDiff(lignesDiff: d.lignes)
        }
    }
}

/**
 * Lignes d'un diff : ajouts en vert, retraits en rouge, séparateurs de morceaux ; numéros de ligne
 * quand ils sont connus (git). Au-delà de `max` lignes : « Tout afficher ».
 */
@MainActor
struct CorpsDiff: View {
    let lignesDiff: [Diff.Ligne]
    var max: Int = 80
    @State private var tout = false

    var body: some View {
        let lignes = (tout || lignesDiff.count <= max) ? lignesDiff : Array(lignesDiff.prefix(max))
        let numeros = lignesDiff.contains { $0.ancien != nil || $0.nouveau != nil }
        let chiffres = String(lignesDiff.map { Swift.max($0.ancien ?? 0, $0.nouveau ?? 0) }.max() ?? 0).count
        VStack(alignment: .leading, spacing: 0) {
            ScrollView(.horizontal, showsIndicators: false) {
                VStack(alignment: .leading, spacing: 0) {
                    ForEach(Array(lignes.enumerated()), id: \.offset) { _, l in
                        Text(texte(l, numeros: numeros, chiffres: chiffres))
                            .font(.system(size: 12, design: .monospaced))
                            .foregroundStyle(encre(l.genre))
                            .padding(.horizontal, 8)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .background(fond(l.genre))
                    }
                }
                .padding(.vertical, 6)
                .fixedSize(horizontal: true, vertical: false)
            }
            .background(RoundedRectangle(cornerRadius: 6).fill(Color.fondCode))
            if lignesDiff.count > max {
                Button(tout ? "Réduire" : "Tout afficher (\(lignesDiff.count) lignes)") { tout.toggle() }.font(.caption)
            }
        }
    }

    private func texte(_ l: Diff.Ligne, numeros: Bool, chiffres: Int) -> String {
        let signe: String
        switch l.genre {
        case .ajout: signe = "+"
        case .retrait: signe = "−"
        case .morceau: signe = ""
        case .contexte: signe = " "
        }
        var no = ""
        if numeros && l.genre != .morceau {
            func cadre(_ n: Int?) -> String {
                let t = n.map { String($0) } ?? ""
                return String(repeating: " ", count: Swift.max(0, chiffres - t.count)) + t
            }
            no = cadre(l.ancien) + " " + cadre(l.nouveau) + " "
        }
        return no + signe + " " + l.texte
    }

    private func encre(_ g: Diff.Genre) -> Color {
        switch g {
        case .ajout: return vertDiff
        case .retrait: return rougeDiff
        case .morceau: return .accentCcs
        case .contexte: return .primary
        }
    }

    private func fond(_ g: Diff.Genre) -> Color {
        switch g {
        case .ajout: return vertDiff.opacity(0.14)
        case .retrait: return rougeDiff.opacity(0.14)
        default: return .clear
        }
    }
}

@MainActor
private struct GroupeOutils: View {
    let outils: [ElementFil.Outil]
    @State private var ouvert = false

    var body: some View {
        let dernier = outils.last
        let enCours = outils.contains { !$0.fini }
        VStack(alignment: .leading, spacing: 0) {
            Button {
                withAnimation(.easeOut(duration: 0.15)) { ouvert.toggle() }
            } label: {
                HStack(spacing: 6) {
                    Image(systemName: ouvert ? "chevron.up" : "chevron.down").font(.caption)
                    Text("\(outils.count) actions").font(.subheadline.weight(.semibold))
                    Text("· \(Outils.libelle(dernier?.nom ?? "")) \(dernier?.cible ?? "")")
                        .font(.caption).foregroundStyle(.secondary).lineLimit(1)
                        .frame(maxWidth: .infinity, alignment: .leading)
                    Marque(fini: !enCours, erreur: outils.contains { $0.erreur })
                }
                .padding(.horizontal, 10)
                .padding(.vertical, 8)
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            if ouvert {
                VStack(spacing: 4) {
                    ForEach(outils) { o in CarteOutil(e: o) }
                }
                .padding(6)
            }
        }
        .background(RoundedRectangle(cornerRadius: 10).fill(Color.carte.opacity(0.6)))
        .overlay(RoundedRectangle(cornerRadius: 10).stroke(Color.secondary.opacity(0.25), lineWidth: 1))
    }
}

@MainActor
private struct CarteAgent: View {
    let e: ElementFil.Agent
    let actions: ActionsFil
    @State private var ouvert = false

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 8) {
                Image(systemName: "cpu").foregroundStyle(Color.accentCcs)
                VStack(alignment: .leading, spacing: 1) {
                    Text("Sous-agent · \(e.nom)").font(.subheadline.weight(.semibold)).lineLimit(2)
                    Text(etat).font(.caption).foregroundStyle(.secondary)
                }
                Spacer()
                Button("Voir") { actions.voirAgent(e.cle) }.buttonStyle(.bordered).controlSize(.small)
            }
            Button(ouvert ? "Masquer la consigne" : "Consigne et résultat") {
                withAnimation { ouvert.toggle() }
            }
            .font(.caption)
            if ouvert {
                TexteMono(texte: e.consigne, lignes: 20)
                if let r = e.resultat { MarkdownVue(texte: r) }
            }
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 8)
        .background(RoundedRectangle(cornerRadius: 10).fill(Color.accentCcs.opacity(0.08)))
    }

    private var etat: String {
        switch e.statut {
        case .travaille: return e.arrierePlan ? "en arrière-plan…" : "au travail…"
        case .fini: return "✓ terminé"
        case .arrete: return "arrêté"
        }
    }
}

@MainActor
private struct NoteVue: View {
    let e: ElementFil.Note
    let actions: ActionsFil

    var body: some View {
        HStack {
            Text(e.texte)
                .font(.footnote)
                .foregroundStyle(e.genre == "error" ? Color.red : (e.genre == "warning" ? Color.primary : Color.secondary))
                .frame(maxWidth: .infinity, alignment: .leading)
            if e.action == .compacter {
                Button("Compacter", action: actions.compacter).buttonStyle(.bordered).controlSize(.small)
            }
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 6)
        .background(RoundedRectangle(cornerRadius: 8).fill(fond))
    }

    private var fond: Color {
        switch e.genre {
        case "error": return Color.red.opacity(0.12)
        case "warning": return Color.avertissement.opacity(0.15)
        default: return Color.secondary.opacity(0.1)
        }
    }
}

@MainActor
private struct SeparateurVue: View {
    let e: ElementFil.Separateur

    var body: some View {
        HStack(spacing: 8) {
            Rectangle().fill(Color.accentCcs).frame(width: 24, height: 1)
            Text(e.auto
                ? "Sujet terminé : Claude a effacé la conversation — il ne voit plus les messages au-dessus"
                : "Nouvelle conversation — Claude ne voit plus les messages au-dessus")
                .font(.caption.weight(.medium))
                .foregroundStyle(Color.accentCcs)
                .multilineTextAlignment(.center)
                .frame(maxWidth: .infinity)
            Rectangle().fill(Color.accentCcs).frame(width: 24, height: 1)
        }
        .padding(.vertical, 8)
    }
}

@MainActor
private struct CarteDemande: View {
    let e: ElementFil.Demande
    let actions: ActionsFil
    @State private var motif = ""
    @State private var details = false

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Claude demande : \(e.outil)").font(.subheadline.weight(.semibold))
            TexteMono(texte: e.cible.isEmpty ? e.details : e.cible, lignes: 12)
            if !e.description.isEmpty {
                Text(e.description).font(.footnote).foregroundStyle(.secondary)
            }
            if !e.cible.isEmpty {
                Button(details ? "Masquer les détails" : "Détails") { details.toggle() }.font(.caption)
                if details { TexteMono(texte: e.details, lignes: 30) }
            }
            HStack(spacing: 8) {
                Button("Autoriser") { actions.repondre(e.cle, "allow", motif) }.buttonStyle(.borderedProminent)
                Button("Toujours") { actions.repondre(e.cle, "always", motif) }.buttonStyle(.bordered)
                Button("Refuser", role: .destructive) { actions.repondre(e.cle, "deny", motif) }.buttonStyle(.bordered)
            }
            .controlSize(.small)
            TextField("Motif du refus (facultatif)", text: $motif).textFieldStyle(.roundedBorder).font(.footnote)
        }
        .padding(12)
        .background(RoundedRectangle(cornerRadius: 12).fill(Color.carte))
        .overlay(RoundedRectangle(cornerRadius: 12).stroke(Color.avertissement, lineWidth: 2))
    }
}

@MainActor
private struct CarteQuestions: View {
    let e: ElementFil.Questions
    let actions: ActionsFil
    @State private var choix: [Int: Set<String>] = [:]
    @State private var autres: [Int: String] = [:]

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Claude te pose une question").font(.subheadline.weight(.semibold))
            ForEach(Array(e.questions.enumerated()), id: \.offset) { qi, q in
                VStack(alignment: .leading, spacing: 6) {
                    if !q.entete.isEmpty { Text(q.entete).font(.caption.weight(.semibold)).foregroundStyle(Color.accentCcs) }
                    Text(q.question).font(.subheadline.weight(.medium))
                    ForEach(Array(q.options.enumerated()), id: \.offset) { _, o in
                        let pris = (choix[qi] ?? []).contains(o.libelle)
                        Button {
                            basculer(qi, q, o.libelle, pris)
                        } label: {
                            HStack(alignment: .top, spacing: 8) {
                                Image(systemName: q.plusieurs ? (pris ? "checkmark.square.fill" : "square") : (pris ? "largecircle.fill.circle" : "circle"))
                                    .foregroundStyle(Color.accentCcs)
                                VStack(alignment: .leading, spacing: 1) {
                                    Text(o.libelle).font(.subheadline.weight(.semibold)).foregroundStyle(.primary)
                                    if !o.description.isEmpty {
                                        Text(o.description).font(.caption).foregroundStyle(.secondary)
                                    }
                                }
                                Spacer(minLength: 0)
                            }
                            .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                    }
                    TextField("Autre réponse (facultatif)", text: Binding<String>(
                        get: { autres[qi] ?? "" }, set: { autres[qi] = $0 }
                    ))
                    .textFieldStyle(.roundedBorder)
                    .font(.footnote)
                    if qi < e.questions.count - 1 { Divider() }
                }
            }
            Button("Répondre") { envoyer() }.buttonStyle(.borderedProminent)
        }
        .padding(12)
        .background(RoundedRectangle(cornerRadius: 12).fill(Color.carte))
        .overlay(RoundedRectangle(cornerRadius: 12).stroke(Color.accentCcs, lineWidth: 2))
    }

    private func basculer(_ qi: Int, _ q: QuestionClaude, _ libelle: String, _ pris: Bool) {
        var avant = choix[qi] ?? []
        if q.plusieurs {
            if pris { avant.remove(libelle) } else { avant.insert(libelle) }
            choix[qi] = avant
        } else {
            choix[qi] = [libelle]
        }
    }

    private func envoyer() {
        var reponses: [String: JSON] = [:]
        for (qi, q) in e.questions.enumerated() {
            let libre = (autres[qi] ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
            let pris = q.options.map { $0.libelle }.filter { (choix[qi] ?? []).contains($0) }
            if !libre.isEmpty {
                reponses[q.question] = .chaine(libre)
            } else if q.plusieurs {
                reponses[q.question] = .de(pris)
            } else {
                reponses[q.question] = .chaine(pris.first ?? "")
            }
        }
        actions.questions(e.cle, reponses)
    }
}

@MainActor
private struct CarteCommande: View {
    let e: ElementFil.Commande
    let actions: ActionsFil

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 6) {
                Image(systemName: "terminal").font(.caption)
                Text("Commande").font(.subheadline.weight(.semibold))
                Text("$ \(e.commande)").font(.system(.caption, design: .monospaced)).lineLimit(2)
                    .frame(maxWidth: .infinity, alignment: .leading)
                Text(etat).font(.caption2)
                    .foregroundStyle((e.code ?? 0) != 0 ? Color.red : Color.secondary)
            }
            if let s = e.sortie { TexteMono(texte: s, lignes: 30, erreur: e.code != 0) }
            if !e.finie, let run = e.runId {
                Button {
                    actions.arreterShell(run)
                } label: {
                    Label("Arrêter", systemImage: "stop.fill")
                }
                .buttonStyle(.bordered)
                .controlSize(.small)
            }
        }
        .padding(10)
        .background(RoundedRectangle(cornerRadius: 10).fill(Color.carte.opacity(0.6)))
        .overlay(RoundedRectangle(cornerRadius: 10).stroke(Color.secondary.opacity(0.25), lineWidth: 1))
    }

    private var etat: String {
        guard let c = e.code else { return "en cours…" }
        return c == 0 ? "terminé" : "code \(c)"
    }
}

@MainActor
private struct CarteArret: View {
    let e: ElementFil.Arrete
    let actions: ActionsFil

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("Ce chat s'est arrêté").font(.subheadline.weight(.semibold))
            Text(e.reprenable
                ? "Le pont a redémarré : Claude n'est plus lancé pour cette conversation."
                : "Le pont a redémarré et on ne retrouve pas sa conversation.")
                .font(.footnote)
            if e.reprenable {
                Button("Reprendre la conversation", action: actions.reprendre).buttonStyle(.borderedProminent)
            }
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 12).fill(Color.avertissement.opacity(0.15)))
    }
}

/// Liste des tâches de Claude, épinglée au-dessus de la saisie (repliable).
@MainActor
struct VueTaches: View {
    let taches: [Tache]
    @State private var ouvert = true

    var body: some View {
        if !taches.isEmpty {
            let faites = taches.filter { $0.statut == "completed" }.count
            let enCours = taches.first { $0.statut == "in_progress" }
            VStack(alignment: .leading, spacing: 2) {
                Button {
                    withAnimation { ouvert.toggle() }
                } label: {
                    HStack {
                        Text("Tâches \(faites)/\(taches.count)").font(.caption.weight(.semibold))
                        Text(enCours.map { " · " + $0.texte } ?? "").font(.caption2).foregroundStyle(.secondary).lineLimit(1)
                        Spacer()
                        Image(systemName: ouvert ? "chevron.down" : "chevron.up").font(.caption)
                    }
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                if ouvert {
                    ScrollView {
                        VStack(alignment: .leading, spacing: 2) {
                            ForEach(Array(taches.enumerated()), id: \.offset) { _, t in
                                Text(marque(t) + " " + t.texte)
                                    .font(.caption)
                                    .foregroundStyle(t.statut == "completed" ? Color.secondary : (t.statut == "in_progress" ? Color.accentCcs : Color.primary))
                                    .frame(maxWidth: .infinity, alignment: .leading)
                            }
                        }
                    }
                    .frame(maxHeight: 140)
                }
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 4)
            .background(Color.carte)
        }
    }

    private func marque(_ t: Tache) -> String {
        switch t.statut {
        case "completed": return "✓"
        case "in_progress": return "▸"
        default: return "○"
        }
    }
}
