import SwiftUI

/// Identifiant de message d'une ligne (bulles seulement), pour les étiquettes.
private func msgIdDe(_ l: LigneFil) -> String? {
    guard let e = l.element else { return nil }
    switch e {
    case .toi(let m): return m.msgId.isEmpty ? nil : m.msgId
    case .claude(let m): return m.msgId.isEmpty ? nil : m.msgId
    default: return nil
    }
}

/// Écran d'un chat : le modèle est créé au premier affichage et gardé tant que l'écran vit.
@MainActor
struct EcranChat: View {
    @Environment(ModeleAppli.self) private var modele
    let dest: DestChat
    @State private var mc: ModeleChat? = nil

    var body: some View {
        Group {
            if let m = mc {
                FilChatVue(mc: m, titre: titre)
            } else {
                Chargement(texte: "Ouverture du chat…")
            }
        }
        .navigationTitle(titre)
        .navigationBarTitleDisplayMode(.inline)
        .toolbar(.hidden, for: .tabBar)
        .onAppear {
            if mc == nil {
                let m = ModeleChat(client: modele.client, avis: modele.avis, dest: dest)
                mc = m
                m.demarrer()
            }
        }
        .onDisappear { mc?.quitter() }
    }

    private var titre: String {
        if let t = dest.titre, !t.isEmpty { return t }
        return Format.base(dest.cwd)
    }
}

/// Le fil, la recherche, les sous-agents et la saisie.
@MainActor
private struct FilChatVue: View {
    @Environment(ModeleAppli.self) private var modele
    let mc: ModeleChat
    let titre: String

    @State private var enBas = true
    @State private var recherche = false
    @State private var requete = ""
    @State private var trouve = -1
    @State private var passage: MessageChoisi? = nil
    @State private var aEtiqueter: MessageChoisi? = nil
    @State private var voletEtiquettes = false
    @State private var filtreEtiquette: String? = nil
    @State private var effacer = false
    @State private var viser: String? = nil

