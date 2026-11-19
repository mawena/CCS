package com.mawena.ccs.terminal

import android.annotation.SuppressLint
import android.content.Context
import android.graphics.Canvas
import android.graphics.Typeface
import android.text.InputType
import android.util.TypedValue
import android.view.GestureDetector
import android.view.KeyCharacterMap
import android.view.KeyEvent
import android.view.MotionEvent
import android.view.ScaleGestureDetector
import android.view.View
import android.view.inputmethod.BaseInputConnection
import android.view.inputmethod.EditorInfo
import android.view.inputmethod.InputConnection
import android.view.inputmethod.InputMethodManager
import com.mawena.ccs.logique.Touches
import com.termux.terminal.KeyHandler
import com.termux.terminal.TextStyle
import com.termux.view.TerminalRenderer
import kotlin.math.abs

/** Ctrl et Alt collants de la barre de touches : valables pour la touche suivante. */
interface Collants {
    val ctrl: Boolean
    val alt: Boolean
    fun relacher()
}

/**
 * Vue d'un terminal : dessin par le `TerminalRenderer` de Termux, saisie du clavier du téléphone
 * (sans suggestions ni correction), touches physiques (flèches, F1…F12, Ctrl, Alt), défilement de
 * l'historique au doigt (flèches dans l'écran alternatif : less, vim…), zoom à deux doigts.
 */
@SuppressLint("ViewConstructor")
class VueTerminal(context: Context, private val collants: Collants) : View(context) {
    /** Texte à envoyer au terminal. */
    var surSaisie: (String) -> Unit = {}
    /** La place change : nouvelles colonnes et lignes. */
    var surTaille: (SessionTerminal, Int, Int) -> Unit = { _, _, _ -> }
    /** Zoom à deux doigts : +1 ou −1. */
    var surZoom: (Int) -> Unit = {}
    var surAppuiLong: () -> Unit = {}

    private var rendu = TerminalRenderer(px(12f), Typeface.MONOSPACE)
    private var tailleSp = 12
    private var haut = 0                    // première ligne montrée : 0 = en bas, négatif = dans l'historique
    private var defile = 0f

    private val redessiner: () -> Unit = {
        session?.let { haut = haut.coerceIn(-it.emulateur.screen.activeTranscriptRows, 0) }
        invalidate()
    }

    var session: SessionTerminal? = null
        set(v) {
            if (field === v) return
            field?.oublier(redessiner)
            field = v
            v?.ecouter(redessiner)
            haut = 0
            ajuster()
            invalidate()
        }

    init {
        isFocusable = true
        isFocusableInTouchMode = true
    }

