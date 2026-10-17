# /// script
# dependencies = ["pygame-ce"]
# ///
"""Pygbag entry point. Desktop users may also run RPG_Game.py directly."""
import asyncio
import pygame
from RPG_Game import main

asyncio.run(main())