    var body: some View {
        let vue = mc.vue
        let lignes = vue.agentVu == nil ? vue.lignes : vue.lignesAgent
        let resultats = recherche ? Recherche.trouver(lignes.map { LigneFil.texte($0) }, requete) : []
        let surligne: String? = (trouve >= 0 && trouve < resultats.count) ? lignes[resultats[trouve]].cle : nil
        VStack(spacing: 0) {
            if recherche {
                BarreRecherche(requete: $requete, trouve: trouve, nombre: resultats.count,
                               pas: { sens in
                                   trouve = Recherche.pas(trouve < 0 ? (sens > 0 ? -1 : 0) : trouve, resultats.count, sens)
                                   if trouve >= 0 && trouve < resultats.count { viser = lignes[resultats[trouve]].cle }
                               },
                               fermer: {
                                   recherche = false
                                   requete = ""
                                   trouve = -1
                               })
            }
            if !vue.agents.isEmpty {
                PucesAgents(agents: vue.agents, vu: vue.agentVu) { mc.voirAgent($0) }
            }
            if let err = vue.ouverture {
                EtatErreur(message: err) { mc.reessayerOuverture() }
                    .frame(maxHeight: .infinity)
            } else {
                ScrollViewReader { proxy in
                    ZStack(alignment: .bottomTrailing) {
                        ScrollView {
                            LazyVStack(alignment: .leading, spacing: 8) {
                                if vue.agentVu == nil && !vue.historiqueComplet {
                                    Button("Messages plus anciens") { mc.chargerPlus() }
                                        .buttonStyle(.bordered)
                                        .controlSize(.small)
                                        .frame(maxWidth: .infinity)
                                }
                                if lignes.isEmpty && vue.pret {
                                    Text(vue.agentVu == nil ? "Écris ton premier message à Claude." : "Ce sous-agent n'a encore rien fait.")
                                        .font(.footnote)
                                        .foregroundStyle(.secondary)
                                        .frame(maxWidth: .infinity)
                                        .padding(.top, 40)
                                } else if lignes.isEmpty {
                                    Chargement().frame(maxWidth: .infinity).padding(.top, 40)
                                }
                                ForEach(lignes) { l in
                                    LigneVue(ligne: l, etiquettes: msgIdDe(l).flatMap { mc.etiquettes[$0]?.etiquettes },
                                             surligne: l.cle == surligne, actions: actions)
                                        .id(l.cle)
                                }
                                Color.clear
                                    .frame(height: 1)
                                    .id("bas")
                                    .onAppear { enBas = true }
                                    .onDisappear { enBas = false }
                            }
                            .padding(.horizontal, 10)
                            .padding(.vertical, 8)
                        }
                        .defaultScrollAnchor(.bottom)
                        .scrollDismissesKeyboard(.interactively)
                        if !enBas {
                            Button {
                                withAnimation { proxy.scrollTo("bas", anchor: .bottom) }
                            } label: {
                                Image(systemName: "arrow.down")
                                    .font(.headline)
                                    .padding(10)
                                    .background(Circle().fill(Color.carte))
                                    .shadow(radius: 2)
                            }
                            .accessibilityLabel("Aller en bas")
                            .padding(12)
                        }
                    }
                    .onChange(of: lignes.last) { _, _ in
                        if enBas { proxy.scrollTo("bas", anchor: .bottom) }
                    }
                    .onChange(of: viser) { _, cle in
                        if let c = cle {
                            withAnimation { proxy.scrollTo(c, anchor: .center) }
                            viser = nil
                        }
                    }
                }
            }
        }
        .safeAreaInset(edge: .bottom, spacing: 0) {
            VStack(spacing: 0) {
                if vue.agentVu == nil {
                    VueTaches(taches: vue.taches)
                    BandeauEtat(vue: vue)
                    Saisie(mc: mc)
                } else {
                    Button("Revenir au chat principal") { mc.voirAgent(nil) }
                        .buttonStyle(.borderedProminent)
                        .padding(8)
                        .frame(maxWidth: .infinity)
                        .background(.bar)
                }
            }
        }
        .onChange(of: requete) { _, _ in trouve = -1 }
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Menu {
                    Button {
                        recherche = true
                    } label: {
                        Label("Rechercher", systemImage: "magnifyingglass")
                    }
                    Button {
                        filtreEtiquette = nil
                        voletEtiquettes = true
                    } label: {
                        Label("Étiquettes", systemImage: "tag")
                    }
                    if let sid = mc.sessionId {
                        Button {
                            copier(sid)
                            modele.avis.dire("Identifiant de session copié.")
                        } label: {
                            Label("Copier l'identifiant de session", systemImage: "number")
                        }
                    }
                    Divider()
                    Button {
                        effacer = true
                    } label: {
                        Label("Nouvelle conversation (/clear)", systemImage: "eraser")
                    }
                } label: {
                    Image(systemName: "ellipsis.circle")
                }
                .accessibilityLabel("Actions du chat")
            }
        }
        .confirmationDialog("Effacer la conversation ?", isPresented: $effacer, titleVisibility: .visible) {
            Button("Nouvelle conversation") { mc.envoyerTexte("/clear") }
            Button("Annuler", role: .cancel) {}
        } message: {
            Text("Claude ne verra plus les messages précédents ; ils restent affichés au-dessus.")
        }
        .sheet(item: $passage) { m in
            DialoguePassage(m: m) { c in mc.citer(c) }
        }
        .sheet(item: $aEtiqueter) { m in
            DialogueEtiquettes(m: m, actuelles: mc.etiquettes[m.msgId]?.etiquettes ?? [], connues: mc.connues) { liste in
                mc.etiqueter(m.msgId, liste, texte: m.texte, role: m.auteur == .moi ? "utilisateur" : "assistant")
            }
        }
        .sheet(isPresented: $voletEtiquettes) {
            FeuilleEtiquettes(etiquettes: mc.etiquettes, filtre: filtreEtiquette) { id in montrerMessage(id) }
        }
    }

    private var actions: ActionsFil {
        let m = mc
        return ActionsFil(
            citer: { auteur, brut in
                if let c = Citation.de(auteur, brut) { m.citer(c) }
            },
            passage: { passage = $0 },
            etiqueter: { choisi in
                if choisi.msgId.isEmpty || m.sessionId == nil {
                    m.dire("Ce message ne peut pas encore être étiqueté.")
                } else {
                    aEtiqueter = choisi
                }
            },
            voirAgent: { m.voirAgent($0) },
            repondre: { id, decision, motif in m.repondre(id, decision, motif) },
            questions: { id, reponses in m.repondreQuestions(id, reponses) },
            arreterShell: { m.arreterShell($0) },
            reprendre: { m.reprendre() },
            compacter: { m.envoyerTexte("/compact") },
            voirEtiquette: { e in
                filtreEtiquette = e
                voletEtiquettes = true
            }
        )
    }

    /// Montre un message étiqueté : charge tout l'historique s'il le faut, puis défile jusqu'à lui.
    private func montrerMessage(_ msgId: String) {
        let m = mc
        Task { @MainActor in
            if m.vue.agentVu != nil { m.voirAgent(nil) }
            if !m.vue.lignes.contains(where: { msgIdDe($0) == msgId }) {
                await m.chargerToutHistorique()
            }
            if let l = m.vue.lignes.first(where: { msgIdDe($0) == msgId }) {
                viser = l.cle
            } else {
                m.dire("Message introuvable dans ce chat.")
            }
        }
    }
}

