import SwiftUI

/**
 * Partage vers CCS : choisir un chat en cours ou un nouveau chat (dossier). Les fichiers partent
 * d'abord dans le dossier du projet (`files.upload`, sans rien écraser), puis le chat s'ouvre avec
 * le texte et les fichiers cités dans la saisie. Rien n'est envoyé à Claude : on relit et on
 * envoie soi-même.
 */
@MainActor
struct FeuillePartage: View {
    @Environment(ModeleAppli.self) private var modele
    @Environment(\.dismiss) private var fermer
    let partage: Partage
    let ouvrir: (DestChat) -> Void

    @State private var chats: [ChatOuvert]? = nil
    @State private var erreur: String? = nil
    @State private var progres: String? = nil
    @State private var nouvelle = false

    private static let maxEssaisNom = 20

    var body: some View {
        NavigationStack {
            List {
                Section {
                    if !partage.texte.isEmpty {
                        Text(partage.texte).lineLimit(3).font(.callout)
                    }
                    ForEach(partage.fichiers, id: \.self) { f in
                        Label(f.lastPathComponent, systemImage: "doc").font(.callout)
                    }
                } footer: {
                    Text(partage.resume + (partage.fichiers.isEmpty ? "" : " · les fichiers iront dans le dossier du projet") + ". Tu relis avant d'envoyer.")
                }
                if let p = progres {
                    HStack(spacing: 12) {
                        ProgressView()
                        Text(p)
                    }
                } else {
                    if let m = erreur { Text(m).foregroundStyle(.red) }
                    Section {
                        Button { nouvelle = true } label: {
                            Label("Nouveau chat…", systemImage: "plus.bubble")
                        }
                        .disabled(!modele.client.etat.estConnecte)
                    }
                    Section("Chats en cours") {
                        if let l = chats {
                            if l.isEmpty { Text("Aucun chat ouvert.").foregroundStyle(.secondary) }
                            ForEach(l) { c in
                                let e = EtatChat.de(c.state)
                                Button { livrer(c, repli: c.cwd) } label: {
                                    HStack(spacing: 10) {
                                        Pastille(couleur: couleurEtat(e.ton))
                                        VStack(alignment: .leading, spacing: 2) {
                                            Text(Format.base(c.cwd)).foregroundStyle(.primary).lineLimit(1)
                                            Text("\(e.libelle) · \(c.cwd)").font(.caption).foregroundStyle(.secondary)
                                                .lineLimit(1).truncationMode(.head)
                                        }
                                    }
                                }
                            }
                        } else {
                            HStack(spacing: 8) {
                                ProgressView()
                                Text(modele.client.etat.estConnecte ? "Chargement…" : "Connexion au serveur…").foregroundStyle(.secondary)
                            }
                        }
                    }
                }
            }
            .navigationTitle("Partager vers CCS")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Annuler") { fermer() }.disabled(progres != nil)
                }
            }
            .task(id: modele.client.etat.estConnecte) {
                guard modele.client.etat.estConnecte else { return }
                do {
                    chats = try await modele.client.appeler("chat.list", en: ListeChats.self).chats
                    erreur = nil
                } catch {
                    erreur = texteErreur(error)
                }
            }
            .sheet(isPresented: $nouvelle) {
                FeuilleNouvelleSession(connus: []) { r, chemin in
                    nouvelle = false
                    livrer(r, repli: chemin)
                }
            }
        }
        .interactiveDismissDisabled(progres != nil)
    }

    private func livrer(_ c: ChatOuvert, repli: String) {
        let cwd = c.cwd.isEmpty ? repli : c.cwd
        Task {
            erreur = nil
            do {
                var envoyes: [String] = []
                for (k, f) in partage.fichiers.enumerated() {
                    progres = "Envoi de « \(f.lastPathComponent) »" + (partage.fichiers.count > 1 ? " (\(k + 1)/\(partage.fichiers.count))" : "") + "…"
                    envoyes.append(try await envoyerSansEcraser(f, dossier: cwd))
                }
                let dest = DestChat(cwd: cwd, sessionId: c.sessionId, chemin: c.path, titre: Format.base(cwd), chatId: c.chatId)
                let cle = "brouillon:" + dest.cle
                Prefs.ecrire(cle, Partage.composer(Prefs.lire(cle) ?? "", partage.texte, envoyes))
                progres = nil
                ouvrir(dest)
            } catch {
                progres = nil
                erreur = texteErreur(error)
            }
        }
    }

    /// Envoie le fichier sans rien écraser : « nom (2).ext » si le nom est pris ; rend le nom gardé.
    private func envoyerSansEcraser(_ f: URL, dossier: String) async throws -> String {
        let base = Transferts.nettoyer(f.lastPathComponent)
        for essai in 1...FeuillePartage.maxEssaisNom {
            let nom = Partage.nomLibre(base, essai)
            do {
                try await Transferts.envoyer(modele.client, dossier: dossier, url: f, nom: nom, remplacer: false)
                return nom
            } catch let e as RpcErreur where e.code == "existe" {
                continue
            }
        }
        throw RpcErreur("existe", "« \(base) » : trop de fichiers du même nom dans le dossier.")
    }
}

extension ModeleAppli {
    /**
     * Fichier reçu par « Ouvrir dans CCS » (copié par iOS dans la boîte de réception de l'appli)
     * ou lien `ccs://partager` : la feuille de partage s'ouvre.
     */
    func recevoir(_ u: URL) {
        // ccs://root : demande du mot de passe root (lien d'un avis) : la feuille revient
        if u.scheme?.lowercased() == "ccs", u.host?.lowercased() == "root" {
            root.afficher()
            return
        }
        if u.isFileURL {
            var p = partage ?? Partage(texte: "", fichiers: [])
            if !p.fichiers.contains(u) { p.fichiers.append(u) }
            partage = p
        } else if let p = Partage.depuisLien(u), !p.vide {
            partage = p
        }
    }
}
