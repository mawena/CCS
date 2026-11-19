import SwiftUI
import UIKit

/// Texte sélectionnable (UITextView) : on y choisit le passage à citer.
@MainActor
private struct TexteSelectionnable: UIViewRepresentable {
    let texte: String
    @Binding var selection: String

    func makeCoordinator() -> Coordinateur { return Coordinateur(selection: $selection) }

    func makeUIView(context: Context) -> UITextView {
        let v = UITextView()
        v.isEditable = false
        v.isSelectable = true
        v.font = UIFont.preferredFont(forTextStyle: .body)
        v.adjustsFontForContentSizeCategory = true
        v.backgroundColor = .clear
        v.textContainerInset = UIEdgeInsets(top: 8, left: 4, bottom: 8, right: 4)
        v.delegate = context.coordinator
        v.text = texte
        return v
    }

    func updateUIView(_ v: UITextView, context: Context) {
        if v.text != texte { v.text = texte }
    }

    @MainActor
    final class Coordinateur: NSObject, UITextViewDelegate {
        var selection: Binding<String>

        init(selection: Binding<String>) { self.selection = selection }

        func textViewDidChangeSelection(_ textView: UITextView) {
            let r = textView.selectedRange
            let ns = (textView.text ?? "") as NSString
            if r.location != NSNotFound && r.length > 0 && r.location + r.length <= ns.length {
                selection.wrappedValue = ns.substring(with: r)
            } else {
                selection.wrappedValue = ""
            }
        }
    }
}

/// « Citer un passage… » : on sélectionne une partie du message, puis « Citer ».
@MainActor
struct DialoguePassage: View {
    let m: MessageChoisi
    let citer: (Citation.Cite) -> Void
    @Environment(\.dismiss) private var fermer
    @State private var selection = ""

    var body: some View {
        NavigationStack {
            VStack(alignment: .leading, spacing: 6) {
                Text("Sélectionne le passage à citer.").font(.footnote).foregroundStyle(.secondary).padding(.horizontal)
                TexteSelectionnable(texte: m.texte, selection: $selection)
                    .padding(.horizontal, 8)
            }
            .navigationTitle("Citer un passage")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Annuler") { fermer() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button(selection.isEmpty ? "Tout citer" : "Citer") {
                        let t = selection.isEmpty ? m.texte : String(selection.prefix(Citation.maxSelection))
                        let propre = t.trimmingCharacters(in: .whitespacesAndNewlines)
                        if !propre.isEmpty {
                            citer(Citation.Cite(auteur: m.auteur, texte: selection.isEmpty ? Citation.extrait(propre) : propre))
                        }
                        fermer()
                    }
                }
            }
        }
    }
}

/// Étiquettes d'un message : celles qu'il a (retirables), une saisie (séparées par des virgules), des suggestions.
@MainActor
struct DialogueEtiquettes: View {
    let m: MessageChoisi
    let actuelles: [String]
    let connues: [String]
    let valider: ([String]) -> Void
    @Environment(\.dismiss) private var fermer
    @State private var liste: [String] = []
    @State private var saisie = ""
    @State private var lu = false

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    Text(Citation.uneLigne(m.texte)).font(.footnote).foregroundStyle(.secondary).lineLimit(3)
                }
                Section("Étiquettes") {
                    if liste.isEmpty {
                        Text("Aucune étiquette.").foregroundStyle(.secondary)
                    }
                    ForEach(liste, id: \.self) { e in
                        HStack {
                            Label(e, systemImage: "tag")
                            Spacer()
                            Button {
                                liste.removeAll { $0 == e }
                            } label: {
                                Image(systemName: "minus.circle.fill").foregroundStyle(.red)
                            }
                            .buttonStyle(.borderless)
                            .accessibilityLabel("Retirer \(e)")
                        }
                    }
                    HStack {
                        TextField("Nouvelle étiquette", text: $saisie)
                            .textInputAutocapitalization(.never)
                            .autocorrectionDisabled()
                            .onSubmit { ajouter() }
                        Button("Ajouter") { ajouter() }
                            .disabled(Etiquettes.lire(saisie).isEmpty)
                    }
                }
                if !suggestions.isEmpty {
                    Section("Suggestions") {
                        ForEach(suggestions, id: \.self) { e in
                            Button {
                                liste = Etiquettes.nettoyer(liste + [e])
                            } label: {
                                Label(e, systemImage: "plus")
                            }
                        }
                    }
                }
            }
            .navigationTitle("Étiqueter")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Annuler") { fermer() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Enregistrer") {
                        let finale = Etiquettes.nettoyer(liste + Etiquettes.lire(saisie))
                        valider(finale)
                        fermer()
                    }
                }
            }
        }
        .onAppear {
            if !lu {
                liste = actuelles
                lu = true
            }
        }
    }

    /// Étiquettes déjà utilisées dans la session, filtrées par la saisie.
    private var suggestions: [String] {
        let f = Recherche.plier(saisie.trimmingCharacters(in: .whitespaces))
        return connues.filter { c in
            !liste.contains(c) && (f.isEmpty || Recherche.plier(c).contains(f))
        }.prefix(12).map { $0 }
    }

    private func ajouter() {
        let neuves = Etiquettes.lire(saisie)
        guard !neuves.isEmpty else { return }
        liste = Etiquettes.nettoyer(liste + neuves)
        saisie = ""
    }
}

