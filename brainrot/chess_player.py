#!/usr/bin/env python3
"""Stockfish auto-play with ASCII board + annotations."""
import chess
import chess.engine
import time
import json
import sys
import os

STOCKFISH_PATH = "/usr/games/stockfish"
PIECE_SYMBOLS = {
    "R": "♜", "N": "♞", "B": "♝", "Q": "♛", "K": "♚", "P": "♟",
    "r": "♖", "n": "♘", "b": "♗", "q": "♕", "k": "♔", "p": "♙",
}

def render_board(board):
    """Render board as ASCII art."""
    lines = ["  a b c d e f g h"]
    lines.append(" ┌─┬─┬─┬─┬─┬─┬─┬─┐")
    for rank in range(7, -1, -1):
        row = f"{rank+1}│"
        for file in range(8):
            sq = chess.square(file, rank)
            piece = board.piece_at(sq)
            if piece:
                sym = PIECE_SYMBOLS.get(piece.symbol(), piece.symbol())
            else:
                sym = "·" if (rank + file) % 2 == 0 else " "
            row += f"{sym}│"
        lines.append(row)
        if rank > 0:
            lines.append(" ├─┼─┼─┼─┼─┼─┼─┼─┤")
    lines.append(" └─┴─┴─┴─┴─┴─┴─┴─┘")
    lines.append(f"  {'White' if board.turn else 'Black'} to move")
    return "\n".join(lines)


def play_game(depth=5, callback=None):
    """Play a full game of Stockfish vs itself."""
    if not os.path.exists(STOCKFISH_PATH):
        return {"error": "stockfish not installed"}

    engine = chess.engine.SimpleEngine.popen_uci(STOCKFISH_PATH)
    board = chess.Board()
    moves = []
    move_num = 0

    try:
        while not board.is_game_over() and move_num < 200:
            result = engine.play(board, chess.engine.Limit(depth=depth))
            move = result.move
            san = board.san(move)
            board.push(move)
            move_num += 1
            moves.append(san)

            if callback:
                frame = render_board(board)
                info = {
                    "move_num": move_num,
                    "move": san,
                    "fen": board.fen(),
                    "moves_so_far": " ".join(moves[-10:]),
                }
                callback(frame, info)

            time.sleep(0.8)

        # Game over
        result_str = board.result()
        outcome = board.outcome()
        winner = "Draw"
        if outcome and outcome.winner is not None:
            winner = "White" if outcome.winner else "Black"

        summary = {
            "result": result_str,
            "winner": winner,
            "total_moves": move_num,
            "final_fen": board.fen(),
            "last_moves": " ".join(moves[-6:]),
        }

        if callback:
            callback(render_board(board), {**summary, "game_over": True})

        return summary

    finally:
        engine.quit()


if __name__ == "__main__":
    if "--test" in sys.argv:
        def printer(frame, info):
            print(f"\033[H\033[J{frame}")
            if "game_over" in info:
                print(f"\nGAME OVER: {info['result']} ({info['winner']})")
            else:
                print(f"Move {info['move_num']}: {info['move']}")
        play_game(depth=5, callback=printer)
    else:
        print(json.dumps(play_game(depth=3)))
