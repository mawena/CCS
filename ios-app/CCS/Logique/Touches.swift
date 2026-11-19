import Foundation

/**
 * Barre de touches du terminal (`web/terminal.js`) : séquences envoyées au programme. Ctrl et Alt
 * collants sont ceux de l'émulateur (SwiftTerm les applique au caractère suivant tapé au clavier) ;
 * pour les flèches de la barre, ils deviennent un modificateur xterm (`ESC [1;5D` pour Ctrl+←).
 */
enum Touches {
    static let echap = "\u{1B}"
    static let tab = "\t"

    /// Flèches de la barre ; elles suivent le mode « curseur application » (vim, less…).
    enum Fleche: CaseIterable {
        case gauche, bas, haut, droite

        var libelle: String {
            switch self {
            case .gauche: return "←"
            case .bas: return "↓"
            case .haut: return "↑"
            case .droite: return "→"
            }
        }

        var lettre: String {
            switch self {
            case .gauche: return "D"
            case .bas: return "B"
            case .haut: return "A"
            case .droite: return "C"
            }
        }

        func sequence(application: Bool, ctrl: Bool = false, alt: Bool = false) -> String {
            let mod = 1 + (alt ? 2 : 0) + (ctrl ? 4 : 0)
            if mod > 1 { return "\u{1B}[1;\(mod)\(lettre)" }
            return application ? "\u{1B}O\(lettre)" : "\u{1B}[\(lettre)"
        }
    }

    static let debut = "\u{1B}[H"
    static let fin = "\u{1B}[F"
    static let pagePrecedente = "\u{1B}[5~"
    static let pageSuivante = "\u{1B}[6~"

    /// Symboles difficiles à taper au clavier du téléphone.
    static let symboles = ["|", "~", "/", "-", "_", "*", "&", "$", ">", "<"]

    /// Taille du texte du terminal, en points.
    static let tailleMin = 8
    static let tailleMax = 24
    static let tailleDefaut = 13

    static func borner(_ t: Int) -> Int { return min(tailleMax, max(tailleMin, t)) }

    /// Message affiché à la fin du shell (code −1 : le pont ne connaît plus ce terminal).
    static func messageFin(_ code: Int) -> String {
        return code < 0 ? "\r\n[terminal fermé]\r\n" : "\r\n[terminé, code \(code)]\r\n"
    }
}
