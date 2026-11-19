package com.mawena.ccs.ui.chat

import androidx.compose.runtime.Stable
import androidx.compose.runtime.compositionLocalOf
import com.mawena.ccs.logique.LiensFichiers

/** Fichiers du projet du chat et comment les ouvrir (chemin absolu, ligne) : liens du Markdown et des diffs. */
@Stable
class OuvreFichier(val liens: LiensFichiers, val ouvrir: (String, Int?) -> Unit)

val LocalOuvreFichier = compositionLocalOf<OuvreFichier?> { null }
