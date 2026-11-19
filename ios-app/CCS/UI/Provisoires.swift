import SwiftUI

// Écrans des tâches suivantes de la phase 26, remplacés au fur et à mesure.

struct EcranAccueil: View {
    var body: some View { EcranProvisoire(titre: "Accueil", texte: "Comptes, bascule, pause et bilan de santé.") }
}

struct EcranAnalyse: View {
    var body: some View { EcranProvisoire(titre: "Analyse", texte: "Usage par projet, modèle, compte et heure.") }
}

struct EcranSessions: View {
    var body: some View { EcranProvisoire(titre: "Sessions", texte: "Chats en cours, projets et conversations.") }
}

struct EcranProjet: View {
    let cwd: String
    var body: some View { EcranProvisoire(titre: "Projet", texte: cwd) }
}

struct EcranChat: View {
    let dest: DestChat
    var body: some View { EcranProvisoire(titre: "Chat", texte: dest.cwd) }
}
