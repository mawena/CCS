import SwiftUI
import UniformTypeIdentifiers

/**
 * Volet Fichiers (`web/files.js`, `files-manage.js`) : un dossier à la fois sous `base` (ligne
 * « Dossier parent »), marques git, recherche par nom, créer, envoyer depuis l'appli Fichiers
 * d'iOS, enregistrer, partager, renommer, supprimer (confirmé), copier / couper / coller.
 * `protege` : dossier à ne jamais renommer ni supprimer d'ici (le projet), passé au pont en `root`.
 */
@MainActor
struct PanneauFichiers: View {
    @Environment(ModeleAppli.self) private var modele
    @Environment(\.naviguer) private var naviguer
    let base: String
    var home: String = ""
    var protege: String?
    var entete: AnyView? = nil

    @State private var dossier: String
    @State private var liste: ListeFichiers? = nil
    @State private var erreur: String? = nil
    @State private var recherche: String? = nil
    @State private var trouves: ListeFichiers? = nil
    @State private var travail: String? = nil
    @State private var progres: Double? = nil
    @State private var choisir = false
    @State private var local: FichierLocal? = nil
    @State private var demandes = Demandes()
    private var presse: Presse { return Presse.partage }

    /// `proteger` : le dossier de base (le projet) ne peut être ni renommé ni supprimé d'ici.
    init(base: String, home: String = "", proteger: Bool = true, entete: AnyView? = nil) {
        self.base = base
        self.home = home
        self.protege = proteger ? base : nil
        self.entete = entete
        _dossier = State(initialValue: base)
    }

    private var client: CcsClient { return modele.client }
    private var requete: String { return recherche?.trimmingCharacters(in: .whitespaces) ?? "" }

    var body: some View {
        VStack(spacing: 0) {
            if let e = entete { e }
            barre
            if recherche != nil {
                TextField("Chercher par nom dans \(Fichiers.nom(dossier))", text: Binding<String>(
                    get: { recherche ?? "" }, set: { recherche = $0 }
                ))
                .textFieldStyle(.roundedBorder)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .padding(.horizontal, 12)
                .padding(.vertical, 4)
            }
            if let t = travail { BandeauTravail(texte: t, progres: progres) }
            Divider()
            if requete.isEmpty { contenu } else { resultats }
        }
        .onChange(of: dossier) { _, _ in
            liste = nil
            erreur = nil
        }
        .task(id: "\(client.etat.estConnecte)|\(dossier)") {
            guard client.etat.estConnecte else { return }
            await charger()
        }
        .task(id: "\(requete)|\(dossier)|\(client.etat.estConnecte)") {
            trouves = nil
            let q = requete
            guard !q.isEmpty, client.etat.estConnecte else { return }
            try? await Task.sleep(nanoseconds: 300_000_000)
            if Task.isCancelled { return }
            do {
                trouves = try await client.appeler("files.search", ["root": .chaine(dossier), "query": .chaine(q)], en: ListeFichiers.self)
            } catch {
                modele.avis.dire(texteErreur(error))
                trouves = ListeFichiers(json: .vide)
            }
        }
        .fileImporter(isPresented: $choisir, allowedContentTypes: [.item], allowsMultipleSelection: true) { r in
            if case .success(let urls) = r, !urls.isEmpty { envoyer(urls, dans: dossier) }
        }
        .presenterFichier($local)
        .demandes(demandes)
    }

    // MARK: barre du dossier

