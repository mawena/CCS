"""Disposition du graphe façon ungit : tests portés de GiGit (src/graph.rs)."""

import time
import unittest

from ccs_app.git_graph import GEdge, layout
from ccs_app.git_repo import Commit, Ref


def c(cid, parents, t):
    return Commit(cid, list(parents), "", "", t, "")


def r(name, kind, target):
    return Ref(name, kind, target)


def head(target):
    return r("HEAD", "head", target)


def node(l, commits, cid):
    i = l.index[cid]
    assert commits[l.nodes[i].commit].id == cid
    return l.nodes[i]


BRANCHED = [c("f2", ["f1"], 6), c("m2", ["m1"], 5), c("f1", ["base"], 4),
            c("m1", ["base"], 3), c("base", [], 1)]
BRANCHED_REFS = [head("m2"), r("main", "branch", "m2"), r("feature", "branch", "f2")]


class GraphTest(unittest.TestCase):
    def test_linear_history_is_main_line(self):
        cs = [c("c", ["b"], 3), c("b", ["a"], 2), c("a", [], 1)]
        l = layout(cs, [head("c"), r("main", "branch", "c")])
        self.assertEqual(len(l.nodes), 3)
        self.assertTrue(all(n.main and n.slot == 0 for n in l.nodes))
        self.assertEqual([n.y for n in l.nodes], [0.0, 2.0, 4.0])
        self.assertEqual(l.edges, [GEdge(0, 1), GEdge(1, 2)])
        self.assertEqual(l.nodes[0].branch, "main")

    def test_unmerged_branch_goes_to_its_own_column(self):
        l = layout(BRANCHED, BRANCHED_REFS)
        f2 = node(l, BRANCHED, "f2")
        self.assertFalse(f2.main)
        self.assertEqual((f2.slot, f2.branch), (1, "feature"))
        self.assertTrue(node(l, BRANCHED, "m2").main)
        self.assertTrue(node(l, BRANCHED, "base").main)
        self.assertEqual(l.max_slot, 1)

    def test_y_spacing_follows_ungit(self):
        l = layout(BRANCHED, BRANCHED_REFS)
        self.assertEqual([n.y for n in l.nodes], [0.0, 1.0, 2.0, 3.0, 5.0])
        self.assertEqual(l.height, 5.0)

    def test_unreferenced_commits_are_dropped(self):
        cs = [c("s", ["b"], 9), c("b", ["a"], 2), c("a", [], 1)]
        l = layout(cs, [head("b"), r("main", "branch", "b")])
        self.assertEqual(len(l.nodes), 2)
        self.assertNotIn("s", l.index)

    def test_older_branch_claims_shared_history_first(self):
        cs = [c("n", ["base"], 5), c("o", ["base"], 3), c("base", [], 1)]
        l = layout(cs, [r("new", "branch", "n"), r("old", "branch", "o")])
        self.assertEqual(node(l, cs, "base").branch, "old")
        self.assertEqual(node(l, cs, "n").branch, "new")

    def test_local_branches_win_over_remote_and_tags(self):
        cs = [c("a", [], 1)]
        l = layout(cs, [r("v1", "tag", "a"), r("origin/main", "remote", "a"), r("main", "branch", "a")])
        self.assertEqual(l.nodes[0].branch, "main")

    def test_merge_edges_reach_both_parents(self):
        cs = [c("m", ["a", "b"], 3), c("b", ["a"], 2), c("a", [], 1)]
        l = layout(cs, [head("m"), r("main", "branch", "m")])
        im, ia, ib = l.index["m"], l.index["a"], l.index["b"]
        for e in (GEdge(im, ia), GEdge(im, ib), GEdge(ib, ia)):
            self.assertIn(e, l.edges)
        self.assertFalse(node(l, cs, "b").main)

    def test_no_head_means_no_main_line(self):
        l = layout([c("a", [], 1)], [r("x", "branch", "a")])
        self.assertFalse(l.nodes[0].main)
        self.assertEqual(l.nodes[0].slot, 0)

    def test_parent_outside_page_is_ignored(self):
        cs = [c("b", ["a"], 2)]          # « a » sera sur la page suivante
        l = layout(cs, [head("b"), r("main", "branch", "b")])
        self.assertEqual((len(l.nodes), l.edges), (1, []))

    def test_layout_10k_linear_under_200ms(self):
        n = 10_000
        ids = [str(i) for i in range(n)]
        commits = [c(ids[i], [ids[i + 1]] if i + 1 < n else [], n - i) for i in range(n)]
        refs = [head("0"), r("main", "branch", "0")]
        start = time.perf_counter()
        l = layout(commits, refs)
        elapsed = time.perf_counter() - start
        self.assertEqual(len(l.nodes), n)
        self.assertLess(elapsed, 0.2, f"{elapsed:.3f} s")


if __name__ == "__main__":
    unittest.main()