@MainActor
private struct BarreRecherche: View {
    @Binding var requete: String
    let trouve: Int
    let nombre: Int
    let pas: (Int) -> Void
    let fermer: () -> Void
    @FocusState private var focus: Bool

    var body: some View {
        HStack(spacing: 6) {
            Image(systemName: "magnifyingglass").foregroundStyle(.secondary)
            TextField("Rechercher dans le fil", text: $requete)
                .focused($focus)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .submitLabel(.search)
                .onSubmit { pas(1) }
            Text(compte).font(.caption).foregroundStyle(.secondary).monospacedDigit()
            Button { pas(-1) } label: { Image(systemName: "chevron.up") }
                .disabled(nombre == 0)
                .accessibilityLabel("Précédent")
            Button { pas(1) } label: { Image(systemName: "chevron.down") }
                .disabled(nombre == 0)
                .accessibilityLabel("Suivant")
            Button(action: fermer) { Image(systemName: "xmark") }
                .accessibilityLabel("Fermer la recherche")
        }
        .buttonStyle(.borderless)
        .padding(.horizontal, 12)
        .padding(.vertical, 6)
        .background(.bar)
        .onAppear { focus = true }
    }

    private var compte: String {
        if requete.trimmingCharacters(in: .whitespaces).isEmpty { return "" }
        if nombre == 0 { return "0" }
        return trouve < 0 ? "\(nombre)" : "\(trouve + 1)/\(nombre)"
    }
}

/// Sous-agents du chat : touchez-en un pour voir son fil.
@MainActor
private struct PucesAgents: View {
    let agents: [VueAgent]
    let vu: String?
    let choisir: (String?) -> Void

    var body: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 6) {
                Button {
                    choisir(nil)
                } label: {
                    Text("Chat").font(.caption)
                }
                .buttonStyle(.bordered)
                .tint(vu == nil ? Color.accentCcs : Color.secondary)
                ForEach(agents) { a in
                    Button {
                        choisir(a.id)
                    } label: {
                        HStack(spacing: 4) {
                            if a.statut == .travaille { ProgressView().controlSize(.mini) }
                            Text(a.nom).font(.caption).lineLimit(1)
                        }
                    }
                    .buttonStyle(.bordered)
                    .tint(vu == a.id ? Color.accentCcs : Color.secondary)
                }
            }
            .controlSize(.small)
            .padding(.horizontal, 10)
            .padding(.vertical, 4)
        }
        .background(.bar)
    }
}