    private var barre: some View {
        HStack(spacing: 4) {
            ScrollViewReader { lecteur in
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 2) {
                        let fil = Fichiers.ariane(dossier, base, home)
                        ForEach(Array(fil.enumerated()), id: \.offset) { i, p in
                            if i > 0 { Image(systemName: "chevron.right").font(.caption2).foregroundStyle(.secondary) }
                            if i == fil.count - 1 {
                                Text(p.nom).font(.subheadline.weight(.semibold)).lineLimit(1).padding(.horizontal, 6).id("fin")
                            } else {
                                Button(i == 0 && p.nom.count > 24 ? Fichiers.nom(p.nom) : p.nom) { dossier = p.chemin }
                                    .font(.subheadline).lineLimit(1).padding(.horizontal, 4)
                            }
                        }
                    }
                    .padding(.leading, 12)
                }
                .onChange(of: dossier) { _, _ in lecteur.scrollTo("fin", anchor: .trailing) }
                .onAppear { lecteur.scrollTo("fin", anchor: .trailing) }
            }
            Button {
                recherche = recherche == nil ? "" : nil
            } label: {
                Image(systemName: recherche == nil ? "magnifyingglass" : "xmark")
            }
            .accessibilityLabel("Chercher un fichier")
            .padding(.horizontal, 6)
            Menu {
                actionsDossier(dossier, courant: true)
            } label: {
                Image(systemName: "ellipsis.circle")
            }
            .accessibilityLabel("Actions sur ce dossier")
            .padding(.trailing, 12)
        }
        .frame(height: 40)
    }

    @ViewBuilder
    private func actionsDossier(_ cible: String, courant: Bool) -> some View {
        Button { creer(cible, dossier: false) } label: { Label("Nouveau fichier", systemImage: "doc.badge.plus") }
        Button { creer(cible, dossier: true) } label: { Label("Nouveau dossier", systemImage: "folder.badge.plus") }
        if courant {
            Button { choisir = true } label: { Label("Envoyer des fichiers ici", systemImage: "square.and.arrow.up") }
        }
        if let t = presse.tenu {
            Button { coller(cible) } label: { Label("Coller « \(t.nom) »", systemImage: "doc.on.clipboard") }
        }
        Button { ajouterProjet(cible) } label: { Label("Ajouter aux projets", systemImage: "text.badge.plus") }
        if courant {
            Button { Task { await charger() } } label: { Label("Actualiser", systemImage: "arrow.clockwise") }
        }
    }

    // MARK: liste

    @ViewBuilder
    private var contenu: some View {
        List {
            if dossier != base && Fichiers.sous(dossier, base) {
                Button {
                    dossier = Fichiers.parent(dossier)
                } label: {
                    Label("Dossier parent", systemImage: "arrow.turn.left.up")
                }
            }
            if let l = liste {
                if l.entries.isEmpty {
                    EtatVide("Ce dossier est vide.") {
                        Menu("Créer ou envoyer un fichier") { actionsDossier(dossier, courant: true) }
                    }
                    .listRowSeparator(.hidden)
                }
                ForEach(l.entries) { e in
                    let abs = Fichiers.joindre(base, e.path)
                    ligne(e.avec(chemin: abs), sousTitre: nil)
                }
                if l.truncated { EtatVide("(dossier trop long : liste coupée)") }
            } else if let m = erreur {
                EtatErreur(message: m) { Task { await charger() } }
            } else {
                Chargement()
            }
        }
        .listStyle(.plain)
        .refreshable { await charger() }
    }

    @ViewBuilder
    private var resultats: some View {
        List {
            if let t = trouves {
                if t.entries.isEmpty { EtatVide("Aucun fichier nommé « \(requete) ».") }
                ForEach(t.entries) { e in
                    let abs = Fichiers.joindre(dossier, e.path)
                    ligne(e.avec(chemin: abs), sousTitre: e.path.contains("/") ? Fichiers.parent(e.path) : nil, depuisRecherche: true)
                }
                if t.truncated { EtatVide("Trop de résultats : précise ta recherche.") }
            } else {
                Chargement(texte: "Recherche…")
            }
        }
        .listStyle(.plain)
    }

    private func ligne(_ e: EntreeFichier, sousTitre: String?, depuisRecherche: Bool = false) -> some View {
        let g = Fichiers.genre(e.name, dossier: e.dir)
        return HStack(spacing: 12) {
            Image(systemName: g.icone).foregroundStyle(g.teinte).frame(width: 24)
            VStack(alignment: .leading, spacing: 2) {
                Text(e.name).lineLimit(1).truncationMode(.middle)
                if let s = sousTitre { Text(s).font(.caption).foregroundStyle(.secondary).lineLimit(1).truncationMode(.head) }
            }
            Spacer(minLength: 4)
            if !e.mark.isEmpty {
                Text(e.mark).font(.subheadline.weight(.bold)).foregroundStyle(couleurMarque(e.mark))
                    .accessibilityLabel(Fichiers.marque(e.mark))
            }
            Menu {
                actionsEntree(e)
            } label: {
                Image(systemName: "ellipsis").frame(width: 32, height: 32)
            }
            .buttonStyle(.borderless)
            .accessibilityLabel("Actions sur \(e.name)")
        }
        .contentShape(Rectangle())
        .onTapGesture { ouvrir(e, depuisRecherche: depuisRecherche) }
        .contextMenu { actionsEntree(e) }
    }

    @ViewBuilder
    private func actionsEntree(_ e: EntreeFichier) -> some View {
        if e.dir {
            Button { recherche = nil; dossier = e.path } label: { Label("Ouvrir", systemImage: "folder") }
            if let t = presse.tenu {
                Button { coller(e.path) } label: { Label("Coller « \(t.nom) » ici", systemImage: "doc.on.clipboard") }
            }
            Button { ajouterProjet(e.path) } label: { Label("Ajouter aux projets", systemImage: "text.badge.plus") }
        } else {
            Button { naviguer(.fichier(chemin: e.path, ligne: nil)) } label: { Label("Ouvrir", systemImage: "doc.text") }
            Button { recuperer(e.path, enregistrer: true) } label: { Label("Enregistrer dans Fichiers", systemImage: "square.and.arrow.down") }
            Button { recuperer(e.path, enregistrer: false) } label: { Label("Partager", systemImage: "square.and.arrow.up") }
        }
        Button {
            presse.tenu = Presse.Tenu(chemin: e.path, nom: e.name, deplacer: false)
            modele.avis.dire("« \(e.name) » copié : « Coller » dans le menu d'un dossier.")
        } label: { Label("Copier", systemImage: "doc.on.doc") }
        Button {
            presse.tenu = Presse.Tenu(chemin: e.path, nom: e.name, deplacer: true)
            modele.avis.dire("« \(e.name) » coupé : « Coller » dans le menu d'un dossier.")
        } label: { Label("Couper", systemImage: "scissors") }
        Button { renommer(e) } label: { Label("Renommer", systemImage: "pencil") }
        Button(role: .destructive) { supprimer(e) } label: { Label("Supprimer", systemImage: "trash") }
    }

    // MARK: actions

    private func ouvrir(_ e: EntreeFichier, depuisRecherche: Bool) {
        if e.dir {
            if depuisRecherche { recherche = nil }
            dossier = e.path
        } else {
            naviguer(.fichier(chemin: e.path, ligne: nil))
        }
    }

    private func charger() async {
        do {
            liste = try await client.appeler("files.list", [
                "root": .chaine(base), "rel": .chaine(Fichiers.relatif(dossier, base) ?? ""),
            ], en: ListeFichiers.self)
            erreur = nil
        } catch {
            erreur = texteErreur(error)
            if liste != nil { modele.avis.dire(texteErreur(error)) }
        }
    }

    private var racine: [String: JSON] {
        if let p = protege { return ["root": .chaine(p)] }
        return [:]
    }

    /// Lance une action (une à la fois) ; recharge le dossier si `recharger`.
    private func agir(_ libelle: String, recharger: Bool = true, _ action: @escaping () async throws -> Void) {
        guard travail == nil else { return }
        travail = libelle
        progres = nil
        Task { @MainActor in
            do {
                try await action()
            } catch {
                modele.avis.dire(texteErreur(error), long: true)
            }
            travail = nil
            progres = nil
            if recharger { await charger() }
        }
    }

    private func progresDe(_ recu: Int64, _ total: Int64) {
        progres = total > 0 ? min(1, max(0, Double(recu) / Double(total))) : nil
    }

    private func creer(_ cible: String, dossier repertoire: Bool) {
        agir(repertoire ? "Création du dossier…" : "Création du fichier…") {
            guard let nom = await demandes.nom(repertoire ? "Nouveau dossier" : "Nouveau fichier", bouton: "Créer",
                                               verifier: Fichiers.nomRefuse) else { return }
            let r = try await client.appeler(repertoire ? "files.mkdir" : "files.create", [
                "dir": .chaine(cible), "name": .chaine(nom),
            ], en: CheminRendu.self)
            if !repertoire && !r.path.isEmpty { naviguer(.fichier(chemin: r.path, ligne: nil)) }
        }
    }

    private func envoyer(_ urls: [URL], dans cible: String) {
        agir("Envoi…") {
            for url in urls {
                let nom = url.lastPathComponent
                travail = "Envoi de « \(nom) »…"
                do {
                    try await Transferts.envoyer(client, dossier: cible, url: url, nom: nom, remplacer: false) { a, b in progresDe(a, b) }
                } catch let e as RpcErreur where e.code == "existe" {
                    if !(await demandes.confirmer("Remplacer « \(nom) » ?", "Un fichier de ce nom existe déjà dans ce dossier.", "Remplacer", danger: true)) {
                        continue
                    }
                    try await Transferts.envoyer(client, dossier: cible, url: url, nom: nom, remplacer: true) { a, b in progresDe(a, b) }
                }
                let t = Transferts.taille(url)
                modele.avis.dire("« \(nom) » envoyé" + (t >= 0 ? " (\(Fichiers.taille(t)))." : "."))
            }
        }
    }

    private func coller(_ cible: String) {
        guard let t = presse.tenu else { return }
        agir(t.deplacer ? "Déplacement…" : "Copie…") {
            var p: [String: JSON] = ["path": .chaine(t.chemin), "dir": .chaine(cible), "mode": .chaine(t.deplacer ? "move" : "copy")]
            p.merge(racine) { a, _ in a }
            _ = try await client.appeler("files.paste", p, delai: 300)
            if t.deplacer { presse.tenu = nil }
            modele.avis.dire("« \(t.nom) » \(t.deplacer ? "déplacé" : "copié").")
        }
    }

    private func recuperer(_ chemin: String, enregistrer: Bool) {
        agir("Téléchargement de « \(Fichiers.nom(chemin)) »…", recharger: false) {
            let url = try await Transferts.telecharger(client, chemin) { a, b in progresDe(a, b) }
            local = FichierLocal(url: url, enregistrer: enregistrer)
        }
    }

    private func renommer(_ e: EntreeFichier) {
        agir("Renommage…") {
            guard let nom = await demandes.nom("Renommer « \(e.name) »", initial: e.name, bouton: "Renommer",
                                               verifier: Fichiers.nomRefuse), nom != e.name else { return }
            var p: [String: JSON] = ["path": .chaine(e.path), "name": .chaine(nom)]
            p.merge(racine) { a, _ in a }
            _ = try await client.appeler("files.rename", p)
        }
    }

    private func supprimer(_ e: EntreeFichier) {
        agir("Suppression…") {
            let info = try await client.appeler("files.info", ["path": .chaine(e.path)], en: InfoFichier.self)
            guard await demandes.confirmer("Supprimer « \(e.name) » ?",
                                           Fichiers.texteSuppression(dossier: info.dir, nombre: info.count, octets: info.size),
                                           "Supprimer", danger: true) else { return }
            var p: [String: JSON] = ["path": .chaine(e.path)]
            p.merge(racine) { a, _ in a }
            _ = try await client.appeler("files.delete", p, delai: 120)
            modele.avis.dire("« \(e.name) » supprimé.")
        }
    }

    private func ajouterProjet(_ chemin: String) {
        agir("Ajout aux projets…", recharger: false) {
            let r = try await client.appeler("projects.add", ["cwd": .chaine(chemin)], en: ProjetAjoute.self)
            modele.avis.dire("« \(Fichiers.nom(r.cwd.isEmpty ? chemin : r.cwd)) » ajouté aux projets.")
        }
    }
}
