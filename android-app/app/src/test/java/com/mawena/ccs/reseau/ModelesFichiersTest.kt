package com.mawena.ccs.reseau

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class ModelesFichiersTest {
    private val json = CodecRpc.json

    @Test
    fun listeEtLecture() {
        val l = json.decodeFromString(ListeFichiers.serializer(),
            """{"entries": [{"name": "src", "path": "src", "dir": true, "mark": ""}, {"name": "a.kt", "path": "a.kt", "dir": false, "mark": "M"}], "truncated": true}""")
        assertEquals(2, l.entries.size)
        assertTrue(l.entries[0].dir)
        assertEquals("M", l.entries[1].mark)
        assertTrue(l.truncated)
        val r = json.decodeFromString(FichierLu.serializer(),
            """{"kind": "text", "stamp": [1763500000123456789, 42], "text": "x", "encoding": "utf-8"}""")
        assertEquals("text", r.kind)
        // le tampon repart tel quel vers files.write (grand entier compris)
        val p = buildJsonObject { put("stamp", r.stamp!!) }
        assertEquals("[1763500000123456789,42]", (p["stamp"] as JsonArray).toString())
        assertEquals("image", json.decodeFromString(FichierLu.serializer(), """{"kind": "image", "stamp": [1, 2]}""").kind)
    }

    @Test
    fun autresReponses() {
        val r = json.decodeFromString(RacinesFichiers.serializer(), """{"home": "/home/c", "roots": ["/home/c", "/srv"]}""")
        assertEquals(listOf("/home/c", "/srv"), r.roots)
        val m = json.decodeFromString(MorceauFichier.serializer(), """{"size": 300000000, "data": "YQ==", "done": false}""")
        assertEquals(300_000_000L, m.size)
        val i = json.decodeFromString(InfoFichier.serializer(), """{"dir": true, "count": 7, "size": 0}""")
        assertEquals(7, i.count)
        assertEquals(listOf("a", "b/c"), json.decodeFromString(IndexFichiers.serializer(), """{"files": ["a", "b/c"]}""").files)
    }
}
