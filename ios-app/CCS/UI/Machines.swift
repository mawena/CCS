import SwiftUI

/// Bandeau d'accent, sur tous les écrans, tant qu'on pilote une autre machine que ce serveur.
@MainActor
struct BandeauMachine: View {
    @Environment(ModeleAppli.self) private var modele

    var body: some View {
        if !modele.client.machine.isEmpty {
            HStack(spacing: 10) {
                Image(systemName: "desktopcomputer").font(.subheadline)
                Text("Machine pilotée : \(modele.client.nomMachine)")
                    .font(.subheadline.weight(.semibold))
                    .lineLimit(1)
                    .frame(maxWidth: .infinity, alignment: .leading)
                Button("Changer") { modele.choixMachine = true }.font(.subheadline)
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 6)
            .background(Color.purple.opacity(0.18))
        }
    }
}

/// Bouton « machine » de la barre des Sessions : ouvre la feuille de choix.
@MainActor
struct BoutonMachine: View {
    @Environment(ModeleAppli.self) private var modele

    var body: some View {
        if modele.choixMachinePossible {
            Button {
                modele.choixMachine = true
            } label: {
                Label(modele.client.nomMachine, systemImage: modele.client.machine.isEmpty ? "cloud" : "desktopcomputer")
                    .labelStyle(.titleAndIcon)
                    .font(.subheadline)
                    .lineLimit(1)
            }
            .tint(modele.client.machine.isEmpty ? Color.accentCcs : Color.purple)
            .accessibilityLabel("Machine pilotée : \(modele.client.nomMachine)")
        }
    }
}

/// Feuille « Machine pilotée » : ce serveur, puis les autres machines (comme `machineSheet` du web).
@MainActor
struct FeuilleMachines: View {
    @Environment(ModeleAppli.self) private var modele
    @Environment(\.dismiss) private var fermer
    @State private var cherche = true
    @State private var message: String? = nil

    var body: some View {
        NavigationStack {
            List {
                Section {
                    ligne(nom: CcsClient.ceServeur, detail: "le VPS, toujours là", icone: "cloud",
                          courante: modele.client.machine.isEmpty, active: true) {
                        choisir("", "")
                    }
                    ForEach(modele.machines) { m in
                        ligne(nom: m.nom, detail: m.description, icone: "desktopcomputer",
                              courante: m.id == modele.client.machine, active: m.choisissable) {
                            choisir(m.id, m.nom)
                        }
                    }
                } footer: {
                    Text(pied)
                }
            }
            .navigationTitle("Machine pilotée")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Fermer") { fermer() } }
            }
            .refreshable { await lire() }
            .task { await lire() }
        }
        .presentationDetents([.medium, .large])
    }

    private var pied: String {
        if cherche && modele.machines.isEmpty { return "Recherche des machines…" }
        if let m = message, !m.isEmpty { return m }
        if !modele.machines.isEmpty { return "Le PC doit être allumé, avec CCS installé. Tout l'appli suit la machine choisie, notifications comprises." }
        return "Aucune autre machine sur le relais Ricochet."
    }

    private func lire() async {
        message = await modele.rafraichirMachines()
        cherche = false
    }

    private func choisir(_ id: String, _ nom: String) {
        fermer()
        modele.choisirMachine(id, nom: nom)
    }

    private func ligne(nom: String, detail: String, icone: String, courante: Bool, active: Bool, choisir: @escaping () -> Void) -> some View {
        Button(action: choisir) {
            HStack(spacing: 12) {
                Image(systemName: icone).frame(width: 26)
                VStack(alignment: .leading, spacing: 2) {
                    Text(nom).fontWeight(courante ? .semibold : .regular)
                    Text(detail).font(.footnote).foregroundStyle(.secondary)
                }
                Spacer()
                if courante {
                    Image(systemName: "checkmark").foregroundStyle(Color.accentCcs)
                        .accessibilityLabel("Machine actuelle")
                }
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .disabled(!active || courante)
        .opacity(active || courante ? 1 : 0.5)
    }
}
