"""道路网络：模式约束、闸口封闭与无障碍重算。"""

import unittest

from storm_nlp.dataio import load_network, load_registry
from storm_nlp.graph import RoadEdge
from storm_nlp.models import BasisRef

DATA = "data/drill"


class RoadNetworkTest(unittest.TestCase):
    def setUp(self):
        self.registry = load_registry(DATA)
        self.network = load_network(DATA, self.registry)

    def test_wheelchair_cannot_use_underpass(self):
        route = self.network.shortest_route("J-OLDTOWN", "P-SHELTER-NORTH", "wheelchair")
        self.assertTrue(route.feasible)
        self.assertNotIn("E-UNDERPASS", route.edges)

    def test_walk_uses_fastest_bridge_first(self):
        route = self.network.shortest_route("J-OLDTOWN", "P-SHELTER-NORTH", "walk")
        self.assertTrue(route.feasible)
        self.assertIn("E-LINGANG", route.edges)

    def test_closing_bridge_forces_surface_detour(self):
        self.network.close_gate(
            "P-GATE-LINGANG", BasisRef("N-02", 1, "临港大桥即刻起封闭")
        )
        route = self.network.shortest_route("J-OLDTOWN", "P-SHELTER-NORTH", "wheelchair")
        self.assertTrue(route.feasible)
        self.assertIn("E-SURFACE", route.edges)
        self.assertNotIn("E-LINGANG", route.edges)

    def test_closing_both_gates_still_leaves_feasible_walk_route(self):
        self.network.close_gate("P-GATE-LINGANG", BasisRef("N-02", 1, "桥封闭"))
        self.network.close_gate("P-GATE-UNDERPASS", BasisRef("N-05", 1, "涵洞封闭"))
        route = self.network.shortest_route("J-OLDTOWN", "P-SHELTER-NORTH", "walk")
        self.assertTrue(route.feasible)
        self.assertIn("E-SURFACE", route.edges)

    def test_ferry_mode_uses_ferry_edges(self):
        route = self.network.shortest_route(
            "P-TERMINAL-NIGHT", "P-SHELTER-NORTH", "ferry"
        )
        self.assertTrue(route.feasible)
        self.assertIn("E-FERRY", route.edges)

    def test_unknown_node_returns_unavailable(self):
        route = self.network.shortest_route("J-OLDTOWN", "P-NONE", "walk")
        self.assertFalse(route.feasible)


if __name__ == "__main__":
    unittest.main()
