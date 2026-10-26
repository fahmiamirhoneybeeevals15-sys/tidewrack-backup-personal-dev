extends SceneTree
## Run: godot --headless --path . --script tests/test_dialogue_manager.gd
## Uses an isolated temporary dialogue file; never reads or writes save.json.

const FIXTURE := "user://test_dialogue_manager_fixture.json"
var manager: Node
var state: Node
var shown: Array = []
var last_text: String = ""
var failures := 0
var writes := 0
var finishes := 0


func _initialize() -> void:
	call_deferred("_run")


func _check(ok: bool, label: String) -> void:
	if not ok:
		failures += 1
		push_error(label)


func _line(_speaker: String, text: String, choices: Array) -> void:
	last_text = text
	shown = choices


func _play(choices: Array, entry_flags: Dictionary = {}) -> void:
	var graph := {
		"start": {"text": "Pick", "set_flag": entry_flags, "choices": choices},
		"picked": {"text": "Correct target", "next": null},
	}
	var file := FileAccess.open(FIXTURE, FileAccess.WRITE)
	file.store_string(JSON.stringify(graph))
	file.close()
	_check(manager.start(FIXTURE), "fixture starts")


func _run() -> void:
	manager = root.get_node("DialogueManager")
	state = root.get_node("GameState")
	manager.line_shown.connect(_line)
	state.state_changed.connect(func(): writes += 1)
	manager.dialogue_finished.connect(func(): finishes += 1)
	var hidden := {
		"text": "Hidden", "requires_flags": {"gate": true},
		"set_flag": {"wrong": true}, "next": null,
	}
	var visible := {
		"text": "Visible", "set_flag": {"correct": true}, "next": "picked",
	}
	state.new_game()
	_play([hidden, visible])
	_check(shown.size() == 1 and shown[0]["text"] == "Visible", "hidden first choice removed")
	manager.choose(-1)
	manager.choose(1)
	manager.advance()
	_check(manager.is_active and not state.get_flag("correct"), "invalid indices and advance do nothing")
	manager.choose(0)
	_check(state.get_flag("correct") and not state.get_flag("wrong"), "display index 0 applies visible effects")
	_check(last_text == "Correct target" and shown.is_empty(), "visible choice follows its target")
	manager.choose(0)
	_check(manager.is_active, "linear node has no cached choices")
	manager.advance()
	_check(not manager.is_active, "linear terminal ends")

	state.new_game()
	_play([visible, hidden, {"text": "Last", "next": null, "set_flag": {"last": true}}])
	manager.choose(1)
	_check(state.get_flag("last") and not state.get_flag("wrong"), "hidden middle choice preserves indices")
	_check(not manager.is_active, "null choice target ends")

	state.new_game()
	_play([hidden, visible])
	state.set_flag("gate", true)
	manager.choose(0)
	_check(state.get_flag("correct") and not state.get_flag("wrong"), "newly unlocked choice cannot shift displayed indices")
	manager.advance()

	state.new_game()
	_play([hidden, visible], {"gate": true})
	_check(shown.size() == 2, "entry effects run before filtering")
	state.set_flag("gate", false)
	var before := writes
	manager.choose(0)
	_check(writes == before and not state.get_flag("wrong"), "revoked choice applies no effects and does not replay entry effects")
	_check(shown.size() == 1 and shown[0]["text"] == "Visible", "revoked choice refreshes display")
	manager.choose(0)
	_check(state.get_flag("correct"), "refreshed index selects fallback")
	manager.advance()

	state.new_game()
	var finished_before := finishes
	_play([hidden])
	_check(not manager.is_active and finishes == finished_before + 1, "all-hidden node safely finishes")
	_check(not state.get_flag("wrong"), "hidden effects never apply")
	manager.choose(0)

	state.new_game()
	_play([{"text": "Only", "requires_flags": {"gate": true}, "next": null}], {"gate": true})
	state.set_flag("gate", false)
	manager.choose(0)
	_check(not manager.is_active, "revoking last eligible choice safely finishes")

	state.new_game()
	_play([{"text": "Absent false", "requires_flags": {"gate": false}, "next": null}])
	_check(shown.size() == 1, "missing saved flag satisfies false")
	manager.choose(0)
	_check(not manager.is_active, "absent-false choice can end dialogue")

	state.new_game()
	_play([visible])
	shown[0]["set_flag"]["correct"] = false
	shown.clear()
	manager.choose(0)
	_check(state.get_flag("correct"), "UI cannot mutate cached choices")
	manager.advance()

	DirAccess.remove_absolute(FIXTURE)
	print("Dialogue manager failures: %d" % failures)
	quit(1 if failures else 0)
