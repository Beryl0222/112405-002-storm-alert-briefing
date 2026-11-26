"""地名登记：跨语种译名合并、不重复建点、误写容错。"""

import unittest

from storm_nlp.places import Place, PlaceKind, PlaceRegistry


class PlaceRegistryTest(unittest.TestCase):
    def setUp(self):
        self.registry = PlaceRegistry.from_dicts([
            {
                "id": "P-1", "name": "北湾避护中心", "kind": PlaceKind.SHELTER,
                "aliases": ["North Bay Shelter"],
            },
            {
                "id": "P-2", "name": "临港大桥", "kind": PlaceKind.GATE,
                "aliases": ["Lingang Bridge"],
            },
        ])

    def test_two_translations_resolve_to_same_place(self):
        # 同一地点的英文译名与中文名必须解析为同一个 place_id
        self.assertEqual(
            self.registry.resolve("北湾避护中心"),
            self.registry.resolve("North Bay Shelter"),
        )

    def test_duplicate_registration_merges_alias_instead_of_creating_place(self):
        before = len(self.registry.all())
        record = self.registry.register(
            Place("P-NEW", "North Haven Shelter", PlaceKind.SHELTER, aliases=["North Bay Shelter"])
        )
        self.assertIsNotNone(record)
        self.assertEqual(record.target_place_id, "P-1")
        self.assertEqual(len(self.registry.all()), before)  # 没有新增地点
        self.assertEqual(self.registry.resolve("North Haven Shelter"), "P-1")

    def test_learn_alias_keeps_single_place(self):
        record = self.registry.learn_alias("P-1", "北湾临时点")
        self.assertEqual(record.target_place_id, "P-1")
        self.assertEqual(self.registry.resolve("北湾临时点"), "P-1")

    def test_fuzzy_resolve_minor_typo(self):
        self.assertEqual(self.registry.resolve("临港大桥 "), "P-2")
        self.assertEqual(self.registry.resolve("Lingang Brige"), "P-2")

    def test_unknown_mention_returns_none(self):
        self.assertIsNone(self.registry.resolve("火星避难所"))


if __name__ == "__main__":
    unittest.main()
