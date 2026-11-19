package com.mawena.ccs.ui

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

/** Couleurs de CCS (manifeste web) : accent #3584e4, fond sombre #222226, fond clair #fafafb. */
val Accent = Color(0xFF3584E4)

private val Clair = lightColorScheme(
    primary = Accent, onPrimary = Color.White,
    primaryContainer = Color(0xFFD6E6FB), onPrimaryContainer = Color(0xFF0B3A73),
    secondary = Color(0xFF4A5B73), onSecondary = Color.White,
    secondaryContainer = Color(0xFFDDE4EE), onSecondaryContainer = Color(0xFF1C2735),
    background = Color(0xFFFAFAFB), onBackground = Color(0xFF1E1E22),
    surface = Color(0xFFFAFAFB), onSurface = Color(0xFF1E1E22),
    surfaceVariant = Color(0xFFEBEBED), onSurfaceVariant = Color(0xFF5C5C66),
    surfaceContainerLowest = Color.White, surfaceContainerLow = Color(0xFFF5F5F7),
    surfaceContainer = Color(0xFFF0F0F2), surfaceContainerHigh = Color(0xFFEBEBED),
    surfaceContainerHighest = Color(0xFFE4E4E7),
    outline = Color(0xFFC4C4CA), outlineVariant = Color(0xFFDEDEE2),
    error = Color(0xFFC01C28), onError = Color.White,
)

private val Sombre = darkColorScheme(
    primary = Accent, onPrimary = Color.White,
    primaryContainer = Color(0xFF1E4F8C), onPrimaryContainer = Color(0xFFD6E6FB),
    secondary = Color(0xFFB4C3D8), onSecondary = Color(0xFF1C2735),
    secondaryContainer = Color(0xFF34404F), onSecondaryContainer = Color(0xFFDDE4EE),
    background = Color(0xFF222226), onBackground = Color(0xFFEDEDEF),
    surface = Color(0xFF222226), onSurface = Color(0xFFEDEDEF),
    surfaceVariant = Color(0xFF3A3A40), onSurfaceVariant = Color(0xFFB8B8C0),
    surfaceContainerLowest = Color(0xFF1C1C1F), surfaceContainerLow = Color(0xFF29292D),
    surfaceContainer = Color(0xFF2E2E33), surfaceContainerHigh = Color(0xFF36363B),
    surfaceContainerHighest = Color(0xFF3D3D43),
    outline = Color(0xFF5C5C66), outlineVariant = Color(0xFF44444B),
    error = Color(0xFFFF7B63), onError = Color(0xFF2B0A05),
)

@Composable
fun ThemeCcs(sombre: Boolean = isSystemInDarkTheme(), contenu: @Composable () -> Unit) {
    MaterialTheme(colorScheme = if (sombre) Sombre else Clair, content = contenu)
}
