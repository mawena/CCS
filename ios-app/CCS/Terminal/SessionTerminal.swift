import SwiftTerm
import UIKit

/**
 * Un terminal du pont (`bridge_term.py`) affiché par l'émulateur SwiftTerm (VT100/xterm, couleurs
 * 256 et 24 bits, écran alternatif, défilement, modes du curseur). La vue de l'émulateur vit avec
 * la session : on peut quitter l'écran et y revenir sans rien perdre. Le texte reçu par
 * `term.output` y est versé ; la saisie et les réponses de l'émulateur partent par `envoyer`.
 */
@MainActor
@Observable
final class SessionTerminal: Identifiable {
    let id: String
    let nom: String
    let cwd: String

    /// Titre donné par le programme (séquence OSC 0/2), sinon le nom.
    private(set) var titre: String
    /// Code de sortie quand le shell s'est arrêté (−1 : le pont ne connaît plus ce terminal).
    private(set) var fin: Int?
    private(set) var colonnes: Int
    private(set) var lignes: Int

    @ObservationIgnored let vue: TerminalView
    @ObservationIgnored private let relais: RelaisTerminal
    @ObservationIgnored var surTaille: ((Int, Int) -> Void)?

    init(id: String, nom: String, cwd: String, colonnes: Int = 80, lignes: Int = 24, envoyer: @escaping (String) -> Void) {
        self.id = id
        self.nom = nom
        self.cwd = cwd
        self.titre = nom
        self.colonnes = colonnes
        self.lignes = lignes
        let v = TerminalView(frame: CGRect(x: 0, y: 0, width: 320, height: 480))
        vue = v
        relais = RelaisTerminal()
        v.terminalDelegate = relais
        // la barre de touches est celle de l'écran (au-dessus du clavier, comme sur Android)
        v.inputAccessoryView = nil
        v.nativeBackgroundColor = UIColor(red: 0x1E / 255.0, green: 0x1E / 255.0, blue: 0x22 / 255.0, alpha: 1)
        v.nativeForegroundColor = UIColor(red: 0xF2 / 255.0, green: 0xF2 / 255.0, blue: 0xF5 / 255.0, alpha: 1)
        v.caretColor = v.nativeForegroundColor
        v.font = UIFont.monospacedSystemFont(ofSize: CGFloat(Prefs.tailleTerminal), weight: .regular)
        relais.envoyer = { [weak self] d in
            guard let s = self, s.fin == nil, !d.isEmpty else { return }
            envoyer(d)
        }
        relais.titre = { [weak self] t in
            guard let s = self else { return }
            s.titre = t.trimmingCharacters(in: .whitespaces).isEmpty ? s.nom : t
        }
        relais.taille = { [weak self] c, l in
            guard let s = self, c > 0, l > 0, c != s.colonnes || l != s.lignes else { return }
            s.colonnes = c
            s.lignes = l
            s.surTaille?(c, l)
        }
    }

    /// Texte reçu du pont.
    func recevoir(_ texte: String) {
        if texte.isEmpty { return }
        vue.feed(text: texte)
    }

    /// Rattachement : écran remis à neuf (RIS), puis la fin de la sortie gardée par le pont.
    func remplacer(_ texte: String) {
        vue.feed(text: "\u{1B}c")
        recevoir(texte)
    }

    func terminer(_ code: Int) {
        if fin != nil { return }
        recevoir(Touches.messageFin(code))
        fin = code
        vue.resignFirstResponder()
    }

    /// Collage : entre crochets si le programme l'a demandé (mode 2004), comme un vrai terminal.
    func coller() {
        if fin == nil { vue.paste(nil) }
    }

    /// Envoie une séquence de la barre de touches (Échap, flèches…).
    func taper(_ sequence: String) {
        if fin == nil { vue.send(txt: sequence) }
    }

    /// Flèche de la barre, avec Ctrl et Alt collants (puis relâchés).
    func fleche(_ f: Touches.Fleche) {
        let seq = f.sequence(application: vue.getTerminal().applicationCursor, ctrl: vue.controlModifier, alt: vue.metaModifier)
        vue.controlModifier = false
        vue.metaModifier = false
        taper(seq)
    }

    /// Tout le texte (historique et écran), pour « Copier ».
    func texte() -> String {
        let d = vue.getTerminal().getBufferAsData(kind: .normal)
        return String(decoding: d, as: UTF8.self)
    }

    func changerTaille(_ points: Int) {
        vue.font = UIFont.monospacedSystemFont(ofSize: CGFloat(points), weight: .regular)
    }
}

/**
 * Délégué de SwiftTerm (protocole sans acteur) : relaie vers la session, sur le fil principal où
 * SwiftTerm l'appelle.
 */
final class RelaisTerminal: TerminalViewDelegate {
    var envoyer: (@MainActor (String) -> Void)?
    var titre: (@MainActor (String) -> Void)?
    var taille: (@MainActor (Int, Int) -> Void)?

    private func principal(_ f: @escaping @MainActor () -> Void) {
        if Thread.isMainThread { MainActor.assumeIsolated { f() } } else { Task { @MainActor in f() } }
    }

    func send(source: TerminalView, data: ArraySlice<UInt8>) {
        let t = String(decoding: Array(data), as: UTF8.self)
        principal { [weak self] in self?.envoyer?(t) }
    }

    func sizeChanged(source: TerminalView, newCols: Int, newRows: Int) {
        principal { [weak self] in self?.taille?(newCols, newRows) }
    }

    func setTerminalTitle(source: TerminalView, title: String) {
        principal { [weak self] in self?.titre?(title) }
    }

    func clipboardCopy(source: TerminalView, content: Data) {
        let t = String(decoding: content, as: UTF8.self)
        principal { UIPasteboard.general.string = t }
    }

    func requestOpenLink(source: TerminalView, link: String, params: [String: String]) {
        guard let u = URL(string: link), u.scheme == "https" || u.scheme == "http" else { return }
        principal { UIApplication.shared.open(u) }
    }

    func bell(source: TerminalView) {
        principal { UIImpactFeedbackGenerator(style: .light).impactOccurred() }
    }

    func hostCurrentDirectoryUpdate(source: TerminalView, directory: String?) {}
    func scrolled(source: TerminalView, position: Double) {}
    func iTermContent(source: TerminalView, content: ArraySlice<UInt8>) {}
    func rangeChanged(source: TerminalView, startY: Int, endY: Int) {}
}
