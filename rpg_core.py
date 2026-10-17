"""Deterministic RPG rules shared by the desktop and WebAssembly game.

This module deliberately has no pygame dependency, so gameplay and save files
can be validated without a display, audio device, or browser.
"""
from dataclasses import dataclass, field
import json
import math
import os
from pathlib import Path
import random
import sys

WORLD_W, WORLD_H = 2880, 2160
TILE = 48
CAMP = (624, 1080)
SPAWN = (704, 1080)
ELDER = (620, 978)
MERCHANT = (790, 1110)
PORTAL = (2496, 528)
SHRINES = ((1152, 576), (1968, 1104), (1392, 1728))
SHRINE_NAMES = ("Джерело світла", "Кам'яний гай", "Тихі води")
CHESTS = ((960, 960), (1560, 480), (2112, 1440), (912, 1632), (2448, 816))
SAVE_KEY = "echo-forest-save-v1"
SAVE_VERSION = 1


def distance(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def unit(x, y):
    length = math.hypot(x, y)
    return (x / length, y / length) if length else (0.0, 0.0)


def clamp(value, low, high):
    return max(low, min(high, value))


@dataclass
class Sword:
    tier: int = 0

    @property
    def name(self):
        return ("Клинок мандрівника", "Срібний клинок", "Клинок світанку", "Серце лісу")[self.tier]

    @property
    def damage(self):
        return 23 + self.tier * 9


@dataclass
class Player:
    x: float = SPAWN[0]
    y: float = SPAWN[1]
    hp: float = 100
    mana: float = 100
    level: int = 1
    xp: int = 0
    gold: int = 0
    potions: int = 3
    armour: int = 0
    sword: Sword = field(default_factory=Sword)

    @property
    def pos(self):
        return self.x, self.y

    @property
    def max_hp(self):
        return 100 + (self.level - 1) * 18

    @property
    def damage(self):
        return self.sword.damage + (self.level - 1) * 4

    @property
    def next_xp(self):
        return self.level * 70

    def gain_xp(self, amount):
        self.xp += max(0, int(amount))
        levels = 0
        while self.xp >= self.next_xp and self.level < 20:
            self.xp -= self.next_xp
            self.level += 1
            levels += 1
            self.hp = self.max_hp
            self.mana = 100
        return levels

    def take_damage(self, amount):
        actual = max(1, amount * (1 - self.armour * .16))
        self.hp = max(0, self.hp - actual)
        return actual

    def heal(self):
        if self.potions <= 0 or self.hp >= self.max_hp:
            return False
        self.potions -= 1
        self.hp = min(self.max_hp, self.hp + 65)
        return True


@dataclass
class Enemy:
    id: str
    x: float
    y: float
    kind: str = "slime"
    group: int = -1
    hp: float = 0
    cooldown: float = .8
    flash: float = 0
    windup: float = 0
    attack_dx: float = 0
    attack_dy: float = 0

    def __post_init__(self):
        if not self.hp:
            self.hp = self.max_hp
        self.home = (self.x, self.y)

    @property
    def pos(self):
        return self.x, self.y

    @property
    def max_hp(self):
        return {"slime": 44, "wisp": 60, "guardian": 95, "boss": 460}[self.kind]

    @property
    def radius(self):
        return 36 if self.kind == "boss" else 18

    @property
    def speed(self):
        return {"slime": 83, "wisp": 68, "guardian": 66, "boss": 62}[self.kind]

    @property
    def damage(self):
        return {"slime": 9, "wisp": 12, "guardian": 15, "boss": 20}[self.kind]


@dataclass
class Progress:
    started: bool = False
    crystals: set = field(default_factory=set)
    defeated: set = field(default_factory=set)
    opened: set = field(default_factory=set)
    won: bool = False
    play_time: float = 0

    @property
    def portal_open(self):
        return len(self.crystals) == 3

    @property
    def objective(self):
        if self.won:
            return "Ліс урятовано. Подорож триває!"
        if not self.started:
            return "Поговоріть із хранителькою біля вогнища"
        if not self.portal_open:
            return f"Пробудіть три джерела світла · {len(self.crystals)}/3"
        if "boss" not in self.defeated:
            return "Здолайте Вартового тіні біля північної брами"
        return "Поверніть світло: активуйте північну браму"


def make_enemies(progress):
    enemies = []
    for i, (x, y) in enumerate(SHRINES):
        for j, (dx, dy, kind) in enumerate(((-92, 36, "slime"), (90, 45, "wisp"), (0, -96, "guardian"))):
            enemies.append(Enemy(f"shrine-{i}-{j}", x + dx, y + dy, kind, i))
    for i, (x, y, kind) in enumerate(((1080, 1200, "slime"), (1580, 850, "slime"),
                                     (1790, 1550, "wisp"), (2180, 760, "guardian"),
                                     (1150, 1450, "slime"), (2320, 1410, "slime"),
                                     (1700, 480, "wisp"), (850, 1510, "slime"))):
        enemies.append(Enemy(f"wild-{i}", x, y, kind))
    enemies.append(Enemy("boss", PORTAL[0], PORTAL[1] + 108, "boss"))
    return [e for e in enemies if e.id not in progress.defeated]


class World:
    """Seeded terrain with clear routes connecting every quest location."""

    def __init__(self):
        self.paths = [(CAMP, shrine) for shrine in SHRINES] + [(SHRINES[1], PORTAL)]
        self.paths += [(CAMP, (300, 1080)), (SHRINES[0], PORTAL)]
        self.ponds = ((480, 490, 165, 110), (1820, 1810, 210, 115), (2350, 1760, 120, 165))
        rng = random.Random(47)
        protected = [CAMP, ELDER, MERCHANT, PORTAL, *SHRINES, *CHESTS]
        self.trees = []
        self.rocks = []
        for _ in range(850):
            x, y = rng.randrange(60, WORLD_W - 60), rng.randrange(80, WORLD_H - 60)
            if any(distance((x, y), p) < (270 if p == CAMP else 170) for p in protected):
                continue
            if self.on_path(x, y, 70) or self.water(x, y, 35):
                continue
            if any(distance((x, y), t[:2]) < 68 for t in self.trees):
                continue
            self.trees.append((x, y, rng.randrange(3), rng.randrange(28, 45)))
        for _ in range(60):
            x, y = rng.randrange(80, WORLD_W - 80), rng.randrange(80, WORLD_H - 80)
            if any(distance((x, y), p) < 150 for p in protected) or self.on_path(x, y, 70) or self.water(x, y, 30):
                continue
            self.rocks.append((x, y, rng.randrange(12, 24)))
        # Broad-phase buckets avoid scanning the entire forest on each step.
        self.spatial = {}
        for x, y, _, _ in self.trees:
            self.spatial.setdefault((x // 128, y // 128), []).append((x, y, 15))
        for x, y, radius in self.rocks:
            self.spatial.setdefault((x // 128, y // 128), []).append((x, y, radius))

    def on_path(self, x, y, width=37):
        for a, b in self.paths:
            dx, dy = b[0] - a[0], b[1] - a[1]
            t = clamp(((x - a[0]) * dx + (y - a[1]) * dy) / (dx * dx + dy * dy), 0, 1)
            if distance((x, y), (a[0] + t * dx, a[1] + t * dy)) < width:
                return True
        return False

    def water(self, x, y, pad=0):
        return any(((x - px) / (rx + pad)) ** 2 + ((y - py) / (ry + pad)) ** 2 < 1
                   for px, py, rx, ry in self.ponds)

    def blocked(self, x, y, radius=17):
        if not (radius + 24 <= x <= WORLD_W - radius - 24 and radius + 24 <= y <= WORLD_H - radius - 24):
            return True
        if self.water(x, y, radius):
            return True
        gx, gy = int(x // 128), int(y // 128)
        for bx in range(gx - 1, gx + 2):
            for by in range(gy - 1, gy + 2):
                if any(distance((x, y), (tx, ty)) < radius + tr for tx, ty, tr in self.spatial.get((bx, by), ())):
                    return True
        return False

    def move(self, actor, dx, dy, radius=17):
        # Substeps keep dashes and a low frame rate from crossing solid objects.
        steps = max(1, math.ceil(max(abs(dx), abs(dy)) / 10))
        for _ in range(steps):
            if not self.blocked(actor.x + dx / steps, actor.y, radius):
                actor.x += dx / steps
            if not self.blocked(actor.x, actor.y + dy / steps, radius):
                actor.y += dy / steps


def encode_save(player, progress):
    return json.dumps({"version": SAVE_VERSION, "player": {
        **{key: getattr(player, key) for key in ("x", "y", "hp", "mana", "level", "xp", "gold", "potions", "armour")},
        "sword": player.sword.tier}, "progress": {
        "started": progress.started, "crystals": sorted(progress.crystals),
        "defeated": sorted(progress.defeated), "opened": sorted(progress.opened),
        "won": progress.won, "play_time": progress.play_time}}, ensure_ascii=False, allow_nan=False)


def decode_save(raw):
    try:
        data = json.loads(raw)
        if data["version"] != SAVE_VERSION:
            return None
        p, q = data["player"], data["progress"]
        def number(key, low, high, default, integer=False):
            value = p.get(key, default)
            if type(value) not in (int, float) or not math.isfinite(value):
                value = default
            value = clamp(value, low, high)
            return int(value) if integer else float(value)
        player = Player()
        player.level = number("level", 1, 20, 1, True)
        player.x, player.y = number("x", 45, WORLD_W - 45, SPAWN[0]), number("y", 45, WORLD_H - 45, SPAWN[1])
        player.hp = number("hp", 1, player.max_hp, player.max_hp)
        player.mana = number("mana", 0, 100, 100)
        player.xp = number("xp", 0, player.next_xp - 1, 0, True)
        player.gold = number("gold", 0, 999999, 0, True)
        player.potions = number("potions", 0, 99, 3, True)
        player.armour = number("armour", 0, 3, 0, True)
        player.sword.tier = number("sword", 0, 3, 0, True)
        ids = {e.id for e in make_enemies(Progress())}
        crystals = {i for i in q.get("crystals", []) if type(i) is int and i in range(3)}
        defeated = {i for i in q.get("defeated", []) if isinstance(i, str) and i in ids}
        for i in crystals:
            defeated.update(f"shrine-{i}-{j}" for j in range(3))
        opened = {i for i in q.get("opened", []) if type(i) is int and i in range(len(CHESTS))}
        elapsed = q.get("play_time", 0)
        if type(elapsed) not in (int, float) or not math.isfinite(elapsed):
            elapsed = 0
        progress = Progress(bool(q.get("started")) or bool(crystals), crystals, defeated, opened,
                            bool(q.get("won")) and len(crystals) == 3 and "boss" in defeated,
                            clamp(elapsed, 0, 10 ** 8))
        if World().blocked(player.x, player.y):
            player.x, player.y = SPAWN
        return player, progress
    except (ValueError, TypeError, KeyError, AttributeError):
        return None


class SaveStore:
    def __init__(self, path=None):
        self.path = Path(path) if path else Path(os.environ.get("ECHO_FOREST_SAVE", str(Path.home() / ".echo_forest" / "save.json")))
        self.error = ""

    def read(self):
        try:
            if sys.platform == "emscripten":
                import platform
                raw = platform.window.localStorage.getItem(SAVE_KEY)
            else:
                raw = self.path.read_text(encoding="utf-8") if self.path.exists() else None
            return decode_save(str(raw)) if raw else None
        except Exception as exc:
            self.error = str(exc)
            return None

    def write(self, player, progress):
        try:
            raw = encode_save(player, progress)
            if sys.platform == "emscripten":
                import platform
                platform.window.localStorage.setItem(SAVE_KEY, raw)
            else:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                temp = self.path.with_suffix(".tmp")
                temp.write_text(raw, encoding="utf-8")
                temp.replace(self.path)
            self.error = ""
            return True
        except Exception as exc:
            self.error = str(exc)
            return False
