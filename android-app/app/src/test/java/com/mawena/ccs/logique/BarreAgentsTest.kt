package com.mawena.ccs.logique

import org.junit.Assert.assertEquals
import org.junit.Test

class BarreAgentsTest {
    private fun a(id: String, s: StatutAgent) = VueAgent(id, id, s, false)
    private val agents = listOf(a("a1", StatutAgent.Fini), a("a2", StatutAgent.Travaille), a("a3", StatutAgent.Arrete), a("a4", StatutAgent.Fini))

    @Test
    fun lesFinisQuittentLaBarreSaufCeluiRegarde() {
        assertEquals(listOf("a2"), BarreAgents.pastilles(agents, null).map { it.id })
        assertEquals(listOf("a2", "a3"), BarreAgents.pastilles(agents, "a3").map { it.id })
    }

    @Test
    fun terminesLePlusRecentEnTete() {
        assertEquals(listOf("a4", "a3", "a1"), BarreAgents.termines(agents).map { it.id })
        assertEquals(emptyList<VueAgent>(), BarreAgents.termines(listOf(a("x", StatutAgent.Travaille))))
    }
}
