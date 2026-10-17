import json
import math
from pathlib import Path
import tempfile
import unittest
from collections import deque

from rpg_core import (CAMP, CHESTS, ELDER, MERCHANT, PORTAL, SHRINES, SPAWN,
                      WORLD_W, WORLD_H, Player, Progress, SaveStore, World,
                      decode_save, encode_save, make_enemies)


class RulesTests(unittest.TestCase):
    def test_multiple_levels_restore_health_and_keep_remainder(self):
        p = Player(hp=8, mana=0)
        self.assertEqual(p.gain_xp(240), 2)
        self.assertEqual((p.level, p.xp, p.hp, p.mana), (3, 30, 136, 100))

    def test_armour_and_potions(self):
        p = Player(armour=3)
        self.assertAlmostEqual(p.take_damage(20), 10.4)
        self.assertTrue(p.heal())
        self.assertEqual(p.hp, p.max_hp)
        self.assertEqual(p.potions, 2)
        self.assertFalse(p.heal())
        p.take_damage(9999)
        self.assertEqual(p.hp, 0)

    def test_save_roundtrip_and_atomic_file(self):
        p = Player(gold=83, level=3, xp=12, hp=112, armour=2)
        p.sword.tier = 2
        q = Progress(True, {1}, {"wild-0", "shrine-1-0", "shrine-1-1", "shrine-1-2"}, {0}, False, 156)
        with tempfile.TemporaryDirectory() as tmp:
            store = SaveStore(Path(tmp) / "nested" / "save.json")
            self.assertTrue(store.write(p, q))
            loaded, progress = store.read()
            self.assertEqual(loaded, p)
            self.assertEqual(progress, q)
            self.assertFalse(store.path.with_suffix(".tmp").exists())
            store.path.write_text("incomplete save", encoding="utf-8")
            self.assertIsNone(store.read())

    def test_corrupt_and_untrusted_save_fields(self):
        for bad in ("", "null", "[]", "{", '{"version":2}', '{"version":1,"player":[],"progress":{}}'):
            self.assertIsNone(decode_save(bad))
        raw = json.loads(encode_save(Player(), Progress()))
        raw["player"].update({"x": float("inf"), "hp": float("nan"), "gold": -8, "armour": 90, "sword": -99})
        raw["progress"].update({"crystals": [0, 99, "bad"], "opened": [0, 99], "won": True})
        p, q = decode_save(json.dumps(raw))
        self.assertTrue(math.isfinite(p.x))
        self.assertEqual((p.gold, p.armour, p.sword.tier), (0, 3, 0))
        self.assertEqual(q.crystals, {0})
        self.assertFalse(q.won)

    def test_save_unwritable_path_is_nonfatal(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp) / "not-a-directory"
            parent.write_text("file")
            store = SaveStore(parent / "save.json")
            self.assertFalse(store.write(Player(), Progress()))
            self.assertTrue(store.error)

    def test_defeated_enemies_do_not_respawn_on_load(self):
        q = Progress(defeated={"wild-0", "boss", "shrine-1-2"})
        ids = {e.id for e in make_enemies(q)}
        self.assertFalse(ids & q.defeated)
        self.assertEqual(len(ids), 15)


class NavigationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world = World()

    def test_every_objective_is_walkable_and_reachable(self):
        # Flood fill actual collision geometry at a 24px resolution. Checking
        # just landmark positions would miss an impassable ring of trees.
        step = 24
        start = (round(SPAWN[0] / step), round(SPAWN[1] / step))
        queue, seen = deque([start]), {start}
        while queue:
            x, y = queue.popleft()
            for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if (nx, ny) in seen or not (0 <= nx <= WORLD_W // step and 0 <= ny <= WORLD_H // step):
                    continue
                if self.world.blocked(nx * step, ny * step):
                    continue
                seen.add((nx, ny))
                queue.append((nx, ny))
        for point in (CAMP, ELDER, MERCHANT, PORTAL, *SHRINES, *CHESTS):
            with self.subTest(point=point):
                self.assertFalse(self.world.blocked(*point))
                self.assertTrue(any(abs(x * step - point[0]) < 48 and abs(y * step - point[1]) < 48 for x, y in seen))

    def test_dash_cannot_tunnel_through_a_tree(self):
        x, y, _, _ = self.world.trees[0]
        p = Player(x=x - 55, y=y)
        self.world.move(p, 150, 0)
        self.assertLess(p.x, x)

    def test_world_is_deterministic(self):
        self.assertEqual(self.world.trees, World().trees)


if __name__ == "__main__":
    unittest.main()