/// Volet des étiquettes de la session : messages regroupés par étiquette ; toucher un message le montre dans le fil.
@MainActor
struct FeuilleEtiquettes: View {
    let etiquettes: [String: EntreeEtiquettes]
    let filtre: String?
    let montrer: (String) -> Void
    @Environment(\.dismiss) private var fermer
    @State private var choisie: String? = nil
    @State private var lu = false

    var body: some View {
        let groupes = Etiquettes.parEtiquette(etiquettes)
        let montres = groupes.filter { choisie == nil || $0.etiquette == choisie }
        NavigationStack {
            List {
                if groupes.isEmpty {
                    Text("Aucun message étiqueté dans cette session. Appuie longuement sur un message pour l'étiqueter.")
                        .foregroundStyle(.secondary)
                }
                if groupes.count > 1 {
                    ScrollView(.horizontal, showsIndicators: false) {
                        HStack(spacing: 6) {
                            Puce(texte: "Toutes", pris: choisie == nil) { choisie = nil }
                            ForEach(groupes.map { $0.etiquette }, id: \.self) { e in
                                Puce(texte: e, pris: choisie == e) { choisie = e }
                            }
                        }
                    }
                    .listRowInsets(EdgeInsets(top: 6, leading: 12, bottom: 6, trailing: 12))
                }
                ForEach(montres.map { $0.etiquette }, id: \.self) { e in
                    Section(e) {
                        ForEach(messages(de: e, dans: montres), id: \.self) { id in
                            Button {
                                montrer(id)
                                fermer()
                            } label: {
                                LigneEtiquetee(entree: etiquettes[id])
                            }
                        }
                    }
                }
            }
            .navigationTitle("Étiquettes")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("OK") { fermer() }
                }
            }
        }
        .onAppear {
            if !lu {
                choisie = filtre
                lu = true
            }
        }
    }

    private func messages(de e: String, dans g: [(etiquette: String, messages: [(id: String, entree: EntreeEtiquettes)])]) -> [String] {
        for x in g where x.etiquette == e {
            return x.messages.map { $0.id }
        }
        return []
    }
}

@MainActor
private struct LigneEtiquetee: View {
    let entree: EntreeEtiquettes?

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(auteur).font(.caption.weight(.semibold)).foregroundStyle(Color.accentCcs)
            Text((entree?.extrait ?? "").isEmpty ? "(message)" : (entree?.extrait ?? ""))
                .font(.subheadline).foregroundStyle(.primary).lineLimit(3)
            if let ts = entree?.ts, ts > 0 {
                Text(Format.ilYA(ts)).font(.caption2).foregroundStyle(.secondary)
            }
        }
    }

    private var auteur: String {
        switch Format.role(entree?.role ?? "") {
        case .some(.toi): return "Toi"
        case .some(.claude): return "Claude"
        case .none: return "Message"
        }
    }
}

@MainActor
private struct Puce: View {
    let texte: String
    let pris: Bool
    let faire: () -> Void

    var body: some View {
        Button(action: faire) {
            Text(texte).font(.caption)
        }
        .buttonStyle(.bordered)
        .tint(pris ? Color.accentCcs : Color.secondary)
        .controlSize(.small)
    }
}
