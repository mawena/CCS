package com.mawena.ccs.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.consumeWindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.AccountTree
import androidx.compose.material.icons.filled.Folder
import androidx.compose.material.icons.filled.Forum
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.MoreHoriz
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.navigation.NavType
import androidx.navigation.navArgument
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.navigation.NavGraph.Companion.findStartDestination
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import com.mawena.ccs.reseau.EtatConnexion
import com.mawena.ccs.ui.chat.EcranChat
import kotlinx.coroutines.launch
import com.mawena.ccs.ui.fichiers.EcranFichier
import com.mawena.ccs.ui.fichiers.EcranFichiersOnglet
import com.mawena.ccs.ui.fichiers.EcranFichiersProjet
import com.mawena.ccs.ui.git.EcranCommit
import com.mawena.ccs.ui.git.EcranGitOnglet
import com.mawena.ccs.ui.git.EcranGitProjet

enum class Onglet(val route: String, val titre: String, val icone: ImageVector) {
    Accueil("accueil", "Accueil", Icons.Filled.Home),
    Sessions("sessions", "Sessions", Icons.Filled.Forum),
    Fichiers("fichiers", "Fichiers", Icons.Filled.Folder),
    Git("git", "Git", Icons.Filled.AccountTree),
    Plus("plus", "Plus", Icons.Filled.MoreHoriz),
}

@Composable
fun Racine(modele: ModeleAppli) {
    val identifiants by modele.identifiants.collectAsStateWithLifecycle()
    if (identifiants == null) EcranConnexion(modele) else EcranPrincipal(modele)
}

