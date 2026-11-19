import SwiftUI

// Écrans des tâches suivantes de la phase 26, remplacés au fur et à mesure.

@MainActor
struct EcranChat: View {
    let dest: DestChat
    var body: some View { EcranProvisoire(titre: "Chat", texte: dest.cwd) }
}
