import SwiftUI

/**
 * Questions posées depuis une action (`Demandes` de l'appli Android) : confirmation et saisie
 * d'un nom, attendues avec `await` au milieu du code de l'action. Les alertes sont montrées par
 * `.demandes(d)` posé sur l'écran.
 */
@MainActor
@Observable
final class Demandes {
    struct Confirmation: Identifiable {
        let id = UUID()
        let titre: String
        let texte: String
        let bouton: String
        let danger: Bool
    }

    struct Nom: Identifiable {
        let id = UUID()
        let titre: String
        let bouton: String
        let message: String?
    }

    var confirmation: Confirmation? = nil
    var nom: Nom? = nil
    var saisie = ""

    @ObservationIgnored private var suiteConfirmer: CheckedContinuation<Bool, Never>? = nil
    @ObservationIgnored private var suiteNom: CheckedContinuation<String?, Never>? = nil

    func confirmer(_ titre: String, _ texte: String, _ bouton: String, danger: Bool = false) async -> Bool {
        repondre(false)
        return await withCheckedContinuation { (s: CheckedContinuation<Bool, Never>) in
            suiteConfirmer = s
            confirmation = Confirmation(titre: titre, texte: texte, bouton: bouton, danger: danger)
        }
    }

    func repondre(_ oui: Bool) {
        let s = suiteConfirmer
        suiteConfirmer = nil
        confirmation = nil
        s?.resume(returning: oui)
    }

    /// Nom saisi (vérifié par `verifier` : message d'erreur ou nil), ou nil si on annule.
    func nom(_ titre: String, initial: String = "", bouton: String = "OK", verifier: (String) -> String? = { _ in nil }) async -> String? {
        var message: String? = nil
        var valeur = initial
        while true {
            let r = await demanderNom(titre, valeur, bouton, message)
            guard let t = r?.trimmingCharacters(in: .whitespacesAndNewlines) else { return nil }
            if let e = verifier(t) {
                message = e
                valeur = t
                try? await Task.sleep(nanoseconds: 350_000_000)      // l'alerte précédente se referme
                continue
            }
            return t
        }
    }

    private func demanderNom(_ titre: String, _ initial: String, _ bouton: String, _ message: String?) async -> String? {
        validerNom(nil)
        return await withCheckedContinuation { (s: CheckedContinuation<String?, Never>) in
            suiteNom = s
            saisie = initial
            nom = Nom(titre: titre, bouton: bouton, message: message)
        }
    }

    func validerNom(_ texte: String?) {
        let s = suiteNom
        suiteNom = nil
        nom = nil
        s?.resume(returning: texte)
    }
}

private struct VueDemandes: ViewModifier {
    @Bindable var d: Demandes

    func body(content: Content) -> some View {
        content
            .alert(
                d.confirmation?.titre ?? "",
                isPresented: Binding<Bool>(get: { d.confirmation != nil }, set: { if !$0 { d.repondre(false) } }),
                presenting: d.confirmation
            ) { c in
                Button(c.bouton, role: c.danger ? .destructive : nil) { d.repondre(true) }
                Button("Annuler", role: .cancel) { d.repondre(false) }
            } message: { c in
                Text(c.texte)
            }
            .alert(
                d.nom?.titre ?? "",
                isPresented: Binding<Bool>(get: { d.nom != nil }, set: { if !$0 { d.validerNom(nil) } }),
                presenting: d.nom
            ) { n in
                TextField("Nom", text: $d.saisie)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                Button(n.bouton) { d.validerNom(d.saisie) }
                Button("Annuler", role: .cancel) { d.validerNom(nil) }
            } message: { n in
                if let m = n.message { Text(m) }
            }
    }
}

extension View {
    /// Montre les confirmations et saisies demandées par `d`.
    func demandes(_ d: Demandes) -> some View {
        return modifier(VueDemandes(d: d))
    }
}