    private fun px(sp: Float) = TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_SP, sp, resources.displayMetrics).toInt()

    fun tailleTexte(sp: Int) {
        if (sp == tailleSp) return
        tailleSp = sp
        rendu = TerminalRenderer(px(sp.toFloat()), Typeface.MONOSPACE)
        ajuster()
        invalidate()
    }

    /** Revient en bas (nouvelle saisie). */
    fun enBas() {
        if (haut != 0) { haut = 0; invalidate() }
    }

    override fun onSizeChanged(w: Int, h: Int, oldw: Int, oldh: Int) {
        super.onSizeChanged(w, h, oldw, oldh)
        ajuster()
    }

    override fun onAttachedToWindow() {
        super.onAttachedToWindow()
        session?.let { s -> s.oublier(redessiner); s.ecouter(redessiner) }
    }

    override fun onDetachedFromWindow() {
        session?.oublier(redessiner)
        super.onDetachedFromWindow()
    }

    private fun ajuster() {
        val s = session ?: return
        if (width == 0 || height == 0) return
        val (c, l) = Touches.taille(width - paddingLeft - paddingRight, height - paddingTop - paddingBottom, rendu.fontWidth, rendu.fontLineSpacing)
        surTaille(s, c, l)
    }

    override fun onDraw(canvas: Canvas) {
        val s = session
        if (s == null) {
            canvas.drawColor(TerminalColorsFond)
            return
        }
        val emu = s.emulateur
        canvas.drawColor(emu.mColors.mCurrentColors[TextStyle.COLOR_INDEX_BACKGROUND])
        canvas.save()
        canvas.translate(paddingLeft.toFloat(), paddingTop.toFloat())
        rendu.render(emu, canvas, haut, -1, -1, -1, -1)
        canvas.restore()
    }

    // ---- saisie ----------------------------------------------------------------------------

    override fun onCheckIsTextEditor() = true

    override fun onCreateInputConnection(outAttrs: EditorInfo): InputConnection {
        outAttrs.inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_VISIBLE_PASSWORD or InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS
        outAttrs.imeOptions = EditorInfo.IME_FLAG_NO_FULLSCREEN or EditorInfo.IME_FLAG_NO_EXTRACT_UI or EditorInfo.IME_ACTION_NONE
        return object : BaseInputConnection(this, true) {
            override fun commitText(text: CharSequence?, newCursorPosition: Int): Boolean {
                super.commitText(text, newCursorPosition)
                viderTampon()
                return true
            }

            override fun finishComposingText(): Boolean {
                super.finishComposingText()
                viderTampon()
                return true
            }

            override fun deleteSurroundingText(beforeLength: Int, afterLength: Int): Boolean {
                val e = editable
                if (e.isNullOrEmpty()) {
                    repeat(beforeLength.coerceAtMost(64)) { envoyerTouche(KeyEvent.KEYCODE_DEL, null) }
                    return true
                }
                return super.deleteSurroundingText(beforeLength, afterLength)
            }

            private fun viderTampon() {
                val e = editable ?: return
                val t = e.toString()
                if (t.isEmpty()) return
                e.clear()
                taper(t)
            }
        }
    }

    /** Texte du clavier du téléphone (avec Ctrl et Alt collants). */
    fun taper(texte: String) {
        val t = Touches.appliquer(texte, collants.ctrl, collants.alt)
        collants.relacher()
        envoyer(t)
    }

    fun envoyer(data: String) {
        if (data.isEmpty()) return
        enBas()
        surSaisie(data)
    }

    /** Touche spéciale (flèches, Échap, Tab…) avec les modificateurs collants ou tenus. */
    fun envoyerTouche(code: Int, e: KeyEvent?): Boolean {
        val emu = session?.emulateur ?: return false
        var mod = 0
        if (collants.ctrl || e?.isCtrlPressed == true) mod = mod or KeyHandler.KEYMOD_CTRL
        if (collants.alt || e?.isAltPressed == true) mod = mod or KeyHandler.KEYMOD_ALT
        if (e?.isShiftPressed == true) mod = mod or KeyHandler.KEYMOD_SHIFT
        if (e?.isNumLockOn == true) mod = mod or KeyHandler.KEYMOD_NUM_LOCK
        val seq = KeyHandler.getCode(code, mod, emu.isCursorKeysApplicationMode, emu.isKeypadApplicationMode) ?: return false
        collants.relacher()
        envoyer(seq)
        return true
    }

    override fun onKeyDown(keyCode: Int, event: KeyEvent): Boolean {
        if (keyCode == KeyEvent.KEYCODE_BACK || (event.isSystem && keyCode != KeyEvent.KEYCODE_ENTER)) return super.onKeyDown(keyCode, event)
        if (session == null) return super.onKeyDown(keyCode, event)
        if (envoyerTouche(keyCode, event)) return true
        val sansMod = event.metaState and (KeyEvent.META_CTRL_MASK or KeyEvent.META_ALT_MASK or KeyEvent.META_META_MASK).inv()
        val c = event.getUnicodeChar(sansMod)
        if (c == 0 || (c and KeyCharacterMap.COMBINING_ACCENT) != 0) return super.onKeyDown(keyCode, event)
        val ctrl = collants.ctrl || event.isCtrlPressed
        val alt = collants.alt || event.isAltPressed
        collants.relacher()
        envoyer(Touches.appliquer(String(Character.toChars(c)), ctrl, alt))
        return true
    }

    /** Ouvre le clavier du téléphone. */
    fun montrerClavier() {
        requestFocus()
        context.getSystemService(InputMethodManager::class.java)?.showSoftInput(this, InputMethodManager.SHOW_IMPLICIT)
    }

    // ---- gestes ------------------------------------------------------------------------------

    private val gestes = GestureDetector(context, object : GestureDetector.SimpleOnGestureListener() {
        override fun onDown(e: MotionEvent) = true

        override fun onSingleTapUp(e: MotionEvent): Boolean {
            montrerClavier()
            return true
        }

        override fun onLongPress(e: MotionEvent) = surAppuiLong()

        override fun onScroll(e1: MotionEvent?, e2: MotionEvent, distanceX: Float, distanceY: Float): Boolean {
            val s = session ?: return false
            defile += distanceY
            val pas = rendu.fontLineSpacing.coerceAtLeast(1)
            val n = (defile / pas).toInt()
            if (n == 0) return true
            defile -= n * pas
            val emu = s.emulateur
            if (emu.isAlternateBufferActive) {
                // less, vim, htop… : le doigt fait défiler par les flèches
                val code = if (n > 0) KeyEvent.KEYCODE_DPAD_DOWN else KeyEvent.KEYCODE_DPAD_UP
                repeat(abs(n).coerceAtMost(20)) {
                    KeyHandler.getCode(code, 0, emu.isCursorKeysApplicationMode, emu.isKeypadApplicationMode)?.let(surSaisie)
                }
            } else {
                haut = (haut + n).coerceIn(-emu.screen.activeTranscriptRows, 0)
                invalidate()
            }
            return true
        }
    })

    private var echelle = 1f
    private val zoom = ScaleGestureDetector(context, object : ScaleGestureDetector.SimpleOnScaleGestureListener() {
        override fun onScaleBegin(detector: ScaleGestureDetector): Boolean { echelle = 1f; return true }
        override fun onScale(detector: ScaleGestureDetector): Boolean {
            echelle *= detector.scaleFactor
            if (echelle > 1.15f) { surZoom(1); echelle = 1f } else if (echelle < 0.87f) { surZoom(-1); echelle = 1f }
            return true
        }
    })

    @SuppressLint("ClickableViewAccessibility")
    override fun onTouchEvent(event: MotionEvent): Boolean {
        zoom.onTouchEvent(event)
        if (!zoom.isInProgress) gestes.onTouchEvent(event)
        if (event.actionMasked == MotionEvent.ACTION_DOWN) parent?.requestDisallowInterceptTouchEvent(true)
        return true
    }

    private companion object {
        val TerminalColorsFond = android.graphics.Color.rgb(0x1e, 0x1e, 0x22)
    }
}
