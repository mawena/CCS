package com.mawena.ccs.reseau

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.longOrNull
import kotlinx.serialization.json.put

/**
 * Messages du WebSocket `/api/ws` (voir `ccs_app/server/web.py`), une trame texte JSON chacun :
 * - appel :     `{"id": 7, "method": "accounts.cards", "params": {…}}`
 * - réponse :   `{"id": 7, "result": {…}}` ou `{"id": 7, "error": {"code": "…", "message": "…"}}`
 * - événement : `{"event": "chat.tags", "data": {…}}` (poussé par le pont, sans id)
 */
sealed interface MessageRpc {
    data class Resultat(val id: Long, val resultat: JsonElement) : MessageRpc
    data class Echec(val id: Long?, val code: String, val message: String) : MessageRpc
    data class Evenement(val nom: String, val donnees: JsonObject) : MessageRpc
}

class RpcException(val code: String, message: String) : Exception(message)

object CodecRpc {
    val json = Json {
        ignoreUnknownKeys = true
        explicitNulls = false
        coerceInputValues = true
    }

    private val VIDE = JsonObject(emptyMap())

    fun requete(id: Long, methode: String, params: JsonObject = VIDE): String =
        buildJsonObject {
            put("id", id)
            put("method", methode)
            put("params", params)
        }.toString()

    /** Trame reçue → message ; null si elle n'est pas comprise (ignorée, comme le fait le web). */
    fun decoder(texte: String): MessageRpc? {
        val obj = runCatching { json.parseToJsonElement(texte).jsonObject }.getOrNull() ?: return null
        val evenement = (obj["event"] as? JsonPrimitive)?.takeIf { it.isString }?.content
        if (evenement != null) {
            return MessageRpc.Evenement(evenement, obj["data"] as? JsonObject ?: VIDE)
        }
        val id = (obj["id"] as? JsonPrimitive)?.longOrNull
        val erreur = obj["error"]
        if (erreur != null && erreur !is JsonNull) {
            val e = erreur as? JsonObject
            val code = (e?.get("code") as? JsonPrimitive)?.contentOrNull ?: "erreur"
            val message = (e?.get("message") as? JsonPrimitive)?.contentOrNull ?: "Erreur du serveur."
            return MessageRpc.Echec(id, code, message)
        }
        if (id == null) return null
        val resultat = obj["result"]
        return MessageRpc.Resultat(id, if (resultat == null || resultat is JsonNull) VIDE else resultat)
    }
}
