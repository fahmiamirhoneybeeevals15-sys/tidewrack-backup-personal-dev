extends Node
## DialogueManager — plays JSON-driven branching dialogue graphs.
##
## Autoloaded as `DialogueManager`. A graph is a dictionary of node id -> node.
## Each node:
##   { "speaker": String, "text": String,
##     "next": String|null,                     # linear node; null ends the graph
##     "choices": [ {"text": String, "next": String, "set_flag": {..}} ],
##     "set_flag": { "flag_name": value } }      # applied when the node is entered
##
## Choices may include "requires_flags": {"flag_name": bool}; all must match.
## Missing requirements are unconditional. Checks never apply choice effects.
##
## UI (dialogue_box.gd) listens to these signals; it does not read the graph.

signal dialogue_started
signal line_shown(speaker: String, text: String, choices: Array)
signal dialogue_finished

var _graph: Dictionary = {}
var _current_id: String = ""
# Ordered snapshot sent to the UI; button indices refer only to this array.
var _visible_choices: Array = []
var is_active: bool = false


func start(path: String, start_id: String = "start") -> bool:
	var graph := _load_graph(path)
	if graph.is_empty():
		return false
	_visible_choices.clear()
	_graph = graph
	is_active = true
	dialogue_started.emit()
	_goto(start_id)
	return true


## Advance a linear node (no choices). Ignored while choices are pending.
func advance() -> void:
	if not is_active:
		return
	var node: Dictionary = _graph.get(_current_id, {})
	if not _visible_choices.is_empty():
		return  # waiting on choose()
	var next: Variant = node.get("next", null)
	if next == null:
		_finish()
	else:
		_goto(str(next))


## Pick the displayed choice `index`, never an index into the raw graph.
func choose(index: int) -> void:
	if not is_active:
		return
	if index < 0 or index >= _visible_choices.size():
		return
	var choice: Dictionary = _visible_choices[index]
	# Resolve the displayed snapshot BEFORE checking current state. Refiltering
	# first could silently map the clicked index to a different choice.
	if not GameState.meets_flag_requirements(choice.get("requires_flags", {})):
		_show_current_line()
		return
	_visible_choices.clear()
	_apply_flags(choice.get("set_flag", {}))
	var next: Variant = choice.get("next", null)
	if next == null:
		_finish()
	else:
		_goto(str(next))


func _goto(id: String) -> void:
	if not _graph.has(id):
		push_error("DialogueManager: missing node '%s'." % id)
		_finish()
		return
	_visible_choices.clear()
	_current_id = id
	var node: Dictionary = _graph[id]
	_apply_flags(node.get("set_flag", {}))
	_show_current_line()


## Refresh display without reapplying node-entry effects.
func _show_current_line() -> void:
	var node: Dictionary = _graph[_current_id]
	_visible_choices.clear()
	var choices: Array = node.get("choices", [])
	for choice in choices:
		if GameState.meets_flag_requirements(choice.get("requires_flags", {})):
			_visible_choices.append(choice.duplicate(true))
	if not choices.is_empty() and _visible_choices.is_empty():
		push_warning("DialogueManager: no eligible choices at node '%s'." % _current_id)
		_finish()
		return
	line_shown.emit(
		str(node.get("speaker", "")),
		str(node.get("text", "")),
		_visible_choices.duplicate(true)
	)


func _apply_flags(dict: Dictionary) -> void:
	for key in dict:
		GameState.set_flag(str(key), dict[key])


func _finish() -> void:
	is_active = false
	_visible_choices.clear()
	_graph = {}
	_current_id = ""
	dialogue_finished.emit()


func _load_graph(path: String) -> Dictionary:
	if not FileAccess.file_exists(path):
		push_error("DialogueManager: dialogue file not found: %s" % path)
		return {}
	var file := FileAccess.open(path, FileAccess.READ)
	var parsed: Variant = JSON.parse_string(file.get_as_text())
	file.close()
	if typeof(parsed) != TYPE_DICTIONARY:
		push_error("DialogueManager: dialogue file is not a JSON object: %s" % path)
		return {}
	return parsed
