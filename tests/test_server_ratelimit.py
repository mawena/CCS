"""Limite des essais : 5 échecs en 15 min → refus pendant 15 min."""

import unittest

from ccs_app.server.ratelimit import Limiter


class LimiterTest(unittest.TestCase):
    def test_limiter_blocks_after_five(self):
        lim = Limiter()
        for i in range(4):
            lim.failure("alice", 100 + i)
            self.assertFalse(lim.blocked("alice", 100 + i))
        lim.failure("alice", 110)
        self.assertTrue(lim.blocked("alice", 111))
        self.assertFalse(lim.blocked("bob", 111))

    def test_limiter_unblocks_after_block(self):
        lim = Limiter()
        for i in range(5):
            lim.failure("ip:1.2.3.4", 1000 + i)
        self.assertTrue(lim.blocked("ip:1.2.3.4", 1004 + 899))
        self.assertFalse(lim.blocked("ip:1.2.3.4", 1004 + 901))
        lim.failure("ip:1.2.3.4", 1004 + 902)          # compteur reparti de zéro
        self.assertFalse(lim.blocked("ip:1.2.3.4", 1004 + 903))

    def test_limiter_window_slides(self):
        lim = Limiter()
        for t in (0, 200, 300, 400):
            lim.failure("x", t)
        lim.failure("x", 1000)                         # le premier échec est sorti de la fenêtre
        self.assertFalse(lim.blocked("x", 1001))
        lim.failure("x", 1001)
        self.assertTrue(lim.blocked("x", 1002))

    def test_success_clears(self):
        lim = Limiter()
        for t in range(4):
            lim.failure("x", t)
        lim.success("x")
        lim.failure("x", 5)
        self.assertFalse(lim.blocked("x", 6))

    def test_memory_bounded(self):
        lim = Limiter(max_keys=100)
        for i in range(1000):
            lim.failure(f"u:{i}", float(i))
        self.assertLessEqual(len(lim._failures), 100)
        for t in range(4):
            lim.failure("x", 2000 + t)
        lim.failure("x", 2004)
        self.assertTrue(lim.blocked("x", 2005))                 # un blocage en cours n'est jamais oublié

    def test_retry_after(self):
        lim = Limiter()
        for t in range(5):
            lim.failure("x", 10)
        self.assertEqual(lim.retry_after("x", 100), 810)
        self.assertEqual(lim.retry_after("y", 100), 0)


if __name__ == "__main__":
    unittest.main()
