"""Version 2 game engine: the single source of truth for the escape room.

* The room, puzzle solutions and rules live in ``game_config.json``.
* The mutable game state is a plain, JSON-serialisable dict.
* Every player action goes through :meth:`GameEngine.handle`, which validates it
  and either applies it or refuses it.  The LLM never decides whether an action
  succeeds - it only describes the outcome Python reports.
"""
from __future__ import annotations

import copy
import hmac
import json
import re
from pathlib import Path

CONFIG_PATH = Path(__file__).with_name("game_config.json")

ACTIONS = ("examine", "take", "use", "open", "enter_code", "inventory", "hint", "look", "help", "other")

HELP_TEXT = (
    "Type what you want to do in plain English. You can examine objects, take items, "
    "use an item on an object, try a four-digit code on a lock, check your inventory, "
    "look around, or ask for a hint."
)


def load_config(path: Path = CONFIG_PATH) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


class GameEngine:
    def __init__(self, config: dict | None = None) -> None:
        self.config = config or load_config()
        self.state = self.new_state()

    # ------------------------------------------------------------------ state
    def new_state(self) -> dict:
        cfg = self.config
        return {
            "turn": 0,
            "discovered_objects": list(cfg["starting_objects"]),
            "room_items": [],          # items lying in the room that can be taken
            "inventory": [],           # items the player carries
            "taken": [],               # every item ever picked up (for hints)
            "examined": [],            # objects the player has examined
            "puzzles": {pid: False for pid in cfg["puzzles"]},
            "locks": {oid: "locked" for oid, o in cfg["objects"].items() if "lock" in o},
            "wrong_attempts": 0,
            "escaped": False,
            "log": [],
        }

    def reset(self) -> None:
        self.state = self.new_state()

    def to_json(self) -> str:
        return json.dumps(self.state)

    def load_state(self, data: str | dict) -> None:
        loaded = json.loads(data) if isinstance(data, str) else copy.deepcopy(data)
        fresh = self.new_state()
        if set(loaded) != set(fresh):
            raise ValueError("Saved state does not match the game's state schema.")
        self.state = loaded

    def _snapshot(self) -> str:
        ignore = {"turn", "log", "wrong_attempts"}
        return json.dumps({k: v for k, v in self.state.items() if k not in ignore}, sort_keys=True)

    # --------------------------------------------------------------- lookups
    def _obj_name(self, oid: str) -> str:
        return self.config["objects"][oid]["name"]

    def _item_name(self, iid: str) -> str:
        return self.config["items"][iid]["name"]

    def _valid_object(self, oid) -> str | None:
        return oid if isinstance(oid, str) and oid in self.config["objects"] else None

    def _valid_item(self, iid) -> str | None:
        return iid if isinstance(iid, str) and iid in self.config["items"] else None

    def _is_discovered(self, oid: str) -> bool:
        return oid in self.state["discovered_objects"]

    def _find_alias(self, text: str, table: dict) -> str | None:
        """Longest-alias match on word boundaries (used by the offline parser)."""
        text = text.lower()
        best: tuple[int, str] | None = None
        for key, entry in table.items():
            for alias in entry["aliases"]:
                if re.search(rf"\b{re.escape(alias)}s?\b", text):
                    if best is None or len(alias) > best[0]:
                        best = (len(alias), key)
        return best[1] if best else None

    def find_object(self, text: str) -> str | None:
        return self._find_alias(text, self.config["objects"])

    def find_item(self, text: str) -> str | None:
        return self._find_alias(text, self.config["items"])

    def vocabulary(self) -> dict:
        """Names the player may legitimately refer to right now (no secrets)."""
        cfg, st = self.config, self.state
        visible_items = st["inventory"] + st["room_items"]
        return {
            "objects": {o: cfg["objects"][o]["aliases"] for o in st["discovered_objects"]},
            "items": {i: cfg["items"][i]["aliases"] for i in visible_items},
        }

    def public_state(self) -> dict:
        """Everything the UI / narrator may know. Contains no codes or solutions."""
        cfg, st = self.config, self.state
        return {
            "room": cfg["title"],
            "turn": st["turn"],
            "visible_objects": [self._obj_name(o) for o in st["discovered_objects"]],
            "items_in_room": [self._item_name(i) for i in st["room_items"]],
            "inventory": [self._item_name(i) for i in st["inventory"]],
            "solved_puzzles": [cfg["puzzles"][p] for p, done in st["puzzles"].items() if done],
            "door_status": "open" if st["locks"].get("door") == "open" else "locked",
            "escaped": st["escaped"],
        }

    # --------------------------------------------------------------- results
    @staticmethod
    def _res(ok: bool, code: str, message: str) -> dict:
        return {"ok": ok, "code": code, "message": message, "state_changed": False}

    # ---------------------------------------------------------------- entry
    def handle(self, action: dict) -> dict:
        """Validate and apply one action. Always returns a result dict."""
        if self.state["escaped"]:
            return self._res(False, "game_over", "The player has already escaped. The game is over.")

        act = action.get("action") if isinstance(action, dict) else None
        if act not in ACTIONS:
            act = "other"
        target, item, code = action.get("target"), action.get("item"), action.get("code")

        before = self._snapshot()
        handler = getattr(self, f"_do_{act}")
        if act in ("examine", "open"):
            result = handler(target, item)
        elif act == "take":
            result = handler(item, target)
        elif act == "use":
            result = handler(item, target)
        elif act == "enter_code":
            result = handler(target, code)
        else:
            result = handler()

        self.state["turn"] += 1
        result["state_changed"] = self._snapshot() != before
        self.state["log"].append(
            {"turn": self.state["turn"], "action": act, "target": target, "item": item, "result": result["code"]}
        )
        del self.state["log"][:-200]
        return result

    # --------------------------------------------------------------- actions
    def _unknown(self, code: str = "unknown_target") -> dict:
        return self._res(False, code, "You don't see anything like that here.")

    def _do_examine(self, target, item) -> dict:
        st = self.state
        oid, iid = self._valid_object(target), self._valid_item(item)
        if oid is None and iid is None:
            return self._unknown()
        if oid is None:  # examining an item
            if iid in st["inventory"] or iid in st["room_items"]:
                return self._res(True, "examined", self.config["items"][iid]["description"])
            return self._unknown()

        if not self._is_discovered(oid):
            return self._unknown()
        obj = self.config["objects"][oid]
        text = obj["examine"]
        lock = obj.get("lock")
        if lock and st["locks"][oid] == "open" and "examine_solved" in obj:
            text = obj["examine_solved"]
            left = [self._item_name(i) for i in lock.get("reveals_items", []) if i in st["room_items"]]
            if left:
                text += f" Inside you can see: {', '.join(left)}."
        if st["puzzles"].get("door_plate") and "examine_plate_open" in obj:
            text = obj["examine_plate_open"]

        if oid not in st["examined"]:
            st["examined"].append(oid)
        for new_item in obj.get("reveals_items", []):
            if new_item not in st["inventory"] + st["room_items"] + st["taken"]:
                st["room_items"].append(new_item)
        for new_obj in obj.get("reveals_objects", []):
            if new_obj not in st["discovered_objects"]:
                st["discovered_objects"].append(new_obj)
        return self._res(True, "examined", text)

    def _do_take(self, item, target) -> dict:
        st = self.state
        iid = self._valid_item(item)
        if iid is None:
            oid = self._valid_object(target)
            if oid is not None and self._is_discovered(oid):
                return self._res(False, "not_portable", f"You can't take the {self._obj_name(oid)}; it is not something you can carry.")
            return self._res(False, "unknown_target", "You don't see anything like that that you can pick up.")
        if iid in st["inventory"]:
            return self._res(False, "already_done", f"You are already carrying the {self._item_name(iid)}.")
        if iid not in st["room_items"]:
            return self._res(False, "unknown_target", "You don't see anything like that that you can pick up.")
        st["room_items"].remove(iid)
        st["inventory"].append(iid)
        if iid not in st["taken"]:
            st["taken"].append(iid)
        return self._res(True, "taken", f"You pick up the {self._item_name(iid)}.")

    def _do_use(self, item, target) -> dict:
        st = self.state
        iid, oid = self._valid_item(item), self._valid_object(target)
        if iid is None:
            return self._res(False, "missing_item", "You aren't carrying anything like that.")
        if iid not in st["inventory"]:
            if iid in st["room_items"]:
                return self._res(False, "missing_item", "You aren't carrying that yet - you would need to pick it up first.")
            return self._res(False, "missing_item", "You aren't carrying anything like that.")
        if oid is None or not self._is_discovered(oid):
            if target is None:
                return self._res(False, "missing_target", f"What do you want to use the {self._item_name(iid)} on?")
            return self._unknown()
        effect = self.config["objects"][oid].get("use_effects", {}).get(iid)
        if effect is None:
            return self._res(False, "no_effect", f"Using the {self._item_name(iid)} on the {self._obj_name(oid)} does nothing.")
        if st["puzzles"][effect["puzzle"]]:
            return self._res(False, "already_done", "You have already done that. " + effect["text"])
        st["puzzles"][effect["puzzle"]] = True
        return self._res(True, "puzzle_progress", effect["text"])

    def _do_open(self, target, item=None) -> dict:
        st = self.state
        oid = self._valid_object(target)
        if oid is None or not self._is_discovered(oid):
            return self._unknown()
        lock = self.config["objects"][oid].get("lock")
        if lock is None:
            return self._res(False, "no_lock", f"There is nothing to open on the {self._obj_name(oid)}.")
        if st["locks"][oid] == "open":
            return self._res(False, "already_done", f"The {self._obj_name(oid)} is already open.")
        req = lock.get("requires_puzzle")
        if req and not st["puzzles"][req]:
            return self._res(False, "locked", f"The {self._obj_name(oid)} is locked, and its mechanism is out of reach for now.")
        return self._res(False, "locked", f"The {self._obj_name(oid)} is locked. It needs the correct four-digit code.")

    def _do_enter_code(self, target, code) -> dict:
        st = self.state
        oid = self._valid_object(target)
        if oid is None:
            if target is None:
                return self._res(False, "missing_target", "Where do you want to enter that code?")
            return self._unknown()
        if not self._is_discovered(oid):
            return self._unknown()
        lock = self.config["objects"][oid].get("lock")
        if lock is None:
            return self._res(False, "no_lock", f"There is no lock or keypad on the {self._obj_name(oid)}.")
        digits = re.sub(r"\D", "", code) if isinstance(code, str) else ""
        if len(digits) != len(lock["code"]):
            return self._res(False, "bad_code_format", "A code must be exactly four digits.")
        if st["locks"][oid] == "open":
            return self._res(False, "already_done", f"The {self._obj_name(oid)} is already open.")
        req = lock.get("requires_puzzle")
        if req and not st["puzzles"][req]:
            return self._res(False, "locked", f"You can't enter a code on the {self._obj_name(oid)} yet - its keypad is out of reach.")
        if not hmac.compare_digest(digits, lock["code"]):
            st["wrong_attempts"] += 1
            return self._res(False, "wrong_code", f"The code {digits} does not work. The {self._obj_name(oid)} stays locked.")

        st["locks"][oid] = "open"
        st["puzzles"][lock["puzzle"]] = True
        for new_item in lock.get("reveals_items", []):
            if new_item not in st["inventory"] + st["room_items"] + st["taken"]:
                st["room_items"].append(new_item)
        if lock.get("ends_game"):
            st["escaped"] = True
            return self._res(True, "escaped", lock["success"])
        return self._res(True, "unlocked", lock["success"])

    def _do_inventory(self) -> dict:
        names = [self._item_name(i) for i in self.state["inventory"]]
        msg = "You are carrying: " + ", ".join(names) + "." if names else "You are not carrying anything."
        return self._res(True, "inventory", msg)

    def _do_look(self) -> dict:
        pub = self.public_state()
        msg = "You are in the locked library. You can see: " + ", ".join(pub["visible_objects"]) + "."
        if pub["items_in_room"]:
            msg += " Items within reach: " + ", ".join(pub["items_in_room"]) + "."
        return self._res(True, "look", msg)

    def _do_help(self) -> dict:
        return self._res(True, "help", HELP_TEXT)

    def _check(self, cond: str) -> bool:
        kind, _, key = cond.partition(":")
        st = self.state
        if kind == "examined":
            return key in st["examined"]
        if kind == "taken":
            return key in st["taken"]
        if kind == "puzzle":
            return bool(st["puzzles"].get(key))
        return False

    def _do_hint(self) -> dict:
        for hint in self.config["hints"]:
            if not self._check(hint["done"]):
                return self._res(True, "hint", hint["text"])
        return self._res(True, "hint", "You have everything you need. Try the exit.")

    def _do_other(self) -> dict:
        return self._res(
            False,
            "not_allowed",
            "That is not an action the player can take in this room. No game rule or state was changed.",
        )
