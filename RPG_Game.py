"""Ліс відлунь — a complete, small Python / pygame-ce action RPG.

Run: python RPG_Game.py. Web entry point: main.py; build: python scripts/build_web.py.
All art other than the supplied hero and bundled fonts is drawn by this module.
"""
import asyncio
from array import array
from collections import OrderedDict
import math
from pathlib import Path
import random
import sys

import pygame

from rpg_core import (CAMP, CHESTS, ELDER, MERCHANT, PORTAL, SHRINES, SHRINE_NAMES,
                      SPAWN, TILE, WORLD_H, WORLD_W, Enemy, Player, Progress,
                      SaveStore, World, clamp, distance, make_enemies, unit)

W, H = 1152, 720
ROOT = Path(__file__).resolve().parent
INK = (14, 27, 29)
PANEL = (20, 37, 39)
LINE = (56, 79, 76)
TEXT = (239, 241, 220)
MUTED = (149, 174, 160)
MINT = (168, 215, 151)
CYAN = (109, 223, 222)
GOLD = (234, 197, 122)
RED = (239, 129, 121)


class Audio:
    """Small synthesized sound effects; audio failure never blocks play."""
    def __init__(self):
        self.enabled = True
        self.sounds = {}
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init(22050, -16, 1, 512)
            rate, _, channels = pygame.mixer.get_init()
            for name, hz, duration in (("hit", 180, .09), ("spell", 640, .18),
                                       ("coin", 1100, .1), ("heal", 520, .25),
                                       ("hurt", 95, .13), ("level", 880, .32),
                                       ("dash", 230, .08), ("click", 400, .04)):
                samples = array("h")
                count = int(rate * duration)
                for i in range(count):
                    t = i / rate
                    envelope = (1 - i / count) ** 2
                    value = int(math.sin(math.tau * hz * t * (1 + t * 1.5)) * 3500 * envelope)
                    samples.extend([value] * channels)
                self.sounds[name] = pygame.mixer.Sound(buffer=samples)
        except (pygame.error, ValueError):
            self.sounds.clear()

    def play(self, name):
        if self.enabled and name in self.sounds:
            self.sounds[name].play()


