import SwiftUI
import UIKit

/// Taille du texte du fil (un peu plus petit que le corps d'iOS, comme `bodyMedium` d'Android).
let tailleTexteChat: CGFloat = 16

/**
 * Segments en ligne (gras, italique, code, barré, liens touchables) en texte attribué. Avec
 * `liens`, les chemins de fichiers du projet (en code ou dans le texte) deviennent des liens
 * `ccs-fichier:` que l'écran du chat ouvre.
 */
func annoter(_ segments: [Markdown.Segment], taille: CGFloat = tailleTexteChat, gras: Bool = false, liens: LiensFichiers? = nil) -> AttributedString {
    var r = AttributedString()
    for s in segments {
        func morceau(_ t: String) -> AttributedString {
            var a = AttributedString(t)
            var police: Font = s.code ? Font.system(size: taille - 1, design: .monospaced) : Font.system(size: taille)
            if s.gras || gras { police = police.bold() }
            if s.italique { police = police.italic() }
            a.font = police
            if s.barre { a.strikethroughStyle = Text.LineStyle.single }
            if s.code { a.backgroundColor = Color.fondCode }
            return a
        }
        func lie(_ a: AttributedString, _ u: URL?) -> AttributedString {
            guard let u = u else { return a }
            var b = a
            b.link = u
            b.foregroundColor = Color.accentCcs
            b.underlineStyle = Text.LineStyle.single
            return b
        }
        // image hors paragraphe (tableau, titre) : son texte, ou son adresse, en lien
        if s.image, let l = s.lien {
            let t = s.texte.isEmpty ? l : s.texte
            if let u = URL(string: l), let schema = u.scheme?.lowercased(), ["http", "https"].contains(schema) {
                r.append(lie(morceau(t), u))
            } else {
                r.append(morceau(t))
            }
            continue
        }
        if let l = s.lien, let u = URL(string: l), let schema = u.scheme?.lowercased(), ["http", "https", "mailto"].contains(schema) {
            r.append(lie(morceau(s.texte), u))
            continue
        }
        if let lf = liens, s.lien == nil {
            if s.code {
                if let ref = lf.ref(s.texte) {
                    r.append(lie(morceau(s.texte), lf.lien(ref)))
                    continue
                }
            } else {
                let refs = lf.trouver(s.texte)
                if !refs.isEmpty {
                    let n = s.texte as NSString
                    var pos = 0
                    for ref in refs where ref.debut >= pos {
                        if ref.debut > pos { r.append(morceau(n.substring(with: NSRange(location: pos, length: ref.debut - pos)))) }
                        r.append(lie(morceau(ref.texte), lf.lien(ref)))
                        pos = ref.debut + (ref.texte as NSString).length
                    }
                    if pos < n.length { r.append(morceau(n.substring(from: pos))) }
                    continue
                }
            }
        }
        r.append(morceau(s.texte))
    }
    return r
}

/// Fichiers du projet du chat affiché, pour les liens des chemins cités (nil : pas de liens).
private struct CleLiensFichiers: EnvironmentKey {
    static let defaultValue: LiensFichiers? = nil
}

extension EnvironmentValues {
    var liensFichiers: LiensFichiers? {
        get { return self[CleLiensFichiers.self] }
        set { self[CleLiensFichiers.self] = newValue }
    }
}

/// Réponse de Claude rendue en blocs Markdown.
@MainActor
struct MarkdownVue: View {
    let texte: String

    var body: some View {
        let blocs = Markdown.analyser(texte)
        VStack(alignment: .leading, spacing: 6) {
            ForEach(Array(blocs.enumerated()), id: \.offset) { _, b in
                BlocVue(bloc: b)
            }
        }
    }
}

@MainActor
private struct BlocVue: View {
    @Environment(\.liensFichiers) private var liens
    let bloc: Markdown.Bloc