@Composable
fun EcranPrincipal(modele: ModeleAppli) {
    val nav = rememberNavController()
    val entree by nav.currentBackStackEntryAsState()
    val route = Routes.onglet(entree?.destination?.route)
    val hote = remember { SnackbarHostState() }
    val portee = rememberCoroutineScope()
    val avis = remember(hote, portee) { Avis(hote, portee) }
    val argument = { nom: String -> navArgument(nom) { type = NavType.StringType; defaultValue = "" } }
    // nouveau terminal dans un dossier (chat, projet), puis son écran
    val terminalDans: (String) -> Unit = { cwd ->
        portee.launch {
            try { nav.navigate(Routes.terminal(com.mawena.ccs.ui.terminal.ouvrirTerminal(modele, cwd).id)) }
            catch (e: Exception) { avis.dire("Terminal impossible : ${e.texte()}") }
        }
    }
    // notification touchée, raccourci d'appli
    val demande by modele.demande.collectAsStateWithLifecycle()
    LaunchedEffect(demande) {
        val d = demande ?: return@LaunchedEffect
        modele.demande.value = null
        val versSessions: () -> Unit = {
            nav.navigate(Onglet.Sessions.route) {
                popUpTo(nav.graph.findStartDestination().id) { saveState = true }
                launchSingleTop = true
                restoreState = true
            }
        }
        when (d) {
            is DemandeAppli.OuvrirChat -> nav.navigate(d.dest.route()) { launchSingleTop = true }
            DemandeAppli.Sessions -> versSessions()
            DemandeAppli.NouveauChat -> { modele.nouvelleSession.value = true; versSessions() }
        }
    }
    val partage by modele.partage.collectAsStateWithLifecycle()
    // Autre machine pilotée : les écrans ouverts (chat, projet…) étaient ceux de l'ancienne ; retour
    // aux Sessions, onglets remis à zéro. Les données se rechargent à la connexion (état Connecte).
    val machine by modele.machine.collectAsStateWithLifecycle()
    var machineVue by rememberSaveable { mutableStateOf(machine) }
    LaunchedEffect(machine) {
        if (machine == machineVue) return@LaunchedEffect
        machineVue = machine
        Onglet.entries.forEach { runCatching { nav.clearBackStack(it.route) } }
        nav.navigate(Onglet.Sessions.route) {
            popUpTo(nav.graph.findStartDestination().id)
            launchSingleTop = true
        }
    }
    val choixMachine by modele.choixMachine.collectAsStateWithLifecycle()
    CompositionLocalProvider(LocalAvis provides avis) {
    if (choixMachine) FeuilleMachines(modele, fermer = { modele.choixMachine.value = false })
    partage?.let { p ->
        FeuillePartage(modele, p, fermer = { modele.partage.value = null }) { dest ->
            modele.partage.value = null
            nav.navigate(dest.route()) { launchSingleTop = true }
        }
    }
    Scaffold(
        snackbarHost = { SnackbarHost(hote) },
        bottomBar = {
            // le chat prend tout l'écran (clavier, saisie) : pas de barre d'onglets
            val plein = entree?.destination?.route?.let { it.startsWith("chat") || it.startsWith("terminal?") } == true
            if (!plein) NavigationBar {
                Onglet.entries.forEach { o ->
                    NavigationBarItem(
                        selected = route == o.route,
                        onClick = {
                            nav.navigate(o.route) {
                                popUpTo(nav.graph.findStartDestination().id) { saveState = true }
                                launchSingleTop = true
                                restoreState = true
                            }
                        },
                        icon = { Icon(o.icone, contentDescription = null) },
                        label = { Text(o.titre) },
                    )
                }
            }
        },
    ) { marges ->
        Column(Modifier.fillMaxSize().padding(marges).consumeWindowInsets(marges)) {
            BandeauMachine(modele, changer = { modele.choixMachine.value = true })
            BandeauConnexion(modele)
            NavHost(nav, startDestination = Onglet.Accueil.route, modifier = Modifier.weight(1f)) {
                composable(Onglet.Accueil.route) {
                    EcranAccueil(
                        modele, ouvrirAnalyse = { nav.navigate(Routes.ANALYSE) },
                        ouvrirChat = { nav.navigate(it.route()) },
                        ouvrirTerminal = { nav.navigate(Routes.terminal(it)) },
                    )
                }
                composable(Routes.ANALYSE) { EcranAnalyse(modele, retour = { nav.popBackStack() }) }
                composable(Onglet.Sessions.route) {
                    EcranSessions(
                        modele,
                        ouvrirProjet = { nav.navigate(Routes.projet(it)) },
                        ouvrirChat = { nav.navigate(it.route()) },
                    )
                }
                composable(Routes.PROJET, arguments = listOf(argument("cwd"))) { e ->
                    EcranProjet(
                        modele, e.arguments?.getString("cwd").orEmpty(),
                        retour = { nav.popBackStack() },
                        ouvrirChat = { nav.navigate(it.route()) },
                        ouvrirFichier = { nav.navigate(Routes.fichier(it)) },
                        ouvrirCommit = { cwd, id -> nav.navigate(Routes.commit(cwd, id)) },
                        ouvrirTerminal = terminalDans,
                    )
                }
                composable(Routes.CHAT, arguments = listOf("cwd", "sid", "chemin", "titre", "chat", "envoi", "jeton").map(argument)) { e ->
                    EcranChat(
                        modele, DestChat.de(e), retour = { nav.popBackStack() },
                        ouvrirFichier = { chemin, ligne -> nav.navigate(Routes.fichier(chemin, ligne)) },
                        ouvrirFichiers = { nav.navigate(Routes.fichiersProjet(it)) },
                        ouvrirGit = { nav.navigate(Routes.gitProjet(it)) },
                        ouvrirChat = { nav.navigate(it.route()) },
                        ouvrirTerminal = terminalDans,
                    )
                }
                composable(Onglet.Fichiers.route) { EcranFichiersOnglet(modele, ouvrirFichier = { nav.navigate(Routes.fichier(it)) }) }
                composable(Routes.FICHIERS_PROJET, arguments = listOf(argument("cwd"))) { e ->
                    EcranFichiersProjet(modele, e.arguments?.getString("cwd").orEmpty(), retour = { nav.popBackStack() },
                        ouvrirFichier = { nav.navigate(Routes.fichier(it)) })
                }
                composable(Routes.FICHIER, arguments = listOf(argument("chemin"), argument("ligne"))) { e ->
                    EcranFichier(
                        modele, e.arguments?.getString("chemin").orEmpty(), e.arguments?.getString("ligne")?.toIntOrNull(),
                        retour = { nav.popBackStack() },
                    )
                }
                composable(Onglet.Git.route) { EcranGitOnglet(modele, ouvrirGit = { nav.navigate(Routes.gitProjet(it)) }) }
                composable(Routes.GIT_PROJET, arguments = listOf(argument("cwd"))) { e ->
                    val cwd = e.arguments?.getString("cwd").orEmpty()
                    EcranGitProjet(modele, cwd, retour = { nav.popBackStack() }, ouvrirCommit = { nav.navigate(Routes.commit(cwd, it)) })
                }
                composable(Routes.COMMIT, arguments = listOf(argument("cwd"), argument("id"))) { e ->
                    EcranCommit(modele, e.arguments?.getString("cwd").orEmpty(), e.arguments?.getString("id").orEmpty(), retour = { nav.popBackStack() })
                }
                composable(Onglet.Plus.route) {
                    EcranPlus(
                        modele, ouvrirAnalyse = { nav.navigate(Routes.ANALYSE) },
                        ouvrirReglages = { nav.navigate(Routes.REGLAGES) },
                        ouvrirTerminaux = { nav.navigate(Routes.TERMINAUX) },
                    )
                }
                composable(Routes.REGLAGES) { com.mawena.ccs.ui.reglages.EcranReglages(modele, retour = { nav.popBackStack() }) }
                composable(Routes.TERMINAUX) {
                    com.mawena.ccs.ui.terminal.EcranTerminaux(modele, retour = { nav.popBackStack() }, ouvrir = { nav.navigate(Routes.terminal(it)) })
                }
                composable(Routes.TERMINAL, arguments = listOf(argument("id"))) { e ->
                    com.mawena.ccs.ui.terminal.EcranTerminal(modele, e.arguments?.getString("id").orEmpty(), retour = { nav.popBackStack() })
                }
            }
        }
    }
    }
}