class Game:
    def __init__(self, save_path=None, headless=False):
        pygame.mixer.pre_init(22050, -16, 1, 512)
        pygame.init()
        self.window = pygame.display.set_mode((W, H), pygame.RESIZABLE)
        pygame.display.set_caption("Ліс відлунь · Echo Forest")
        self.screen = pygame.Surface((W, H)).convert()
        self.fonts = {}
        self.text_cache = OrderedDict()
        self.glows = {}
        original = pygame.image.load(str(ROOT / "assets" / "hero.jpeg")).convert()
        iw, ih = original.get_size()
        # The supplied illustration contains the hero in its center. Crop only
        # while rendering, retaining the user's complete original asset on disk.
        crop = pygame.Rect(round(iw * .346), round(ih * .217), round(iw * .309), round(ih * .566))
        self.hero = pygame.transform.smoothscale(original.subsurface(crop), (160, 160)).convert_alpha()
        mask = pygame.Surface((160, 160), pygame.SRCALPHA)
        pygame.draw.rect(mask, (255, 255, 255), mask.get_rect(), border_radius=13)
        self.hero.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
        self.hero_sizes = {n: pygame.transform.smoothscale(self.hero, (n, n)) for n in (28, 36, 40, 48, 64, 128, 160)}
        pygame.display.set_icon(self.hero_sizes[36])
        self.world = World()
        self.ground = self.make_ground()
        self.tree_sprites = {}
        self.store = SaveStore(save_path)
        self.saved = self.store.read()
        self.player, self.progress = Player(), Progress()
        self.enemies = make_enemies(self.progress)
        self.rng = random.Random(97)
        self.audio = Audio()
        self.clock = pygame.time.Clock()
        self.running = True
        self.state = "menu"
        self.previous_state = "playing"
        self.buttons = []
        self.keys = set()
        self.mouse = (-1, -1)
        self.touch = False
        self.fingers = {}
        self.touch_move = (0, 0)
        self.facing = (1, 0)
        self.camera = [SPAWN[0] - W / 2, SPAWN[1] - H / 2]
        self.t = 0
        self.autosave = 0
        self.attack_cd = self.spell_cd = self.dash_cd = self.dash_time = self.invulnerable = 0
        self.dash_vector = (1, 0)
        self.slash = 0
        self.shake = 0
        self.projectiles = []
        self.particles = []
        self.numbers = []
        self.toasts = []
        self.dialog = ("", [])
        self.focused = True
        self.headless = headless
        self.web_last_state = None
        if sys.platform == "emscripten":
            import platform
            # Some pygbag runtimes start main.py before custom_site finishes.
            # Hide the loader only after all game assets have actually loaded.
            platform.window.infobox.style.display = "none"
            platform.window.canvas.setAttribute("data-game-ready", "true")

    def font(self, size, bold=False):
        key = (size, bold)
        if key not in self.fonts:
            name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
            self.fonts[key] = pygame.font.Font(str(ROOT / "assets" / "fonts" / name), size)
        return self.fonts[key]

    def text(self, value, x, y, size=16, color=TEXT, bold=False, center=False, target=None):
        key = (str(value), size, color, bold)
        if key not in self.text_cache:
            self.text_cache[key] = self.font(size, bold).render(str(value), True, color)
            if len(self.text_cache) > 700:
                self.text_cache.popitem(last=False)
        surf = self.text_cache[key]
        (target or self.screen).blit(surf, (int(x - surf.get_width() / 2) if center else int(x), int(y)))
        return surf.get_width()

    def wrap(self, text, x, y, width, size=17, color=MUTED, line=28):
        words, row = text.split(), ""
        for word in words:
            test = f"{row} {word}".strip()
            if self.font(size).size(test)[0] > width and row:
                self.text(row, x, y, size, color)
                y += line
                row = word
            else:
                row = test
        if row:
            self.text(row, x, y, size, color)
            y += line
        return y

    def panel(self, rect, color=PANEL, border=LINE, radius=14, alpha=245):
        rect = pygame.Rect(rect)
        surface = pygame.Surface(rect.size, pygame.SRCALPHA)
        pygame.draw.rect(surface, (*color, alpha), surface.get_rect(), border_radius=radius)
        if border:
            pygame.draw.rect(surface, (*border, min(255, alpha)), surface.get_rect(), width=1, border_radius=radius)
        self.screen.blit(surface, rect)

    def button(self, rect, label, action, primary=False, disabled=False, size=17):
        rect = pygame.Rect(rect)
        hover = rect.collidepoint(self.mouse) and not disabled
        fill = MINT if primary else (39, 59, 56) if hover else (27, 44, 44)
        if disabled:
            fill = (29, 43, 42)
        self.panel(rect, fill, MINT if hover else LINE, 9)
        self.text(label, rect.centerx, rect.y + (rect.height - size) / 2 - 2, size,
                  INK if primary else (84, 108, 98) if disabled else TEXT, True, True)
        if not disabled:
            self.buttons.append((rect, action))

    def glow(self, pos, radius, color, target=None):
        key = (radius, color)
        if key not in self.glows:
            surf = pygame.Surface((radius * 2, radius * 2)).convert()
            surf.fill((0, 0, 0))
            for r in range(radius, 0, -4):
                power = (1 - r / radius) ** 1.9 * .22
                pygame.draw.circle(surf, tuple(int(c * power) for c in color), (radius, radius), r)
            self.glows[key] = surf
        (target or self.screen).blit(self.glows[key], (int(pos[0] - radius), int(pos[1] - radius)), special_flags=pygame.BLEND_RGB_ADD)

    def make_ground(self):
        surf = pygame.Surface((WORLD_W, WORLD_H)).convert()
        rng = random.Random(42)
        for y in range(0, WORLD_H, TILE):
            for x in range(0, WORLD_W, TILE):
                shade = rng.randrange(-3, 4)
                pygame.draw.rect(surf, (32 + shade, 58 + shade, 49 + shade), (x, y, TILE, TILE))
        for a, b in self.world.paths:
            pygame.draw.line(surf, (47, 67, 52), a, b, 100)
            pygame.draw.line(surf, (68, 78, 58), a, b, 64)
            pygame.draw.circle(surf, (68, 78, 58), a, 32)
            pygame.draw.circle(surf, (68, 78, 58), b, 32)
        pygame.draw.circle(surf, (53, 75, 56), CAMP, 235)
        pygame.draw.circle(surf, (70, 82, 60), CAMP, 158)
        for _ in range(19000):
            x, y = rng.randrange(WORLD_W), rng.randrange(WORLD_H)
            color = rng.choice(((45, 76, 59), (53, 82, 62), (37, 66, 52), (70, 87, 63)))
            pygame.draw.line(surf, color, (x, y), (x + rng.randrange(-2, 3), y - rng.randrange(1, 5)))
        for x, y, rx, ry in self.world.ponds:
            for grow, color in ((16, (59, 85, 64)), (7, (35, 68, 62)), (0, (28, 64, 67)), (-12, (28, 59, 65))):
                pygame.draw.ellipse(surf, color, (x - rx - grow, y - ry - grow, (rx + grow) * 2, (ry + grow) * 2))
            for _ in range(25):
                px, py = x + rng.randrange(-rx + 20, rx - 20), y + rng.randrange(-ry + 20, ry - 20)
                if ((px - x) / (rx - 15)) ** 2 + ((py - y) / (ry - 15)) ** 2 < 1:
                    pygame.draw.line(surf, (47, 92, 88), (px, py), (px + 12, py), 1)
        for x, y in SHRINES:
            pygame.draw.circle(surf, (40, 61, 54), (x, y), 122)
            pygame.draw.circle(surf, (77, 95, 75), (x, y), 96, 2)
            for i in range(12):
                a = i * math.tau / 12
                xx, yy = int(x + math.cos(a) * 95), int(y + math.sin(a) * 95)
                pygame.draw.rect(surf, (100, 112, 89), (xx - 5, yy - 5, 10, 10), border_radius=2)
        for _ in range(210):
            x, y = rng.randrange(70, WORLD_W - 70), rng.randrange(70, WORLD_H - 70)
            if not self.world.water(x, y):
                for dx, dy in ((-3, 0), (3, 0), (0, -3)):
                    pygame.draw.circle(surf, rng.choice(((134, 161, 104), (161, 172, 119), (104, 151, 135))), (x + dx, y + dy), 2)
        return surf

    def new_game(self):
        self.player, self.progress = Player(), Progress()
        self.reset_transient()
        self.state = "playing"
        self.save()
        self.toast("Ласкаво просимо до Лісу відлунь", MINT)
        self.toast("WASD — рух · E — поговорити з хранителькою", MUTED)

    def resume(self):
        saved = self.store.read()
        if saved:
            self.player, self.progress = saved
            self.reset_transient()
            self.state = "playing"
            self.toast("Подорож продовжується", MINT)

    def reset_transient(self):
        self.enemies = make_enemies(self.progress)
        self.projectiles.clear()
        self.particles.clear()
        self.numbers.clear()
        self.toasts.clear()
        self.keys.clear()
        self.fingers.clear()
        self.attack_cd = self.spell_cd = self.dash_cd = self.dash_time = self.invulnerable = 0
        self.slash = self.shake = self.autosave = 0
        self.camera = [self.player.x - W / 2, self.player.y - H / 2]

    def save(self):
        if self.store.write(self.player, self.progress):
            self.saved = (self.player, self.progress)
            return True
        self.toast("Збереження недоступне. Перевірте доступ до сховища.", RED)
        return False

    def toast(self, message, color=TEXT):
        self.toasts.append([message, color, 4.0])
        self.toasts = self.toasts[-3:]

    def burst(self, x, y, color, count=12):
        for _ in range(count):
            a, speed = self.rng.random() * math.tau, self.rng.uniform(35, 150)
            life = self.rng.uniform(.3, .7)
            self.particles.append([x, y, math.cos(a) * speed, math.sin(a) * speed, life, life, color])

    def number(self, text, x, y, color):
        self.numbers.append([str(text), x, y - 30, 1, color])

    def reward_xp(self, amount):
        if self.player.gain_xp(amount):
            self.toast(f"Новий рівень: {self.player.level} · здоров'я відновлено", GOLD)
            self.burst(*self.player.pos, GOLD, 35)
            self.audio.play("level")

    def damage_enemy(self, enemy, damage):
        if enemy.hp <= 0 or (enemy.kind == "boss" and not self.progress.portal_open):
            return
        enemy.hp -= damage
        enemy.flash = .16
        self.number(int(damage), enemy.x, enemy.y, GOLD)
        self.burst(enemy.x, enemy.y, GOLD, 6)
        self.audio.play("hit")
        if enemy.hp <= 0:
            self.progress.defeated.add(enemy.id)
            gold = 80 if enemy.kind == "boss" else 20 if enemy.kind == "guardian" else 12
            self.player.gold += gold
            self.reward_xp(150 if enemy.kind == "boss" else 32 if enemy.kind == "guardian" else 20)
            self.burst(enemy.x, enemy.y, CYAN, 20)
            self.number(f"+{gold} зол.", enemy.x, enemy.y + 26, GOLD)
            if enemy.kind == "guardian":
                self.player.potions = min(99, self.player.potions + 1)
                self.toast("Зілля знайдено · F — відновити здоров'я", MINT)
            if enemy.kind == "boss":
                self.toast("Вартового переможено. Активуйте браму клавішею E!", GOLD)
            self.save()

    def hurt_player(self, amount):
        if self.invulnerable > 0 or self.state != "playing":
            return
        actual = self.player.take_damage(amount)
        self.invulnerable = .65
        self.shake = .2
        self.number(int(actual), *self.player.pos, RED)
        self.audio.play("hurt")
        if self.player.hp <= 0:
            self.state = "dead"
            self.keys.clear()

    def attack(self, aim=None):
        if self.attack_cd > 0 or self.state != "playing":
            return
        if aim:
            self.facing = unit(aim[0] - self.player.x, aim[1] - self.player.y)
        else:
            candidates = [e for e in self.enemies if e.hp > 0 and distance(e.pos, self.player.pos) < 110
                          and (e.kind != "boss" or self.progress.portal_open)]
            if candidates:
                target = min(candidates, key=lambda e: distance(e.pos, self.player.pos))
                self.facing = unit(target.x - self.player.x, target.y - self.player.y)
        self.attack_cd, self.slash = .34, .2
        self.audio.play("hit")
        for e in self.enemies:
            d = distance(e.pos, self.player.pos)
            nx, ny = unit(e.x - self.player.x, e.y - self.player.y)
            if d < 88 + e.radius and (nx * self.facing[0] + ny * self.facing[1] > -.15 or d < 38):
                self.damage_enemy(e, self.player.damage)
                if e.kind != "boss":
                    self.world.move(e, nx * 18, ny * 18, e.radius)

    def spell(self):
        if self.spell_cd > 0 or self.state != "playing":
            return
        if self.player.mana < 22:
            self.toast("Недостатньо мани — вона відновлюється", CYAN)
            return
        targets = [e for e in self.enemies if e.hp > 0 and distance(e.pos, self.player.pos) < 440
                   and (e.kind != "boss" or self.progress.portal_open)]
        direction = self.facing
        if targets:
            target = min(targets, key=lambda e: distance(e.pos, self.player.pos))
            direction = unit(target.x - self.player.x, target.y - self.player.y)
        self.player.mana -= 22
        self.spell_cd = .65
        self.projectiles.append([self.player.x, self.player.y, direction[0] * 460, direction[1] * 460, 1.3, True, 42 + self.player.level * 6])
        self.audio.play("spell")

    def dash(self):
        if self.dash_cd <= 0 and self.state == "playing":
            self.dash_cd, self.dash_time = 1.25, .18
            self.invulnerable = max(self.invulnerable, .32)
            self.dash_vector = self.facing
            self.audio.play("dash")

    def heal(self):
        if self.player.heal():
            self.burst(*self.player.pos, MINT, 24)
            self.audio.play("heal")
            self.save()
        else:
            self.toast("Здоров'я вже повне" if self.player.hp >= self.player.max_hp else "Немає зілля. Завітайте до крамаря.", MUTED)

    def nearby(self):
        objects = [("elder", ELDER, 88, "Поговорити"), ("shop", MERCHANT, 88, "Крамниця"),
                   ("camp", CAMP, 76, "Відпочити"), ("portal", PORTAL, 98, "Брама світанку")]
        objects += [(f"shrine:{i}", p, 92, "Пробудити джерело" if i not in self.progress.crystals else "Джерело пробуджене") for i, p in enumerate(SHRINES)]
        objects += [(f"chest:{i}", p, 72, "Відкрити скриню") for i, p in enumerate(CHESTS) if i not in self.progress.opened]
        options = [o for o in objects if distance(self.player.pos, o[1]) < o[2]]
        return min(options, key=lambda o: distance(self.player.pos, o[1])) if options else None

    def interact(self):
        obj = self.nearby()
        if not obj:
            self.toast("Підійдіть ближче до персонажа, скрині або джерела", MUTED)
            return
        kind = obj[0]
        if kind == "elder":
            self.progress.started = True
            if self.progress.won:
                lines = ["Ти повернув лісу його голос. Навіть найменше світло може змінити цілий світ.", "Дякую, мандрівнику. Наше вогнище завжди чекатиме на тебе."]
            elif self.progress.portal_open:
                lines = ["Три джерела знову співають! Але на північному сході ще стоїть Вартовий тіні.", "Іди до брами, здолай його та поверни світло. На мапі позначено шлях."]
            else:
                lines = ["Колись цей ліс світився зсередини. Тепер тінь полонила три його джерела.", "Здолай істот біля кожного джерела, а тоді натисни E, щоб його пробудити. Разом ми відкриємо Браму світанку.", "Стежки приведуть тебе до мети. Tab відкриває мапу. Біля вогнища можна відновити сили."]
            self.dialog = ("МІРА · ХРАНИТЕЛЬКА ЛІСУ", lines)
            self.state = "dialog"
            self.save()
        elif kind == "shop":
            self.state = "shop"
        elif kind == "camp":
            self.player.hp, self.player.mana = self.player.max_hp, 100
            self.player.potions = max(2, self.player.potions)
            self.save()
            self.burst(*self.player.pos, GOLD, 22)
            self.toast("Сили відновлено · щонайменше 2 зілля · прогрес збережено", GOLD)
            self.audio.play("heal")
        elif kind.startswith("chest:"):
            i = int(kind.split(":")[1])
            self.progress.opened.add(i)
            self.player.gold += 30
            self.player.potions = min(99, self.player.potions + 1)
            self.reward_xp(12)
            self.save()
            self.audio.play("coin")
            self.burst(*CHESTS[i], GOLD, 20)
            self.toast("Знайдено: 30 золота та зілля здоров'я", GOLD)
        elif kind.startswith("shrine:"):
            i = int(kind.split(":")[1])
            if i in self.progress.crystals:
                self.toast("Це джерело вже сяє", CYAN)
            elif any(e.group == i and e.hp > 0 for e in self.enemies):
                self.toast("Спершу здолайте трьох охоронців цього джерела", RED)
            else:
                self.progress.started = True
                self.progress.crystals.add(i)
                self.player.gold += 40
                self.reward_xp(55)
                self.player.hp, self.player.mana = self.player.max_hp, 100
                self.save()
                self.burst(*SHRINES[i], CYAN, 60)
                self.audio.play("level")
                self.toast(f"{SHRINE_NAMES[i]} пробуджено · +40 золота", CYAN)
                if self.progress.portal_open:
                    self.toast("Браму відкрито! На північному сході чекає Вартовий.", GOLD)
        elif kind == "portal":
            if not self.progress.portal_open:
                self.toast("Брамі потрібне світло всіх трьох джерел", MUTED)
            elif "boss" not in self.progress.defeated:
                self.toast("Вартовий тіні ще охороняє браму", RED)
            else:
                self.progress.won = True
                self.save()
                self.state = "victory"
                self.audio.play("level")
        if self.state != "playing":
            self.keys.clear()

    def buy(self, kind):
        p = self.player
        price = {"potion": 20, "sword": 45 + p.sword.tier * 35, "armour": 40 + p.armour * 30}[kind]
        if (kind == "sword" and p.sword.tier >= 3) or (kind == "armour" and p.armour >= 3) or (kind == "potion" and p.potions >= 99):
            return
        if p.gold < price:
            self.toast("Недостатньо золота", GOLD)
            return
        p.gold -= price
        if kind == "potion":
            p.potions += 1
        elif kind == "sword":
            p.sword.tier += 1
        else:
            p.armour += 1
        self.audio.play("coin")
        self.save()
        self.toast("Покупку додано до спорядження", MINT)

    def respawn(self):
        self.player.gold = int(self.player.gold * .85)
        self.player.x, self.player.y = SPAWN
        self.player.hp, self.player.mana = self.player.max_hp, 100
        self.player.potions = max(2, self.player.potions)
        self.reset_transient()
        self.state = "playing"
        self.save()
        self.toast("Вогнище повернуло сили · втрачено 15% золота", GOLD)

    def activate(self, action):
        self.audio.play("click")
        if action not in ("attack", "spell", "dash", "heal", "interact"):
            self.keys.clear()
        if action == "new":
            if self.saved:
                self.state = "confirm"
            else:
                self.new_game()
        elif action == "confirm-new":
            self.new_game()
        elif action == "resume":
            self.resume()
        elif action == "back":
            self.state = self.previous_state if self.state == "help" else "playing"
        elif action == "help":
            self.previous_state = self.state
            self.state = "help"
        elif action == "menu":
            if self.player.hp > 0:
                self.save()
            self.state = "menu"
        elif action == "cancel":
            self.state = "menu"
        elif action == "save":
            if self.save():
                self.toast("Подорож збережено", MINT)
        elif action == "sound":
            self.audio.enabled = not self.audio.enabled
        elif action == "respawn":
            self.respawn()
        elif action.startswith("buy:"):
            self.buy(action.split(":")[1])
        elif action == "attack":
            self.attack()
        elif action == "spell":
            self.spell()
        elif action == "dash":
            self.dash()
        elif action == "heal":
            self.heal()
        elif action == "interact":
            self.interact()
        elif action in ("map", "inventory", "pause"):
            self.state = action
            if action == "pause":
                self.save()

    def logical_mouse(self, pos):
        ww, wh = self.window.get_size()
        scale = min(ww / W, wh / H)
        return ((pos[0] - (ww - W * scale) / 2) / scale,
                (pos[1] - (wh - H * scale) / 2) / scale)

    @staticmethod
    def physical_key(event):
        # Keep the controls usable with a Ukrainian (or other) keyboard layout.
        letters = "wasdqefihv"
        mapping = {getattr(pygame, "KSCAN_" + letter.upper()): getattr(pygame, "K_" + letter)
                   for letter in letters}
        return mapping.get(getattr(event, "scancode", -1), event.key)

    def input(self, events):
        for event in events:
            if event.type == pygame.QUIT:
                if self.state not in ("menu", "confirm", "dead"):
                    self.save()
                self.running = False
            elif event.type == pygame.WINDOWFOCUSLOST:
                self.keys.clear()
                self.fingers.clear()
                if self.state == "playing":
                    self.state = "pause"
                    self.save()
            elif event.type == pygame.MOUSEMOTION:
                self.mouse = self.logical_mouse(event.pos)
            elif event.type == pygame.KEYUP:
                self.keys.discard(self.physical_key(event))
            elif event.type == pygame.KEYDOWN:
                k = self.physical_key(event)
                self.keys.add(k)
                if k == pygame.K_ESCAPE:
                    if self.state == "playing":
                        self.state = "pause"
                        self.save()
                    elif self.state in ("pause", "inventory", "map", "shop", "dialog"):
                        self.state = "playing"
                    elif self.state == "help":
                        self.state = self.previous_state
                    elif self.state == "confirm":
                        self.state = "menu"
                    self.keys.clear()
                elif self.state == "menu" and k == pygame.K_RETURN:
                    self.resume() if self.saved else self.new_game()
                elif self.state == "dead" and k == pygame.K_RETURN:
                    self.respawn()
                elif self.state in ("dialog", "victory") and k in (pygame.K_e, pygame.K_RETURN, pygame.K_SPACE):
                    self.state = "playing"
                    self.keys.clear()
                elif self.state in ("map", "inventory") and k in (pygame.K_TAB, pygame.K_i):
                    self.state = "playing"
                    self.keys.clear()
                elif self.state == "playing":
                    actions = {pygame.K_e: "interact", pygame.K_q: "spell", pygame.K_f: "heal",
                               pygame.K_LSHIFT: "dash", pygame.K_RSHIFT: "dash",
                               pygame.K_TAB: "map", pygame.K_i: "inventory", pygame.K_h: "help"}
                    if k in actions:
                        self.activate(actions[k])
                    elif k == pygame.K_v:
                        self.audio.enabled = not self.audio.enabled
            elif event.type == pygame.MOUSEBUTTONDOWN and not getattr(event, "touch", False):
                self.mouse = self.logical_mouse(event.pos)
                if event.button == 1:
                    match = next((action for rect, action in reversed(self.buttons) if rect.collidepoint(self.mouse)), None)
                    if match:
                        self.activate(match)
                    elif self.state == "playing":
                        self.attack((self.mouse[0] + self.camera[0], self.mouse[1] + self.camera[1]))
            elif event.type in (pygame.FINGERDOWN, pygame.FINGERMOTION, pygame.FINGERUP):
                self.touch = True
                if event.type == pygame.FINGERUP:
                    self.fingers.pop(event.finger_id, None)
                else:
                    ww, wh = self.window.get_size()
                    pos = self.logical_mouse((event.x * ww, event.y * wh))
                    self.fingers[event.finger_id] = pos
                    if event.type == pygame.FINGERDOWN:
                        match = next((action for rect, action in reversed(self.buttons) if rect.collidepoint(pos)), None)
                        if match:
                            self.activate(match)

    def update(self, dt):
        dt = min(.05, max(0, dt))
        self.t += dt
        self.toasts = [[msg, col, life - dt] for msg, col, life in self.toasts if life > dt]
        if self.state != "playing":
            return
        p = self.player
        self.progress.play_time += dt
        for attr in ("attack_cd", "spell_cd", "dash_cd", "dash_time", "invulnerable", "slash", "shake"):
            setattr(self, attr, max(0, getattr(self, attr) - dt))
        p.mana = min(100, p.mana + dt * 10)
        dx = int(bool(self.keys & {pygame.K_d, pygame.K_RIGHT})) - int(bool(self.keys & {pygame.K_a, pygame.K_LEFT}))
        dy = int(bool(self.keys & {pygame.K_s, pygame.K_DOWN})) - int(bool(self.keys & {pygame.K_w, pygame.K_UP}))
        for x, y in self.fingers.values():
            if x < 250 and y > H - 220:
                dx, dy = unit(x - 116, y - (H - 112)) if distance((x, y), (116, H - 112)) > 14 else (0, 0)
        dx, dy = unit(dx, dy)
        if dx or dy:
            self.facing = (dx, dy)
        if self.dash_time > 0:
            dx, dy = self.dash_vector
            self.world.move(p, dx * 680 * dt, dy * 680 * dt)
            self.burst(p.x, p.y, CYAN, 2)
        else:
            self.world.move(p, dx * 205 * dt, dy * 205 * dt)
        if pygame.K_SPACE in self.keys:
            self.attack()
        for e in self.enemies:
            if e.hp <= 0:
                continue
            e.flash = max(0, e.flash - dt)
            e.cooldown = max(0, e.cooldown - dt)
            if e.kind == "boss" and not self.progress.portal_open:
                continue
            d = distance(e.pos, p.pos)
            active = d < (620 if e.kind == "boss" else 390) and distance(p.pos, CAMP) > 245
            if not active:
                if distance(e.pos, e.home) > 10:
                    vx, vy = unit(e.home[0] - e.x, e.home[1] - e.y)
                    self.world.move(e, vx * e.speed * dt, vy * e.speed * dt, e.radius)
                e.windup = 0
                continue
            vx, vy = unit(p.x - e.x, p.y - e.y)
            desired = 195 if e.kind == "wisp" else 52 if e.kind == "boss" else 35
            if e.windup <= 0 and d > desired:
                self.world.move(e, vx * e.speed * dt, vy * e.speed * dt, e.radius)
            elif e.kind == "wisp" and d < 125:
                self.world.move(e, -vx * e.speed * dt, -vy * e.speed * dt, e.radius)
            if e.windup > 0:
                e.windup -= dt
                if e.windup <= 0:
                    if e.kind in ("wisp", "boss"):
                        base = math.atan2(e.attack_dy, e.attack_dx)
                        angles = (-.65, -.32, 0, .32, .65) if e.kind == "boss" else (0,)
                        for angle in angles:
                            a = base + angle
                            self.projectiles.append([e.x, e.y, math.cos(a) * 225, math.sin(a) * 225, 2.8, False, e.damage])
                    elif d < e.radius + 50:
                        self.hurt_player(e.damage)
                    e.cooldown = 1.7 if e.kind in ("wisp", "boss") else 1.0
            elif e.cooldown <= 0 and d < (430 if e.kind in ("wisp", "boss") else e.radius + 44):
                e.windup = .55 if e.kind == "boss" else .4
                e.attack_dx, e.attack_dy = vx, vy
            if e.kind == "boss" and d < 62:
                self.hurt_player(e.damage)
            if self.state != "playing":
                break
        for shot in self.projectiles:
            if self.state != "playing":
                break
            shot[4] -= dt
            if shot[4] <= 0:
                continue
            # Swept substeps prevent fast bolts skipping enemies or thin trunks.
            steps = max(1, math.ceil(math.hypot(shot[2], shot[3]) * dt / 10))
            for _ in range(steps):
                shot[0] += shot[2] * dt / steps
                shot[1] += shot[3] * dt / steps
                if self.world.blocked(shot[0], shot[1], 4):
                    shot[4] = 0
                    break
                if shot[5]:
                    hit = next((e for e in self.enemies if e.hp > 0 and distance(e.pos, shot[:2]) < e.radius + 8
                                and (e.kind != "boss" or self.progress.portal_open)), None)
                    if hit:
                        self.damage_enemy(hit, shot[6])
                        shot[4] = 0
                        break
                elif distance(p.pos, shot[:2]) < 24:
                    self.hurt_player(shot[6])
                    shot[4] = 0
                    break
        self.projectiles = [s for s in self.projectiles if s[4] > 0]
        self.enemies = [e for e in self.enemies if e.hp > 0]
        for particle in self.particles:
            particle[0] += particle[2] * dt
            particle[1] += particle[3] * dt
            particle[4] -= dt
        self.particles = [v for v in self.particles[-450:] if v[4] > 0]
        for n in self.numbers:
            n[2] -= dt * 34
            n[3] -= dt
        self.numbers = [n for n in self.numbers if n[3] > 0]
        target = (clamp(p.x - W / 2, 0, WORLD_W - W), clamp(p.y - H / 2, 0, WORLD_H - H))
        for i in (0, 1):
            self.camera[i] += (target[i] - self.camera[i]) * min(1, dt * 9)
            self.camera[i] = clamp(self.camera[i], 0, (WORLD_W - W, WORLD_H - H)[i])
        self.autosave += dt
        if self.autosave >= 12 and self.state == "playing":
            self.autosave = 0
            self.save()

    def xy(self, x, y):
        return int(x - self.camera[0]), int(y - self.camera[1])

    def tree(self, x, y, kind, size):
        key = (kind, size)
        if key not in self.tree_sprites:
            surf = pygame.Surface((132, 150), pygame.SRCALPHA)
            pygame.draw.ellipse(surf, (10, 25, 23, 85), (18, 112, 96, 28))
            pygame.draw.rect(surf, (75, 72, 51), (60, 72, 13, 56), border_radius=4)
            pygame.draw.rect(surf, (104, 92, 61), (62, 77, 4, 45))
            colors = [((30, 65, 53), (41, 82, 61), (57, 99, 70)),
                      ((33, 71, 66), (43, 86, 71), (65, 106, 83)),
                      ((44, 71, 51), (60, 89, 59), (81, 110, 71))][kind]
            if kind != 2:
                for offset, col in zip((35, 16, -5), colors):
                    pygame.draw.polygon(surf, col, [(66, 18 + offset), (66 - size - 8, 80 + offset), (66 + size + 8, 80 + offset)])
                    pygame.draw.line(surf, tuple(min(255, c + 8) for c in col), (66, 20 + offset), (66 - size - 5, 78 + offset), 2)
            else:
                for px, py, r, col in ((46, 73, size, colors[0]), (87, 69, size - 4, colors[0]),
                                        (65, 48, size + 3, colors[1]), (52, 38, size - 10, colors[2])):
                    pygame.draw.circle(surf, col, (px, py), r)
            self.tree_sprites[key] = surf
        self.screen.blit(self.tree_sprites[key], (x - 66, y - 125))

    def crystal(self, x, y, active, small=False):
        bob = int(math.sin(self.t * 2 + x * .01) * 4)
        size = 10 if small else 18
        color = CYAN if active else (129, 148, 124)
        if active:
            self.glow((x, y - 20), 100 if not small else 50, CYAN)
        pygame.draw.ellipse(self.screen, (27, 43, 40), (x - 29, y - 4, 58, 18))
        pygame.draw.polygon(self.screen, (104, 119, 100), [(x - 26, y + 2), (x, y - 11), (x + 26, y + 2), (x, y + 12)])
        yy = y - 30 + bob
        pts = [(x, yy - size * 1.5), (x + size, yy), (x, yy + size), (x - size, yy)]
        pygame.draw.polygon(self.screen, color, pts)
        pygame.draw.polygon(self.screen, (205, 246, 214) if active else (175, 188, 156), [pts[0], (x, yy + size), pts[3]])
        pygame.draw.lines(self.screen, (237, 253, 225) if active else (101, 128, 108), True, pts, 1)

    def npc(self, x, y, merchant=False):
        pygame.draw.ellipse(self.screen, (18, 37, 31), (x - 20, y - 7, 40, 15))
        coat = GOLD if merchant else (159, 176, 189)
        pygame.draw.polygon(self.screen, coat, [(x, y - 42), (x - 16, y), (x + 16, y)])
        pygame.draw.circle(self.screen, (226, 195, 149), (x, y - 40), 10)
        pygame.draw.polygon(self.screen, (104, 111, 81) if merchant else (107, 137, 148), [(x - 14, y - 42), (x, y - 65), (x + 15, y - 42)])
        pygame.draw.line(self.screen, (130, 112, 71), (x + 20, y - 41), (x + 20, y + 2), 3)
        pygame.draw.circle(self.screen, GOLD if merchant else CYAN, (x + 20, y - 44), 5)
        if distance(self.player.pos, MERCHANT if merchant else ELDER) < 210:
            self.text("ОРИН · КРАМАР" if merchant else "МІРА · ХРАНИТЕЛЬКА", x, y - 91, 11, GOLD if merchant else CYAN, True, True)
            if not merchant and not self.progress.started:
                self.text("!", x, y - 120 + math.sin(self.t * 3) * 3, 23, GOLD, True, True)

    def draw_enemy(self, e):
        x, y = self.xy(e.x, e.y)
        bob = int(math.sin(self.t * 4 + e.x) * 3)
        shadow_w = 76 if e.kind == "boss" else 42
        pygame.draw.ellipse(self.screen, (19, 36, 31), (x - shadow_w // 2, y - 5, shadow_w, 15))
        color = TEXT if e.flash else {"slime": (149, 160, 91), "wisp": (186, 153, 197), "guardian": (134, 151, 139), "boss": (136, 101, 150)}[e.kind]
        if e.windup > 0:
            radius = 52 if e.kind != "boss" else 80
            pygame.draw.circle(self.screen, RED, (x, y), radius, 2)
        if e.kind == "slime":
            pygame.draw.ellipse(self.screen, color, (x - 21, y - 30 + bob, 42, 31 - bob))
            pygame.draw.ellipse(self.screen, (176, 191, 114) if not e.flash else TEXT, (x - 16, y - 29 + bob, 23, 14))
        elif e.kind == "wisp":
            self.glow((x, y - 20), 48, color)
            pygame.draw.polygon(self.screen, color, [(x, y - 45 + bob), (x + 20, y - 16), (x + 11, y - 1), (x, y - 9), (x - 14, y), (x - 20, y - 15)])
        elif e.kind == "guardian":
            pygame.draw.rect(self.screen, (69, 85, 78), (x - 19, y - 32, 38, 36), border_radius=7)
            pygame.draw.rect(self.screen, color, (x - 15, y - 49, 30, 32), border_radius=6)
            pygame.draw.rect(self.screen, color, (x - 27, y - 25, 11, 24), border_radius=3)
            pygame.draw.rect(self.screen, color, (x + 16, y - 25, 11, 24), border_radius=3)
        else:
            if not self.progress.portal_open:
                color = (85, 88, 94)
            self.glow((x, y - 35), 90, color)
            pygame.draw.polygon(self.screen, color, [(x, y - 94), (x + 29, y - 51), (x + 37, y), (x, y - 12), (x - 37, y), (x - 29, y - 51)])
            pygame.draw.polygon(self.screen, (89, 66, 107), [(x, y - 82), (x + 29, y - 51), (x + 37, y), (x, y - 12)])
            pygame.draw.polygon(self.screen, GOLD, [(x - 28, y - 73), (x - 34, y - 105), (x - 13, y - 83), (x, y - 112), (x + 14, y - 83), (x + 34, y - 105), (x + 27, y - 73)], 2)
        eye_y = y - (58 if e.kind == "boss" else 20 if e.kind != "guardian" else 36) + (bob if e.kind == "slime" else 0)
        eye_col = RED if e.kind in ("boss", "guardian") else (32, 42, 36)
        for dx in (-7, 7):
            pygame.draw.circle(self.screen, eye_col, (x + dx, eye_y), 3)
        if e.hp < e.max_hp and e.kind != "boss":
            pygame.draw.rect(self.screen, INK, (x - 23, y - 62, 46, 5), border_radius=2)
            pygame.draw.rect(self.screen, RED, (x - 23, y - 62, max(0, int(46 * e.hp / e.max_hp)), 5), border_radius=2)

    def draw_world(self):
        cx, cy = int(self.camera[0]), int(self.camera[1])
        self.screen.blit(self.ground, (0, 0), (cx, cy, W, H))
        visible = pygame.Rect(cx - 130, cy - 100, W + 260, H + 270)
        for x, y in SHRINES:
            if visible.collidepoint(x, y):
                sx, sy = self.xy(x, y)
                self.glow((sx, sy), 110, CYAN)
        # Small stone arch at the final objective.
        x, y = self.xy(*PORTAL)
        if visible.collidepoint(*PORTAL):
            color = GOLD if self.progress.portal_open else (81, 103, 92)
            self.glow((x, y - 40), 145, color)
            pygame.draw.ellipse(self.screen, (24, 39, 36), (x - 65, y - 105, 130, 140))
            pygame.draw.ellipse(self.screen, color, (x - 62, y - 104, 124, 136), 9)
            for side in (-1, 1):
                for i in range(4):
                    pygame.draw.rect(self.screen, (107 + i * 4, 117 + i * 3, 96 + i * 3), (x + side * 58 - 10, y - i * 24, 23, 21), border_radius=3)
            if self.progress.portal_open:
                pygame.draw.ellipse(self.screen, (63, 81, 69), (x - 43, y - 85, 86, 105))
                self.text("✦", x, y - 70, 44, GOLD, center=True)
            self.text("БРАМА СВІТАНКУ", x, y - 142, 12, color, True, True)
        # Camp props.
        x, y = self.xy(*CAMP)
        if visible.collidepoint(*CAMP):
            self.glow((x, y - 12), 160, GOLD)
            pygame.draw.ellipse(self.screen, (40, 46, 35), (x - 34, y - 14, 68, 32))
            for i in range(8):
                a = math.tau * i / 8
                pygame.draw.circle(self.screen, (118, 121, 99), (int(x + math.cos(a) * 29), int(y + math.sin(a) * 13)), 6)
            for dx in (-10, 5):
                pygame.draw.line(self.screen, (122, 86, 53), (x - 16, y + dx), (x + 17, y - dx), 6)
            f = int(math.sin(self.t * 13) * 4)
            pygame.draw.polygon(self.screen, (226, 144, 77), [(x - 16, y), (x - 8, y - 29), (x - 1, y - 17), (x + 7, y - 42 - f), (x + 17, y - 6), (x + 12, y + 3)])
            pygame.draw.polygon(self.screen, GOLD, [(x - 8, y), (x + 2, y - 26 - f), (x + 9, y)])
            tx, ty = x - 133, y - 85
            pygame.draw.polygon(self.screen, (113, 129, 91), [(tx, ty - 69), (tx - 69, ty + 24), (tx + 66, ty + 24)])
            pygame.draw.polygon(self.screen, (76, 98, 73), [(tx, ty - 69), (tx + 66, ty + 24), (tx + 6, ty + 24)])
            pygame.draw.polygon(self.screen, (30, 49, 40), [(tx, ty - 24), (tx - 28, ty + 24), (tx + 6, ty + 24)])
            pygame.draw.line(self.screen, (177, 176, 122), (tx, ty - 69), (tx - 69, ty + 24), 2)
            self.text("ПРИХИСТОК МАНДРІВНИКА", x, y + 52, 11, (162, 172, 130), True, True)
        scene = []
        for tree in self.world.trees:
            if visible.collidepoint(tree[:2]):
                scene.append((tree[1], "tree", tree))
        for rock in self.world.rocks:
            if visible.collidepoint(rock[:2]):
                scene.append((rock[1], "rock", rock))
        for i, pos in enumerate(SHRINES):
            scene.append((pos[1], "shrine", (i, pos)))
        for i, pos in enumerate(CHESTS):
            scene.append((pos[1], "chest", (i, pos)))
        scene += [(ELDER[1], "npc", False), (MERCHANT[1], "npc", True), (self.player.y, "player", None)]
        scene += [(e.y, "enemy", e) for e in self.enemies if visible.collidepoint(e.pos)]
        for _, kind, data in sorted(scene, key=lambda v: v[0]):
            if kind == "tree":
                x, y = self.xy(data[0], data[1])
                self.tree(x, y, data[2], data[3])
            elif kind == "rock":
                x, y = self.xy(data[0], data[1])
                r = data[2]
                pygame.draw.ellipse(self.screen, (27, 43, 35), (x - r - 3, y - 5, r * 2 + 6, r))
                pygame.draw.polygon(self.screen, (93, 109, 91), [(x - r, y), (x - r + 4, y - r), (x + 5, y - r - 5), (x + r, y - 8), (x + r - 3, y + 4)])
                pygame.draw.line(self.screen, (126, 139, 113), (x - r + 4, y - r), (x + 5, y - r - 5), 2)
            elif kind == "shrine":
                i, pos = data
                x, y = self.xy(*pos)
                self.crystal(x, y, i in self.progress.crystals)
                if distance(pos, self.player.pos) < 260:
                    self.text(SHRINE_NAMES[i], x, y - 88, 12, CYAN if i in self.progress.crystals else MUTED, True, True)
            elif kind == "chest":
                i, pos = data
                x, y = self.xy(*pos)
                opened = i in self.progress.opened
                pygame.draw.ellipse(self.screen, (23, 41, 32), (x - 25, y - 4, 50, 16))
                pygame.draw.rect(self.screen, (111, 82, 48), (x - 21, y - 24, 42, 27), border_radius=4)
                pygame.draw.rect(self.screen, (154, 119, 66), (x - 21, y - (37 if opened else 27), 42, 12), border_radius=4)
                for xx in (x - 14, x + 10):
                    pygame.draw.rect(self.screen, GOLD, (xx, y - 23, 4, 25))
                if not opened:
                    pygame.draw.rect(self.screen, GOLD, (x - 4, y - 16, 8, 8), border_radius=2)
                    if distance(pos, self.player.pos) < 260:
                        self.glow((x, y - 10), 55, GOLD)
            elif kind == "npc":
                x, y = self.xy(*(MERCHANT if data else ELDER))
                self.npc(x, y, data)
            elif kind == "enemy":
                self.draw_enemy(data)
            elif kind == "player":
                x, y = self.xy(*self.player.pos)
                bob = math.sin(self.t * 13) * 2 if self.keys or self.fingers else math.sin(self.t * 2.5) * 2
                self.glow((x, y - 18), 58, CYAN)
                pygame.draw.ellipse(self.screen, (18, 36, 32), (x - 25, y - 3, 50, 15))
                if self.invulnerable <= 0 or int(self.t * 16) % 2 == 0:
                    self.screen.blit(self.hero_sizes[40], (x - 20, y - 40 + bob))
                    fx, fy = self.facing
                    a = math.atan2(fy, fx)
                    if self.slash > 0:
                        a += (1 - self.slash / .2) * 2.4 - 1.2
                        points = [(x, y - 12)]
                        for n in range(10):
                            theta = a - .5 + n * .1
                            points.append((x + math.cos(theta) * 78, y - 12 + math.sin(theta) * 55))
                        overlay = pygame.Surface((W, H), pygame.SRCALPHA)
                        pygame.draw.polygon(overlay, (*GOLD, 95), points)
                        pygame.draw.lines(overlay, (*GOLD, 240), False, points[1:], 3)
                        self.screen.blit(overlay, (0, 0))
                    bx, by = x + math.cos(a) * 24, y - 15 + math.sin(a) * 17
                    tip = (bx + math.cos(a) * 29, by + math.sin(a) * 24)
                    pygame.draw.line(self.screen, (218, 230, 208), (bx, by), tip, 4)
                    pygame.draw.line(self.screen, GOLD, (bx - math.sin(a) * 6, by + math.cos(a) * 6), (bx + math.sin(a) * 6, by - math.cos(a) * 6), 3)
        for shot in self.projectiles:
            x, y = self.xy(shot[0], shot[1])
            col = CYAN if shot[5] else RED
            self.glow((x, y - 15), 36, col)
            pygame.draw.circle(self.screen, col, (x, y - 15), 7)
            pygame.draw.circle(self.screen, TEXT, (x - 1, y - 17), 3)
            vx, vy = unit(shot[2], shot[3])
            pygame.draw.line(self.screen, col, (x, y - 15), (x - vx * 17, y - 15 - vy * 17), 3)
        for p in self.particles:
            x, y = self.xy(p[0], p[1])
            pygame.draw.circle(self.screen, p[6], (x, y - 18), max(1, int(4 * p[4] / p[5])))
        for text, x, y, life, col in self.numbers:
            sx, sy = self.xy(x, y)
            self.text(text, sx, sy, 16, col, True, True)
        # Subtle drifting fireflies add movement without an external art pack.
        for i in range(24):
            x = int((i * 193 + math.sin(self.t * .3 + i) * 26 - cx * .7) % W)
            y = int((i * 97 + math.cos(self.t * .4 + i) * 20 - cy * .7) % H)
            bright = int(100 + math.sin(self.t * 1.4 + i) * 45)
            pygame.draw.circle(self.screen, (bright, min(255, bright + 45), bright), (x, y), 1)

    def bar(self, rect, fraction, color, bg=(37, 53, 50)):
        rect = pygame.Rect(rect)
        pygame.draw.rect(self.screen, bg, rect, border_radius=max(1, rect.height // 2))
        filled = rect.copy()
        filled.width = int(rect.width * clamp(fraction, 0, 1))
        if filled.width:
            pygame.draw.rect(self.screen, color, filled, border_radius=max(1, rect.height // 2))

    def draw_map(self, rect, full=False):
        rect = pygame.Rect(rect)
        self.panel(rect, (20, 38, 34), LINE, 8)
        sx, sy = rect.width / WORLD_W, rect.height / WORLD_H
        def point(p):
            return int(rect.x + p[0] * sx), int(rect.y + p[1] * sy)
        for a, b in self.world.paths:
            pygame.draw.line(self.screen, (68, 88, 65), point(a), point(b), 3 if full else 1)
        for x, y, rx, ry in self.world.ponds:
            px, py = point((x, y))
            pygame.draw.ellipse(self.screen, (47, 87, 87), (px - rx * sx, py - ry * sy, rx * sx * 2, ry * sy * 2))
        if full:
            for x, y, _, _ in self.world.trees:
                pygame.draw.circle(self.screen, (41, 66, 49), point((x, y)), 3)
        radius = 7 if full else 3
        for i, pos in enumerate(SHRINES):
            px, py = point(pos)
            col = CYAN if i in self.progress.crystals else MUTED
            pygame.draw.polygon(self.screen, col, [(px, py - radius), (px + radius, py), (px, py + radius), (px - radius, py)])
            if full:
                self.text(SHRINE_NAMES[i], px, py + 14, 13, col, center=True)
        pygame.draw.circle(self.screen, GOLD, point(CAMP), radius)
        px, py = point(PORTAL)
        pygame.draw.circle(self.screen, GOLD if self.progress.portal_open else (151, 123, 162), (px, py), radius + 2, 2)
        if full:
            self.text("Прихисток", *point((CAMP[0] - 130, CAMP[1] + 90)), 13, GOLD)
            self.text("Брама світанку", px, py - 30, 13, GOLD, center=True)
            for i, pos in enumerate(CHESTS):
                if i not in self.progress.opened:
                    xx, yy = point(pos)
                    pygame.draw.rect(self.screen, GOLD, (xx - 3, yy - 3, 6, 6))
        px, py = point(self.player.pos)
        pygame.draw.circle(self.screen, CYAN, (px, py), radius + 4, 1)
        pygame.draw.circle(self.screen, TEXT, (px, py), radius - 1)

    def draw_hud(self):
        p = self.player
        self.panel((22, 20, 290, 100))
        self.screen.blit(self.hero_sizes[48], (38, 37))
        self.text("МАНДРІВНИК", 102, 32, 12, TEXT, True)
        self.text(f"РІВЕНЬ {p.level}", 284, 33, 10, MINT, True, True)
        self.bar((103, 58, 185, 9), p.hp / p.max_hp, RED)
        self.bar((103, 77, 185, 5), p.mana / 100, CYAN)
        self.text(f"{math.ceil(p.hp)} / {p.max_hp} HP", 103, 91, 10, MUTED)
        self.text(f"{int(p.mana)} MP", 252, 91, 10, CYAN)
        self.bar((38, 105, 49, 3), p.xp / p.next_xp, GOLD)
        self.panel((328, 20, 115, 40))
        pygame.draw.circle(self.screen, GOLD, (347, 40), 5)
        self.text(str(p.gold), 363, 29, 16, GOLD, True)
        self.button((454, 20, 38, 40), "Ⅱ", "pause", size=16)
        self.panel((W - 214, 20, 192, 180))
        self.text("ЛІС ВІДЛУНЬ", W - 198, 33, 11, MINT, True)
        self.text("TAB", W - 64, 34, 10, MUTED)
        self.draw_map((W - 201, 58, 166, 125))
        self.buttons.append((pygame.Rect(W - 214, 20, 192, 180), "map"))
        if distance(p.pos, CAMP) < 255:
            self.text("ПРИХИСТОК · БЕЗПЕЧНА ЗОНА", W / 2 + 72, 33, 10, MINT, True, True)
        boss = next((e for e in self.enemies if e.kind == "boss"), None)
        if boss and self.progress.portal_open and distance(boss.pos, p.pos) < 600:
            self.panel((390, 83, 370, 62))
            self.text("ВАРТОВИЙ ТІНІ", W / 2, 93, 13, (205, 172, 214), True, True)
            self.bar((408, 122, 334, 6), boss.hp / boss.max_hp, (179, 132, 187))
        if not self.touch:
            self.panel((22, H - 120, 345, 98))
            self.text("ВАША ПОДОРОЖ", 39, H - 106, 10, GOLD, True)
            self.wrap(self.progress.objective, 39, H - 84, 314, 14, TEXT, 22)
            slots = [("SPACE", "Клинок", "attack", self.attack_cd / .34), ("Q", "Магія", "spell", self.spell_cd / .65),
                     ("SHIFT", "Ривок", "dash", self.dash_cd / 1.25), ("F", f"Зілля · {p.potions}", "heal", 0), ("I", "Рюкзак", "inventory", 0)]
            for i, (key, label, action, cd) in enumerate(slots):
                x = 397 + i * 104
                self.panel((x, H - 94, 94, 72), (23, 42, 40))
                self.text(key, x + 47, H - 82, 12, CYAN if i == 1 else GOLD if i == 3 else TEXT, True, True)
                self.text(label, x + 47, H - 56, 12, MUTED, center=True)
                if cd > 0:
                    self.bar((x + 10, H - 29, 74, 3), 1 - cd, CYAN)
                self.buttons.append((pygame.Rect(x, H - 94, 94, 72), action))
            self.text("H · допомога", W - 65, H - 49, 11, MUTED, center=True)
        else:
            self.draw_touch()
        obj = self.nearby()
        if obj:
            label = f"E  ·  {obj[3]}"
            width = self.font(14).size(label)[0] + 34
            x, y = self.xy(self.player.x, self.player.y + 29)
            x = clamp(x - width / 2, 12, W - width - 12)
            self.panel((x, y, width, 36), INK, LINE, 8)
            self.text(label, x + width / 2, y + 8, 14, GOLD, center=True)
            self.buttons.append((pygame.Rect(x, y, width, 36), "interact"))

    def draw_touch(self):
        self.panel((40, H - 190, 152, 152), INK, LINE, 75, 150)
        pygame.draw.circle(self.screen, MUTED, (116, H - 114), 47, 1)
        self.text("↑", 116, H - 187, 28, TEXT, center=True)
        self.text("↓", 116, H - 98, 28, TEXT, center=True)
        self.text("‹", 65, H - 144, 32, TEXT, center=True)
        self.text("›", 167, H - 144, 32, TEXT, center=True)
        for x, y, label, action in ((W - 115, H - 155, "УДАР", "attack"), (W - 205, H - 200, "МАГІЯ", "spell"),
                                      (W - 205, H - 110, "РИВОК", "dash"), (W - 295, H - 155, "ДІЯ", "interact"),
                                      (W - 295, H - 78, "ЗІЛЛЯ", "heal")):
            self.button((x, y, 80, 68), label, action, size=12)
        self.button((W / 2 - 46, H - 65, 92, 43), "РЮКЗАК", "inventory", size=11)

    def dim(self, opacity=170):
        overlay = pygame.Surface((W, H), pygame.SRCALPHA)
        overlay.fill((8, 20, 21, opacity))
        self.screen.blit(overlay, (0, 0))

    def draw_menu(self):
        self.dim(150)
        self.panel((58, 62, W - 116, H - 124), (16, 31, 32), (67, 88, 76), 20, 233)
        self.text("E C H O   F O R E S T", 106, 104, 13, MINT, True)
        self.text("ЛІС", 101, 152, 68, TEXT, True)
        self.text("ВІДЛУНЬ", 101, 224, 68, TEXT, True)
        pygame.draw.line(self.screen, MINT, (108, 324), (165, 324), 3)
        self.wrap("Маленький мандрівник. Велика подорож.", 108, 349, 480, 20, TEXT, 31)
        self.wrap("Знайди три джерела світла та пробуди ліс, що загубив свій голос.", 108, 392, 410, 17, MUTED, 28)
        if self.saved:
            self.button((108, 487, 282, 53), "Продовжити подорож  →", "resume", True)
            self.button((108, 553, 180, 44), "Нова гра", "new", size=15)
            self.button((301, 553, 142, 44), "Керування", "help", size=15)
        else:
            self.button((108, 487, 282, 56), "Почати подорож  →", "new", True)
            self.button((108, 558, 170, 43), "Як грати", "help", size=15)
        self.text("2D ACTION RPG  /  УКРАЇНСЬКОЮ", 694, 110, 11, MUTED, True)
        self.glow((818, 330), 200, CYAN)
        pygame.draw.circle(self.screen, (62, 91, 78), (817, 325), 146, 1)
        pygame.draw.circle(self.screen, (45, 70, 63), (817, 325), 170, 1)
        for i in range(3):
            a = i * math.tau / 3 - math.pi / 2
            x, y = int(817 + math.cos(a) * 147), int(325 + math.sin(a) * 147)
            self.crystal(x, y + 24, True, True)
        pygame.draw.ellipse(self.screen, (8, 22, 23), (738, 406, 160, 26))
        self.screen.blit(self.hero_sizes[160], (737, 240 + math.sin(self.t * 2) * 7))
        self.text("СВІТЛО ПОЧИНАЄТЬСЯ З ТЕБЕ", 817, 516, 12, MINT, True, True)
        self.text("Досліджуй · Бийся · Повертай життя", 817, 546, 13, MUTED, center=True)
        self.text("Enter · грати", W - 120, H - 40, 11, MUTED, center=True)

    def modal(self, title, subtitle="", width=610, height=475):
        self.dim()
        rect = pygame.Rect((W - width) // 2, (H - height) // 2, width, height)
        self.panel(rect, PANEL, LINE, 18)
        self.text(title, rect.x + 32, rect.y + 28, 26, TEXT, True)
        if subtitle:
            self.text(subtitle, rect.x + 32, rect.y + 69, 13, MUTED)
        return rect

    def draw_overlay(self):
        s, p = self.state, self.player
        if s in ("menu", "confirm"):
            self.draw_menu()
            if s == "confirm":
                self.buttons.clear()
                r = self.modal("Почати спочатку?", "Нова подорож замінить поточне збереження.", 570, 250)
                self.button((r.x + 32, r.y + 143, 240, 52), "Так, нова подорож", "confirm-new", True, size=15)
                self.button((r.x + 288, r.y + 143, 245, 52), "Залишити збереження", "cancel", size=14)
        elif s == "pause":
            r = self.modal("Мить перепочинку", "Подорож автоматично збережено.", 480, 430)
            self.button((r.x + 32, r.y + 113, 416, 52), "Продовжити  →", "back", True)
            self.button((r.x + 32, r.y + 181, 200, 48), "Керування", "help", size=15)
            self.button((r.x + 248, r.y + 181, 200, 48), "Звук: " + ("увімкнено" if self.audio.enabled else "вимкнено"), "sound", size=14)
            self.button((r.x + 32, r.y + 245, 416, 48), "Зберегти подорож", "save", size=16)
            self.button((r.x + 32, r.y + 309, 416, 48), "Головне меню", "menu", size=16)
            self.text("ESC · повернутися", r.centerx, r.bottom - 39, 12, MUTED, center=True)
        elif s == "help":
            r = self.modal("Ваша перша пригода", "Керування та маленькі підказки", 730, 600)
            controls = [("W A S D / ↑ ↓ ← →", "Рух персонажа"), ("SPACE / ліва кнопка миші", "Удар мечем; Space можна тримати"),
                        ("Q", "Магічний постріл із наведенням · 22 мани"), ("SHIFT", "Ривок із короткою невразливістю"),
                        ("E", "Розмова, скриня, джерело або відпочинок"), ("F", "Зілля здоров'я · +65 HP"),
                        ("TAB / I", "Мапа / рюкзак і завдання"), ("ESC / V", "Пауза / звук")]
            for i, (key, desc) in enumerate(controls):
                yy = r.y + 115 + i * 36
                self.text(key, r.x + 32, yy, 13, GOLD, True)
                self.text(desc, r.x + 282, yy, 13, TEXT)
            self.wrap("Почни з розмови з Мірою. Здолай охоронців трьох джерел і пробуди їх клавішею E. Вогнище лікує безкоштовно. На сенсорному екрані з'являться кнопки керування.", r.x + 32, r.y + 421, r.width - 64, 14, MUTED, 23)
            self.button((r.x + 32, r.bottom - 73, r.width - 64, 45), "Зрозуміло", "back", True, size=15)
        elif s == "dialog":
            r = self.modal(self.dialog[0], "Прихисток мандрівника", 720, 445)
            y = r.y + 112
            for line in self.dialog[1]:
                y = self.wrap(line, r.x + 32, y, r.width - 64, 17, TEXT, 28) + 14
            self.button((r.x + 32, r.bottom - 77, r.width - 64, 48), "Назустріч пригоді  →", "back", True)
        elif s == "inventory":
            r = self.modal("Рюкзак мандрівника", f"Рівень {p.level} · {p.xp}/{p.next_xp} досвіду · {p.gold} золота", 760, 565)
            self.screen.blit(self.hero_sizes[64], (r.x + 34, r.y + 117))
            self.text(p.sword.name, r.x + 124, r.y + 117, 19, GOLD, True)
            self.text(f"Атака: {p.damage}  ·  Броня: {p.armour * 16}%  ·  Зілля: {p.potions}", r.x + 124, r.y + 153, 14, MUTED)
            self.text("ЖУРНАЛ ПОДОРОЖІ", r.x + 32, r.y + 213, 12, MINT, True)
            goals = [(self.progress.started, "Знайомство з хранителькою"),
                     *[(i in self.progress.crystals, SHRINE_NAMES[i]) for i in range(3)],
                     ("boss" in self.progress.defeated, "Перемога над Вартовим тіні"),
                     (self.progress.won, "Повернення світла до лісу")]
            for i, (done, label) in enumerate(goals):
                yy = r.y + 245 + i * 30
                self.text("✓" if done else "○", r.x + 34, yy, 17, MINT if done else MUTED)
                self.text(label, r.x + 66, yy + 1, 15, MINT if done else TEXT)
            self.text(f"Скрині: {len(self.progress.opened)}/{len(CHESTS)}   ·   Час у грі: {int(self.progress.play_time // 60)} хв", r.x + 32, r.y + 440, 13, MUTED)
            self.button((r.x + 32, r.bottom - 70, r.width - 64, 44), "Повернутися до лісу", "back", True, size=15)
        elif s == "shop":
            r = self.modal("Крамниця Орина", f"Добре спорядження — добра пригода. У вас {p.gold} золота.", 740, 550)
            items = [("potion", "Зілля здоров'я", "+65 HP · використати клавішею F", 20, p.potions >= 99),
                     ("sword", "Покращення клинка", f"+9 до атаки · рівень {p.sword.tier}/3", 45 + p.sword.tier * 35, p.sword.tier >= 3),
                     ("armour", "Захисний талісман", f"−16% вхідної шкоди · рівень {p.armour}/3", 40 + p.armour * 30, p.armour >= 3)]
            for i, (kind, title, desc, price, full) in enumerate(items):
                y = r.y + 117 + i * 106
                self.panel((r.x + 28, y, r.width - 56, 92), (25, 43, 41))
                self.text(title, r.x + 48, y + 17, 17, TEXT, True)
                self.text(desc, r.x + 48, y + 49, 13, MUTED)
                self.button((r.right - 190, y + 23, 140, 44), "Максимум" if full else f"{price} зол.  +", f"buy:{kind}", disabled=full or p.gold < price, size=14)
            self.button((r.x + 32, r.bottom - 73, r.width - 64, 45), "До нових зустрічей", "back", True, size=15)
        elif s == "map":
            r = self.modal("Мапа Лісу відлунь", "Йдіть стежками. Ваша наступна пригода вже поруч.", 900, 650)
            self.draw_map((r.x + 32, r.y + 108, 630, 472), True)
            self.text("ПОЗНАЧКИ", r.x + 687, r.y + 124, 11, MINT, True)
            for i, (label, col) in enumerate((("Ви", TEXT), ("Джерела", CYAN), ("Прихисток", GOLD), ("Скрині", GOLD), ("Брама", (185, 145, 195)))):
                pygame.draw.circle(self.screen, col, (r.x + 694, r.y + 169 + i * 37), 4)
                self.text(label, r.x + 711, r.y + 158 + i * 37, 13, col)
            self.wrap(self.progress.objective, r.x + 684, r.y + 374, 180, 14, TEXT, 24)
            self.button((r.x + 684, r.bottom - 113, 182, 49), "Назад · TAB", "back", True, size=14)
            self.text("Світлі джерела вже пробуджено. Квадрати — невідкриті скрині.", r.x + 32, r.bottom - 44, 12, MUTED)
        elif s == "dead":
            r = self.modal("Світло ще не згасло", "Кожен мандрівник іноді потребує нового початку.", 620, 340)
            self.wrap("Вогнище поверне вас до прихистку. Завдання й спорядження залишаться, але 15% золота загубиться в лісі.", r.x + 32, r.y + 115, r.width - 64, 17, TEXT, 28)
            self.button((r.x + 32, r.bottom - 85, r.width - 64, 52), "Повернутися до вогнища", "respawn", True)
        elif s == "victory":
            r = self.modal("Ліс знову співає", "Ви завершили історію Лісу відлунь.", 660, 445)
            self.wrap("Три джерела сяють. Тінь відступила. Маленький мандрівник повернув великому лісу його серце.", r.x + 32, r.y + 118, r.width - 64, 19, TEXT, 32)
            self.text(f"РІВЕНЬ {p.level}    ·    {len(self.progress.defeated)} ПЕРЕМОГ    ·    {int(self.progress.play_time // 60)} ХВ", r.centerx, r.y + 248, 14, GOLD, True, True)
            self.text("Ще можна відшукати всі скрині та повернутися до Міри.", r.centerx, r.y + 288, 14, MUTED, center=True)
            self.button((r.x + 32, r.bottom - 86, r.width - 64, 52), "Продовжити дослідження  →", "back", True)

    def draw(self):
        self.buttons = []
        self.draw_world()
        if self.state not in ("menu", "confirm"):
            self.draw_hud()
        if self.state != "playing":
            self.buttons.clear()
            self.draw_overlay()
        if self.state in ("playing", "shop", "pause"):
            messages = self.toasts if self.state == "playing" else self.toasts[-1:]
            for i, (msg, col, life) in enumerate(messages):
                width = min(W - 80, self.font(14).size(msg)[0] + 34)
                y = 155 + i * 43 if self.state == "playing" else H - 60
                self.panel(((W - width) / 2, y, width, 35), INK, LINE, 8, min(235, int(life * 235)))
                self.text(msg, W / 2, y + 8, 14, col, center=True)
        ww, wh = self.window.get_size()
        scale = min(ww / W, wh / H)
        size = (max(1, int(W * scale)), max(1, int(H * scale)))
        frame = self.screen if size == (W, H) else pygame.transform.smoothscale(self.screen, size)
        self.window.fill((8, 18, 19))
        shake_x = int(math.sin(self.t * 150) * 4) if self.shake and self.state == "playing" else 0
        self.window.blit(frame, ((ww - size[0]) // 2 + shake_x, (wh - size[1]) // 2))
        pygame.display.flip()
        if sys.platform == "emscripten" and self.web_last_state != self.state:
            import platform
            names = {"menu": "Головне меню", "playing": "Подорож лісом", "dialog": "Розмова з Мірою",
                     "map": "Мапа лісу", "inventory": "Рюкзак мандрівника", "pause": "Пауза",
                     "shop": "Крамниця Орина", "victory": "Ліс урятовано", "dead": "Відродження",
                     "help": "Керування", "confirm": "Підтвердження нової гри"}
            platform.window.canvas.setAttribute("aria-label", names.get(self.state, "Ліс відлунь"))
            platform.window.canvas.setAttribute("data-screen", self.state)
            self.web_last_state = self.state


async def main():
    game = Game()
    try:
        while game.running:
            # The browser owns the frame scheduler. Desktop caps at 60 FPS.
            dt = game.clock.tick(0 if sys.platform == "emscripten" else 60) / 1000
            game.input(pygame.event.get())
            game.update(dt)
            game.draw()
            await asyncio.sleep(0)
    finally:
        pygame.quit()


if __name__ == "__main__":
    asyncio.run(main())
