#!/usr/bin/env python3
"""Conway's Game of Life — ASCII renderer with pattern detection."""
import random
import time
import json
import sys

PATTERNS = {
    "glider": [(0,1),(1,2),(2,0),(2,1),(2,2)],
    "r_pentomino": [(0,1),(0,2),(1,0),(1,1),(2,1)],
    "gosper_gun": [
        (0,24),(1,22),(1,24),(2,12),(2,13),(2,20),(2,21),(2,34),(2,35),
        (3,11),(3,15),(3,20),(3,21),(3,34),(3,35),(4,0),(4,1),(4,10),
        (4,16),(4,20),(4,21),(5,0),(5,1),(5,10),(5,14),(5,16),(5,17),
        (5,22),(5,24),(6,10),(6,16),(6,24),(7,11),(7,15),(8,12),(8,13),
    ],
    "acorn": [(0,1),(1,3),(2,0),(2,1),(2,4),(2,5),(2,6)],
    "diehard": [(0,6),(1,0),(1,1),(2,1),(2,5),(2,6),(2,7)],
}

class GameOfLife:
    def __init__(self, width=60, height=25, pattern=None):
        self.w = width
        self.h = height
        self.grid = set()
        if pattern and pattern in PATTERNS:
            ox, oy = height // 3, width // 3
            for r, c in PATTERNS[pattern]:
                self.grid.add((r + ox, c + oy))
            self.pattern_name = pattern
        else:
            # Random seed ~20% density
            for r in range(height):
                for c in range(width):
                    if random.random() < 0.2:
                        self.grid.add((r, c))
            self.pattern_name = "random"
        self.gen = 0
        self.prev_counts = []

    def step(self):
        neighbors = {}
        for r, c in self.grid:
            for dr in (-1, 0, 1):
                for dc in (-1, 0, 1):
                    if dr == 0 and dc == 0:
                        continue
                    nr, nc = (r + dr) % self.h, (c + dc) % self.w
                    neighbors[(nr, nc)] = neighbors.get((nr, nc), 0) + 1
        new = set()
        for pos, cnt in neighbors.items():
            if cnt == 3 or (cnt == 2 and pos in self.grid):
                new.add(pos)
        self.grid = new
        self.gen += 1
        self.prev_counts.append(len(self.grid))
        if len(self.prev_counts) > 20:
            self.prev_counts.pop(0)

    def render(self):
        lines = []
        for r in range(self.h):
            row = ""
            for c in range(self.w):
                row += "█" if (r, c) in self.grid else " "
            lines.append(row)
        return "\n".join(lines)

    def detect_event(self):
        if len(self.grid) == 0:
            return "extinction"
        if len(self.prev_counts) >= 5:
            last5 = self.prev_counts[-5:]
            if len(set(last5)) == 1:
                return "still_life"
            if len(self.prev_counts) >= 10:
                last10 = self.prev_counts[-10:]
                if last10[:5] == last10[5:]:
                    return "oscillator"
        return None

    def stats(self):
        return {
            "generation": self.gen,
            "live_cells": len(self.grid),
            "pattern": self.pattern_name,
        }


def run_game(generations=500, width=60, height=25, callback=None):
    pattern = random.choice(list(PATTERNS.keys()) + ["random"] * 2)
    game = GameOfLife(width, height, pattern if pattern != "random" else None)
    if pattern == "random":
        game.pattern_name = "random"

    for _ in range(generations):
        frame = game.render()
        event = game.detect_event()
        stats = game.stats()

        if callback:
            callback(frame, stats, event)

        if event == "extinction":
            break

        game.step()
        time.sleep(0.15)

    return game.stats()


if __name__ == "__main__":
    if "--test" in sys.argv:
        def printer(frame, stats, event):
            print(f"\033[H\033[J{frame}")
            print(f"Gen: {stats['generation']} | Cells: {stats['live_cells']} | Pattern: {stats['pattern']}")
            if event:
                print(f"EVENT: {event}")
        run_game(generations=100, callback=printer)
    else:
        print(json.dumps(run_game(generations=50)))
