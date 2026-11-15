"""Version 1 - the LLM *is* the whole game.

The room, the puzzles AND the solutions all live inside one system prompt.
The model is trusted to remember what happened and to apply the rules.
There is no structured state and no validation in Python (that is Version 2).
"""
from __future__ import annotations

from common.llm_client import generate

ESCAPE_TOKEN = "[[ESCAPED]]"

INTRO = (
    "You wake up on a cold stone floor. Dust drifts in the dim light of a single "
    "lamp. You are inside a **locked library**. In front of you stand a heavy "
    "**desk**, a tall **bookshelf**, a large **painting**, a small **locked drawer**, "
    "and a **door** secured with a four-digit code.\n\n"
    "Explore, collect items, and find the clues to escape. What do you do?"
)

SYSTEM_PROMPT = f"""You are the Game Master of a text-based escape room called "The Locked Library".
Stay in character, write 2-4 atmospheric sentences per reply, and always end by letting the player act.

THE ROOM (secret - only reveal things as the player discovers them):
- Desk: holds a brass magnifying glass and a scrap of paper saying "Not all books on the shelf are equal. Look for the four that stand out." The player may take the magnifying glass.
- Bookshelf: four red books are arranged differently from the rest. Inside their front covers are handwritten numbers, left to right: 3, 1, 4, 2.
- Locked drawer: has a four-digit combination lock. The code is 3142 (the numbers in the red books). Inside is a small brass key.
- Painting: a stormy seascape with a lighthouse. Tiny scratches in the waves can only be read with the magnifying glass: they spell the numerals 9 0 2 6.
- Door: a keypad hidden behind a locked metal plate. The brass key opens the plate. The keypad code is 9026.

RULES:
1. The player escapes only by: finding the drawer code (3142), taking the brass key, using the key on the door's plate, reading the painting with the magnifying glass (9026), and entering 9026 on the door keypad.
2. Reveal clues only when the player examines the right object. Never reveal codes or solutions otherwise.
3. Remember everything the player has done and collected during this conversation.
4. Only the objects described above exist. Do not invent new ones.
5. When (and only when) the player correctly opens the door, describe their escape and put the exact token {ESCAPE_TOKEN} at the very end of your reply.
"""


class GameSession:
    """Holds the running conversation. That conversation is the only 'memory'."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.escaped = False
        # Gemini wants the first turn to come from the user.
        self.history: list[dict] = [
            {"role": "user", "content": "Start the game."},
            {"role": "assistant", "content": INTRO},
        ]

    def send(self, player_text: str) -> str:
        """Send the player's message to the LLM and return the Game Master reply."""
        self.history.append({"role": "user", "content": player_text})
        try:
            reply = generate(SYSTEM_PROMPT, self.history, temperature=0.8)
        except Exception:
            self.history.pop()  # keep the conversation consistent on failure
            raise
        if ESCAPE_TOKEN in reply:
            self.escaped = True
            reply = reply.replace(ESCAPE_TOKEN, "").strip()
        self.history.append({"role": "assistant", "content": reply})
        return reply
