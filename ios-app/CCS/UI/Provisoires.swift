import SwiftUI

// Écrans des tâches suivantes de la phase 26, remplacés au fur et à mesure.

@MainActor
struct EcranSessions: View {
    var body: some View { EcranProvisoire(titre: "Sessions", texte: "Chats en cours, projets et conversations.") }
}

@MainActor
struct EcranProjet: View {
    let cwd: String
    var body: some View { EcranProvisoire(titre: "Projet", texte: cwd) }
}

@MainActor
struct EcranChat: View {
    let dest: DestChat
    var body: some View { EcranProvisoire(titre: "Chat", texte: dest.cwd) }
}
