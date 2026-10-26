# Tidewrack

A narrative adventure set on a fog-bound island off the Washington coast. You
are the new keeper of **Cape Marrow Light**. The keeper before you, Edith Vane,
rowed out into the fog eleven days ago and did not come back.

Built solo by **Fogline Games** (Seattle) in **Godot 4**, shipping to Steam.

> **Status:** Public-demo candidate (Steam Next Fest). Vertical slice +
> branching conversation with save/load. See [`docs/milestones.md`](docs/milestones.md)
> for the road to launch.

## Controls

| Action        | Key                     |
|---------------|-------------------------|
| Move          | Arrow keys              |
| Interact      | Enter / Space           |
| Advance / skip line | Enter / Space     |
| Pause / back  | Esc                     |

The game uses only Godot's built-in input actions, so it works with no input
remapping (controller support and remappable keys are a Public Demo milestone).

## Running it

Requires **Godot 4.3+** (standard, non-.NET build).

```bash
# Open in the editor
godot -e --path .

# Or run directly
godot --path .
```

The main scene is `scenes/main_menu.tscn`. Saves are written to Godot's
`user://save.json` (per-OS user data dir).

## Project layout

```
tidewrack/
├── project.godot            # engine config; registers the two autoloads
├── scenes/                  # thin .tscn wrappers (root node + script)
│   ├── main_menu.tscn
│   ├── game.tscn            # the vertical-slice level
│   └── ui/{dialogue_box,settings}.tscn
├── scripts/
│   ├── autoload/
│   │   ├── game_state.gd     # story flags + save/load  (autoload: GameState)
│   │   └── dialogue_manager.gd  # branching graph player (autoload: DialogueManager)
│   ├── main_menu.gd, settings.gd
│   ├── game.gd               # builds the level + HUD + pause menu
│   ├── player.gd             # top-down movement (Player)
│   ├── interactable.gd       # examinable world object (Interactable)
│   └── dialogue_box.gd       # dialogue UI, listens to DialogueManager
├── data/dialogue/
│   └── keeper_intro.json     # the keeper's-log conversation
├── assets/{sprites,audio,fonts}/   # placeholder art for now
├── tests/validate_dialogue.py      # engine-free dialogue-graph checker
└── docs/                     # GDD, narrative bible, milestones, credits
```

**Design note:** UI and levels are constructed in GDScript rather than authored
as large scene files. This keeps `.tscn` files small and reviewable in diffs and
avoids merge pain — a deliberate choice for a one-person studio.

## The dialogue system

Conversations are plain JSON graphs in `data/dialogue/`. Each node is either a
linear line (`"next": "<id>"`, or `null` to end) or a choice node (`"choices"`).
Any node can set story flags via `"set_flag"`, which `GameState` persists.

```json
{
  "start": { "speaker": "Edith", "text": "…", "next": "choice1" },
  "choice1": {
    "text": "…",
    "choices": [
      { "text": "Trust her", "next": "end", "set_flag": { "trusted_edith": true } }
    ]
  },
  "end": { "speaker": "", "text": "…", "next": null }
}
```

Dialogue choices may include an optional `requires_flags` object, such as `"requires_flags": {"trusted_edith": true}`; the choice is shown only when every listed boolean matches `GameState`. Allowed flag names are `skeptic`, `believer`, `trusted_edith`, and `radioed_tom`. Missing flags count as `false`, so a false requirement also matches an unset flag; omit `requires_flags` or use `{}` for an unconditional choice. Node `set_flag` effects run before filtering, while choice effects run only after selection and a fresh prerequisite check. The manager resolves button indices against the displayed choices, keeping hidden options from shifting selections. Keep an unconditional fallback at each choice node, and run `python3 tests/validate_dialogue.py` to check flag names, prerequisites, reachability, and dead ends. Conditions live in dialogue JSON and do not change the save format.

## Verifying changes

```bash
# Validate every dialogue graph (targets resolve, has an ending, no orphans)
python3 tests/validate_dialogue.py

# In-engine checks (requires Godot on PATH)
godot --headless --path . --check-only   # parse all scripts
```

> The GDScript in this build was authored without a local Godot install, so it
> has been checked statically and via the dialogue validator, **not** yet run in
> the engine. First engine open may surface minor fixups — tracked in the issue
> list.

## Steam Next Fest demo

The public demo (target: **Steam Next Fest**) extends the vertical slice with
the lamp-room chapter, a discovered-logs journal, and controller support. Demo
scope is locked in [`docs/milestones.md`](docs/milestones.md); the build is
feature-frozen and tagged `v0.2-demo-rc`.

Demo controls add a gamepad (analog stick + A/B) on top of the keyboard bindings.