    var body: some View {
        switch bloc {
        case .paragraphe(let contenu):
            EnLigneRiche(contenu: contenu)
        case .titre(let niveau, let contenu):
            Text(annoter(contenu, taille: niveau == 1 ? 21 : (niveau == 2 ? 19 : 17), gras: true, liens: liens))
                .padding(.top, 4)
                .fixedSize(horizontal: false, vertical: true)
        case .liste(let elements):
            VStack(alignment: .leading, spacing: 2) {
                ForEach(Array(elements.enumerated()), id: \.offset) { _, e in
                    HStack(alignment: .firstTextBaseline, spacing: 4) {
                        Text(marque(e))
                            .font(.system(size: tailleTexteChat))
                            .foregroundStyle(.secondary)
                            .frame(minWidth: e.marque.count > 2 ? 26 : 16, alignment: .leading)
                        EnLigneRiche(contenu: e.contenu)
                    }
                    .padding(.leading, CGFloat(e.niveau * 16))
                }
            }
        case .code(let langue, let texte):
            if langue.lowercased() == "ccs", let c = Riche.bloc(texte) {
                ComposantRiche(composant: c)
            } else {
                BlocCode(code: texte, langue: langue)
            }
        case .citation(let blocs):
            HStack(alignment: .top, spacing: 10) {
                RoundedRectangle(cornerRadius: 2).fill(Color.secondary.opacity(0.5)).frame(width: 3)
                // vue récursive : AnyView coupe le type opaque qui se contiendrait lui-même
                AnyView(
                    VStack(alignment: .leading, spacing: 4) {
                        ForEach(Array(blocs.enumerated()), id: \.offset) { _, b in BlocVue(bloc: b) }
                    }
                    .foregroundStyle(.secondary)
                )
            }
            .padding(.vertical, 2)
        case .tableau(let entetes, let lignes):
            VueTableau(entetes: entetes, lignes: lignes)
        case .regle:
            Divider().padding(.vertical, 4)
        }
    }

    private func marque(_ e: Markdown.Element) -> String {
        switch e.coche {
        case .some(true): return "☑"
        case .some(false): return "☐"
        case .none: return e.marque
        }
    }
}

/**
 * Texte en ligne d'un paragraphe ou d'un élément de liste : les images en sont retirées et
 * s'affichent dessous, avec un lecteur pour chaque son ou vidéo cité (lien, `code`, chemin).
 */
@MainActor
private struct EnLigneRiche: View {
    @Environment(\.liensFichiers) private var liens
    let contenu: [Markdown.Segment]

    var body: some View {
        let texte = contenu.filter { !$0.image }
        let medias = Riche.medias(contenu, liens: liens)
        if medias.isEmpty {
            Text(annoter(texte, liens: liens)).fixedSize(horizontal: false, vertical: true)
        } else {
            VStack(alignment: .leading, spacing: 6) {
                if !texte.allSatisfy({ $0.texte.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }) {
                    Text(annoter(texte, liens: liens)).fixedSize(horizontal: false, vertical: true)
                }
                MediasEnLigne(medias: medias)
            }
        }
    }
}

/// Bloc de code : langue, bouton Copier, défilement horizontal.
@MainActor
struct BlocCode: View {
    @Environment(ModeleAppli.self) private var modele
    let code: String
    let langue: String

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack {
                Text(langue.isEmpty ? "code" : langue).font(.caption2).foregroundStyle(.secondary)
                Spacer()
                Button {
                    copier(code)
                    modele.avis.dire("Code copié.")
                } label: {
                    Image(systemName: "doc.on.doc").font(.caption)
                }
                .buttonStyle(.borderless)
                .accessibilityLabel("Copier le code")
            }
            .padding(.horizontal, 10)
            .padding(.top, 6)
            ScrollView(.horizontal, showsIndicators: false) {
                Text(code)
                    .font(.system(size: 13, design: .monospaced))
                    .textSelection(.enabled)
                    .fixedSize(horizontal: true, vertical: true)
                    .padding(10)
            }
        }
        .background(RoundedRectangle(cornerRadius: 8).fill(Color.fondCode))
    }
}

@MainActor
private struct VueTableau: View {
    @Environment(\.liensFichiers) private var liens
    let entetes: [[Markdown.Segment]]
    let lignes: [[[Markdown.Segment]]]

    var body: some View {
        let n = max(entetes.count, lignes.map { $0.count }.max() ?? 0)
        ScrollView(.horizontal, showsIndicators: false) {
            Grid(alignment: .leading, horizontalSpacing: 12, verticalSpacing: 6) {
                GridRow {
                    ForEach(0..<n, id: \.self) { k in
                        Text(annoter(k < entetes.count ? entetes[k] : [], taille: 14, gras: true, liens: liens))
                    }
                }
                Divider()
                ForEach(Array(lignes.enumerated()), id: \.offset) { _, rang in
                    GridRow {
                        ForEach(0..<n, id: \.self) { k in
                            Text(annoter(k < rang.count ? rang[k] : [], taille: 14, liens: liens))
                                .frame(maxWidth: 260, alignment: .leading)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                    }
                }
            }
            .padding(8)
        }
        .background(RoundedRectangle(cornerRadius: 6).fill(Color.fondCode.opacity(0.6)))
    }
}
