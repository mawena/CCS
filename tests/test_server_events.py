"""Événements du chat en JSON et retour : le bureau distant reçoit les mêmes objets qu'en local."""

import dataclasses
import json
import unittest

from ccs_app import chat_engine, chat_protocol as proto
from ccs_app.server import events

SAMPLES = [
    proto.Init("s1", "opus", "default", ("help", "effort")),
    proto.Hello(("help",), (("opus", "Opus"), ("sonnet", "Sonnet")), "default", ("x",)),
    proto.Status("plan"), proto.LocalCommand("ok"), proto.TextDelta("m1", 0, "Bon"),
    proto.AssistantText("m1", "Bonjour", parent_id="t9"), proto.Thinking("m2"),
    proto.ToolUse("t1", "Bash", {"command": "ls", "n": [1, 2]}, None),
    proto.ToolResult("t1", "a\nb", True, "t9"), proto.TaskNotice("t2", "completed", "fini"),
    proto.Todos(({"content": "a", "status": "pending"},)),
    proto.PermissionRequest("r1", "Bash", "Commande", {"command": "rm x"}, [{"type": "rule"}],
                            "desc", "/tmp", "agent"),
    proto.ControlReply("r2", False, {"a": 1}, "erreur"),
    proto.TurnResult(True, "success", 0.5, {"in": 1}, 200000, "fin", False, True),
    proto.Compacted(1000, "auto"), proto.Retrying(2, 1.5), proto.Unknown({"type": "zzz"}),
    chat_engine.StateChanged("busy"), chat_engine.UserSent("bonjour", 1, "n1", "u-1"),
    chat_engine.TagsChanged("s1", "msg_1", {"tags": ["important"], "role": "assistant", "excerpt": "x", "ts": 1.0}),
    chat_engine.ContextUsage(12, 24000, 200000, True),
    chat_engine.OptionRefused("model", "non"), chat_engine.UnhandledRequest("x", "y"),
    chat_engine.ProcessExited(1, "trace", True), events.PermissionSettled("r1", "allow"),
    events.Notice("Compactage automatique : contexte de 152 000 jetons.", "warning"),
]


class EventsTest(unittest.TestCase):
    def test_round_trip_every_event_type(self):
        seen = set()
        for ev in SAMPLES:
            d = events.to_json(ev)
            json.dumps(d)                                   # sérialisable tel quel
            self.assertEqual(d["type"], type(ev).__name__)
            back = events.from_json(json.loads(json.dumps(d)))
            self.assertEqual(back, ev, type(ev).__name__)
            seen.add(type(ev).__name__)
        self.assertEqual(seen, set(events.TYPES))           # chaque type connu a un exemple

    def test_context_usage_from_an_older_bridge(self):
        """Pont d'avant le compactage automatique : pas de champ `auto_compact`, donc faux."""
        back = events.from_json({"type": "ContextUsage", "percentage": 80, "total": 160000, "maximum": 200000})
        self.assertEqual(back, chat_engine.ContextUsage(80, 160000, 200000, False))

    def test_unknown_type_is_unknown(self):
        back = events.from_json({"type": "Inconnu", "a": 1})
        self.assertIsInstance(back, proto.Unknown)
        self.assertEqual(back.raw["a"], 1)

    def test_bad_fields_are_unknown(self):
        back = events.from_json({"type": "TextDelta", "msg_id": "m"})   # champs manquants
        self.assertIsInstance(back, proto.Unknown)

    def test_types_cover_engine_events(self):
        for mod in (proto, chat_engine):
            for name, obj in vars(mod).items():
                if dataclasses.is_dataclass(obj) and isinstance(obj, type) and \
                        obj.__module__ == mod.__name__ and name not in ("ChatSession",):
                    self.assertIn(name, events.TYPES)


if __name__ == "__main__":
    unittest.main()
