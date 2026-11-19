package com.mawena.ccs.ui.fichiers

import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Code
import androidx.compose.material.icons.filled.Description
import androidx.compose.material.icons.filled.Folder
import androidx.compose.material.icons.filled.FolderZip
import androidx.compose.material.icons.filled.Image
import androidx.compose.material.icons.filled.InsertDriveFile
import androidx.compose.material.icons.filled.Movie
import androidx.compose.material.icons.filled.PictureAsPdf
import androidx.compose.material.icons.filled.Settings
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import com.mawena.ccs.logique.Fichiers

/** Ce qui attend d'être collé (copié ou coupé) : commun à tous les volets, comme au web. */
object Presse {
    data class Tenu(val chemin: String, val nom: String, val deplacer: Boolean)

    var tenu by mutableStateOf<Tenu?>(null)
}

@Suppress("DEPRECATION")
fun icone(g: Fichiers.Genre): ImageVector = when (g) {
    Fichiers.Genre.Dossier -> Icons.Filled.Folder
    Fichiers.Genre.Texte -> Icons.Filled.Description
    Fichiers.Genre.Code -> Icons.Filled.Code
    Fichiers.Genre.Config -> Icons.Filled.Settings
    Fichiers.Genre.Image -> Icons.Filled.Image
    Fichiers.Genre.Archive -> Icons.Filled.FolderZip
    Fichiers.Genre.Media -> Icons.Filled.Movie
    Fichiers.Genre.Document -> Icons.Filled.PictureAsPdf
    Fichiers.Genre.Fichier -> Icons.Filled.InsertDriveFile
}

/** Couleur de l'icône d'une famille (celles de la version web, lisibles en clair et en sombre). */
fun teinte(g: Fichiers.Genre): Color = when (g) {
    Fichiers.Genre.Dossier -> Color(0xFFE5A50A)
    Fichiers.Genre.Code -> Color(0xFF3584E4)
    Fichiers.Genre.Config -> Color(0xFF9141AC)
    Fichiers.Genre.Image -> Color(0xFF2EC27E)
    Fichiers.Genre.Archive -> Color(0xFFC64600)
    Fichiers.Genre.Media -> Color(0xFFE01B24)
    Fichiers.Genre.Document -> Color(0xFFC01C28)
    Fichiers.Genre.Texte, Fichiers.Genre.Fichier -> Color(0xFF77767B)
}

/** Couleur d'une marque git (M, A, ?, D). */
fun couleurMarque(m: String): Color = when (m) {
    "M" -> Color(0xFFE5A50A)
    "A", "?" -> Color(0xFF33D17A)
    "D" -> Color(0xFFE01B24)
    else -> Color(0xFF77767B)
}
