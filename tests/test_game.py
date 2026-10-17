"""Integration coverage for quest completion and interactions, with real pygame."""
import os
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

from pathlib import Path
import tempfile
import unittest
import pygame

from RPG_Game import Game
from rpg_core import CAMP, ELDER, MERCHANT, PORTAL, SHRINES, CHESTS, SPAWN, Enemy, Player, Progress, make_enemies


class GameplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.game = Game(save_path=Path(cls.tmp.name) / "save.json", headless=True)

    @classmethod
    def tearDownClass(cls):
        pygame.quit()
        cls.tmp.cleanup()

    def setUp(self):
        self.g = self.game
        self.g.new_game()
        self.g.touch = False

    def go(self, pos):
        self.g.player.x, self.g.player.y = pos

    def test_full_story_from_first_dialogue_to_persisted_ending(self):
        g = self.g
        self.go(ELDER)
        g.interact()
        self.assertEqual(g.state, "dialog")
        g.activate("back")
        for i, pos in enumerate(SHRINES):
            self.go(pos)
            g.interact()
            self.assertNotIn(i, g.progress.crystals)
            for enemy in list(g.enemies):
                if enemy.group == i:
                    g.damage_enemy(enemy, 1000)
            g.interact()
            self.assertIn(i, g.progress.crystals)
        self.assertTrue(g.progress.portal_open)
        self.go(PORTAL)
        g.interact()
        self.assertFalse(g.progress.won)
        boss = next(e for e in g.enemies if e.kind == "boss")
        g.damage_enemy(boss, 1000)
        g.interact()
        self.assertEqual(g.state, "victory")
        self.assertTrue(g.progress.won)
        _, loaded = g.store.read()
        self.assertTrue(loaded.won)
        g.resume()
        self.assertFalse(any(e.kind == "boss" for e in g.enemies))

    def test_melee_spell_and_invulnerability(self):
        g = self.g
        self.go((1152, 900))
        e = Enemy("wild-0", g.player.x + 50, g.player.y)
        g.enemies = [e]
        g.attack()
        self.assertEqual(e.hp, e.max_hp - g.player.damage)
        g.attack()  # cooldown must prevent a second immediate hit
        self.assertEqual(e.hp, e.max_hp - g.player.damage)
        g.spell()
        self.assertEqual(g.player.mana, 78)
        for _ in range(25):
            g.update(1 / 60)
        self.assertIn("wild-0", g.progress.defeated)
        before = g.player.hp
        g.dash()
        g.hurt_player(50)
        self.assertEqual(g.player.hp, before)

    def test_actions_do_not_release_held_movement_keys(self):
        g = self.g
        g.keys.add(pygame.K_d)
        for action in ("spell", "attack", "dash", "heal"):
            g.activate(action)
            self.assertIn(pygame.K_d, g.keys)
        g.activate("map")
        self.assertFalse(g.keys)

    def test_ukrainian_keyboard_uses_physical_wasd_keys(self):
        g = self.g
        event = pygame.event.Event(pygame.KEYDOWN, key=ord("ц"), scancode=pygame.KSCAN_W)
        g.input([event])
        before = g.player.y
        g.update(.05)
        self.assertLess(g.player.y, before)
        g.input([pygame.event.Event(pygame.KEYUP, key=ord("ц"), scancode=pygame.KSCAN_W)])
        self.assertFalse(g.keys)

    def test_purchases_charge_once_and_enforce_limits(self):
        g = self.g
        g.buy("sword")
        self.assertEqual(g.player.sword.tier, 0)
        g.player.gold = 1000
        for _ in range(4):
            g.buy("sword")
        self.assertEqual(g.player.sword.tier, 3)
        self.assertEqual(g.player.gold, 760)
        for _ in range(4):
            g.buy("armour")
        self.assertEqual(g.player.armour, 3)
        self.assertEqual(g.player.gold, 550)

    def test_chest_cannot_be_farmed_and_camp_restores_supplies(self):
        g = self.g
        self.go(CHESTS[0])
        g.interact()
        g.interact()
        self.assertEqual(g.player.gold, 30)
        self.assertEqual(g.player.potions, 4)
        self.go(CAMP)
        g.player.hp, g.player.mana, g.player.potions = 2, 0, 0
        g.interact()
        self.assertEqual((g.player.hp, g.player.mana, g.player.potions), (100, 100, 2))

    def test_death_and_respawn_keep_progress(self):
        g = self.g
        g.progress.started = True
        g.progress.opened.add(0)
        g.player.gold = 100
        g.hurt_player(9999)
        self.assertEqual(g.state, "dead")
        g.respawn()
        self.assertEqual(g.state, "playing")
        self.assertEqual(g.player.gold, 85)
        self.assertEqual(g.player.pos, SPAWN)
        self.assertEqual(g.progress.opened, {0})
        self.assertEqual(g.player.hp, g.player.max_hp)

    def test_focus_loss_pauses_and_clears_input(self):
        g = self.g
        g.keys.add(pygame.K_w)
        g.input([pygame.event.Event(pygame.WINDOWFOCUSLOST)])
        self.assertEqual(g.state, "pause")
        self.assertFalse(g.keys)
        time_before = g.progress.play_time
        g.update(1)
        self.assertEqual(g.progress.play_time, time_before)

    def test_all_screens_render_and_buttons_stay_inside_viewport(self):
        g = self.g
        for state in ("menu", "playing", "pause", "help", "inventory", "shop", "map", "dialog", "dead", "victory", "confirm"):
            with self.subTest(state=state):
                g.state = state
                g.draw()
                self.assertTrue(g.buttons)
                for rect, action in g.buttons:
                    self.assertTrue(pygame.Rect(0, 0, 1152, 720).contains(rect), (state, action, rect))

    def test_multitouch_joystick_keeps_moving_while_attacking(self):
        g = self.g
        g.touch = True
        g.draw()
        g.input([pygame.event.Event(pygame.FINGERDOWN, finger_id=1, x=170 / 1152, y=608 / 720),
                 pygame.event.Event(pygame.FINGERDOWN, finger_id=2, x=1070 / 1152, y=595 / 720)])
        before = g.player.x
        g.update(.05)
        self.assertGreater(g.player.x, before)
        g.input([pygame.event.Event(pygame.FINGERUP, finger_id=1, x=170 / 1152, y=608 / 720)])
        before = g.player.x
        g.update(.05)
        self.assertEqual(g.player.x, before)


if __name__ == "__main__":
    unittest.main()