/** Bandeau discret tant que le WebSocket n'est pas ouvert. */
@Composable
fun BandeauConnexion(modele: ModeleAppli) {
    val etat by modele.etat.collectAsStateWithLifecycle()
    val texte = when (val e = etat) {
        EtatConnexion.Connecte, EtatConnexion.Arrete, is EtatConnexion.Refuse -> return
        is EtatConnexion.Connexion ->
            if (modele.depot.client.machine.value.isEmpty()) "Connexion au serveur…" else "Connexion à ${modele.depot.client.nomMachine}…"
        is EtatConnexion.HorsLigne -> "${e.raison} Nouvel essai dans ${(e.attenteMs / 1000).coerceAtLeast(1)} s."
    }
    Surface(color = MaterialTheme.colorScheme.secondaryContainer, modifier = Modifier.fillMaxWidth()) {
        Row(
            Modifier.padding(horizontal = 16.dp, vertical = 6.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            if (etat is EtatConnexion.Connexion) CircularProgressIndicator(Modifier.size(16.dp), strokeWidth = 2.dp)
            Text(texte, Modifier.weight(1f), style = MaterialTheme.typography.bodyMedium)
            if (etat is EtatConnexion.HorsLigne) {
                TextButton(onClick = { modele.depot.client.reessayer() }) { Text("Réessayer") }
            }
        }
    }
}

@Composable
fun EcranProvisoire(titre: String, texte: String) {
    Box(Modifier.fillMaxSize().padding(24.dp), contentAlignment = Alignment.Center) {
        Column(horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text(titre, style = MaterialTheme.typography.headlineSmall)
            Text(
                "À venir. $texte", textAlign = TextAlign.Center,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}
