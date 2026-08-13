extends Node
"""
Global Input Manager for handling player input actions.
Provides unified input handling with action mapping and state tracking.
"""

# ============================================================================
# SIGNALS
# ============================================================================

signal input_action_pressed(action: String)
signal input_action_released(action: String)
signal input_axis_changed(axis: String, value: float)
signal input_method_changed(method: String) # "keyboard", "mouse", "gamepad"

# ============================================================================
# INPUT ACTIONS (Standard set for all generated games)
# ============================================================================

const STANDARD_ACTIONS = {
	# Movement
	"move_left": ["A", "Left", "joy_left"],
	"move_right": ["D", "Right", "joy_right"],
	"move_up": ["W", "Up", "joy_up"],
	"move_down": ["S", "Down", "joy_down"],
	
	# Actions
	"interact": ["E", "Enter", "ui_accept"],
	"attack": ["Space", "MouseButtonLeft", "joy_button_0"],
	"jump": ["Space", "X", "joy_button_0"],
	"dash": ["Shift", "joy_button_1"],
	
	# UI
	"pause": ["Escape", "ui_cancel"],
	"inventory": ["I", "Tab"],
	"quest_log": ["Q"],
	"dialogue_next": ["Space", "Enter", "MouseButtonLeft"],
	
	# System
	"screenshot": ["F12"],
	"debug_console": ["F1", "tilde"]
}

# ============================================================================
# PROPERTIES
# ============================================================================

var active_actions: Dictionary = {}
var last_input_method: String = "keyboard"
var input_sensitivity: float = 1.0
var deadzone: float = 0.15

# Action state tracking
var _action_states: Dictionary = {}
var _action_press_time: Dictionary = {}
var _axis_values: Dictionary = {}

# ============================================================================
# PUBLIC API
# ============================================================================

func register_action(action_name: String, inputs: Array = []) -> bool:
	"""
	Register a new input action at runtime.
	inputs: Array of input identifiers (key names, mouse buttons, etc.)
	"""
	if action_name in active_actions:
		return false
	
	active_actions[action_name] = inputs
	_action_states[action_name] = false
	_action_press_time[action_name] = 0.0
	return true

func unregister_action(action_name: String) -> void:
	"""Unregister an input action."""
	active_actions.erase(action_name)
	_action_states.erase(action_name)
	_action_press_time.erase(action_name)

func is_action_pressed(action_name: String) -> bool:
	"""Check if an action is currently pressed."""
	if not action_name in active_actions:
		return Input.is_action_pressed(action_name)
	return _action_states.get(action_name, false)

func is_action_just_pressed(action_name: String) -> bool:
	"""Check if an action was just pressed this frame."""
	if not action_name in active_actions:
		return Input.is_action_just_pressed(action_name)
	
	var current = _action_states.get(action_name, false)
	var previous = _action_states.get(action_name + "_prev", false)
	return current and not previous

func is_action_just_released(action_name: String) -> bool:
	"""Check if an action was just released this frame."""
	if not action_name in active_actions:
		return Input.is_action_just_released(action_name)
	
	var current = _action_states.get(action_name, false)
	var previous = _action_states.get(action_name + "_prev", false)
	return not current and previous

func get_action_strength(action_name: String) -> float:
	"""Get the strength of an action press (0.0 to 1.0)."""
	if not action_name in active_actions:
		return Input.get_action_strength(action_name)
	return 1.0 if _action_states.get(action_name, false) else 0.0

func get_axis(negative_action: String, positive_action: String) -> float:
	"""Get axis value from two actions (-1.0 to 1.0)."""
	var negative = get_action_strength(negative_action) * -1.0
	var positive = get_action_strength(positive_action)
	var value = negative + positive
	
	# Apply deadzone
	if abs(value) < deadzone:
		value = 0.0
	
	return clamp(value, -1.0, 1.0)

func get_vector(horizontal_neg: String, horizontal_pos: String, 
				vertical_neg: String, vertical_pos: String) -> Vector2:
	"""Get 2D movement vector from four actions."""
	var x = get_axis(horizontal_neg, horizontal_pos)
	var y = get_axis(vertical_neg, vertical_pos)
	return Vector2(x, y).normalized()

func get_mouse_position() -> Vector2:
	"""Get current mouse position in viewport coordinates."""
	return get_viewport().get_mouse_position()

func get_mouse_global_position() -> Vector2:
	"""Get mouse position in global world coordinates."""
	var camera = get_viewport().get_camera_2d()
	if camera:
		return camera.get_global_mouse_position()
	return get_mouse_position()

func is_mouse_button_pressed(button_index: MouseButton) -> bool:
	"""Check if a mouse button is pressed."""
	return Input.is_mouse_button_pressed(button_index)

func get_joy_axis_value(device: int, axis: JoyAxis) -> float:
	"""Get gamepad axis value with deadzone applied."""
	var value = Input.get_joy_axis(device, axis)
	if abs(value) < deadzone:
		return 0.0
	return value

func set_action_enabled(action_name: String, enabled: bool) -> void:
	"""Enable or disable a specific action."""
	Input.set_action_enabled(action_name, enabled)

func enable_all_actions() -> void:
	"""Enable all registered actions."""
	for action in active_actions.keys():
		Input.set_action_enabled(action, true)

func disable_all_actions() -> void:
	"""Disable all registered actions."""
	for action in active_actions.keys():
		Input.set_action_enabled(action, false)

func get_last_input_method() -> String:
	"""Get the last used input method (keyboard/mouse/gamepad)."""
	return last_input_method

func set_deadzone(value: float) -> void:
	"""Set the deadzone for analog inputs."""
	deadzone = clamp(value, 0.0, 0.5)

func set_sensitivity(value: float) -> void:
	"""Set input sensitivity multiplier."""
	input_sensitivity = max(0.1, value)

# ============================================================================
# INPUT MAPPING
# ============================================================================

func setup_default_input_map() -> void:
	"""Setup default input map with standard actions."""
	# Clear existing actions first (optional)
	# InputMap.load_from_project_settings()
	
	# Add standard actions
	for action_name in STANDARD_ACTIONS.keys():
		if not InputMap.has_action(action_name):
			InputMap.add_action(action_name)
		
		var inputs = STANDARD_ACTIONS[action_name]
		for input_key in inputs:
			var event = _create_input_event(input_key)
			if event:
				InputMap.action_add_event(action_name, event)
	
	print("[InputManager] Setup %d default actions" % STANDARD_ACTIONS.size())

func add_key_to_action(action_name: String, key: String) -> void:
	"""Add a key binding to an action."""
	var event = _create_input_event(key)
	if event:
		InputMap.action_add_event(action_name, event)

func remove_key_from_action(action_name: String, key: String) -> void:
	"""Remove a key binding from an action."""
	var event = _create_input_event(key)
	if event:
		InputMap.action_erase_event(action_name, event)

func rebind_action(action_name: String, new_inputs: Array) -> void:
	"""Rebind an action to new inputs."""
	# Remove all existing bindings
	InputMap.action_erase_events(action_name)
	
	# Add new bindings
	for input_key in new_inputs:
		var event = _create_input_event(input_key)
		if event:
			InputMap.action_add_event(action_name, event)

func get_action_bindings(action_name: String) -> Array:
	"""Get all input bindings for an action."""
	var bindings = []
	var events = InputMap.action_get_events(action_name)
	for event in events:
		bindings.append(_event_to_string(event))
	return bindings

# ============================================================================
# INTERNAL METHODS
# ============================================================================

func _create_input_event(key: String) -> InputEvent:
	"""Create an InputEvent from a string identifier."""
	key = key.strip_edges()
	
	# Keyboard keys
	if key.length() == 1 or key in ["Enter", "Space", "Escape", "Shift", "Ctrl", "Alt", "Tab"]:
		var event = InputEventKey.new()
		var keycode = _string_to_keycode(key)
		if keycode != KEY_NONE:
			event.keycode = keycode
			event.physical_keycode = keycode
			return event
	
	# Mouse buttons
	if key.begins_with("Mouse"):
		var event = InputEventMouseButton.new()
		match key:
			"MouseButtonLeft":
				event.button_index = MOUSE_BUTTON_LEFT
			"MouseButtonRight":
				event.button_index = MOUSE_BUTTON_RIGHT
			"MouseButtonMiddle":
				event.button_index = MOUSE_BUTTON_MIDDLE
		return event
	
	# Gamepad buttons
	if key.begins_with("joy_button_"):
		var event = InputEventJoypadButton.new()
		var button_idx = int(key.split("_")[2])
		event.button_index = button_idx
		return event
	
	# Gamepad axes
	if key in ["joy_left", "joy_right", "joy_up", "joy_down"]:
		var event = InputEventJoypadMotion.new()
		event.axis = JOY_AXIS_LEFT_HORIZONTAL if key in ["joy_left", "joy_right"] else JOY_AXIS_LEFT_VERTICAL
		event.axis_value = -1.0 if key in ["joy_left", "joy_up"] else 1.0
		return event
	
	# UI actions
	if key.begins_with("ui_"):
		var event = InputEventKey.new()
		# Godot has built-in UI actions
		return null
	
	return null

func _string_to_keycode(key: String) -> Key:
	"""Convert string to Key enum value."""
	match key:
		"A": return KEY_A
		"B": return KEY_B
		"C": return KEY_C
		"D": return KEY_D
		"E": return KEY_E
		"F": return KEY_F
		"G": return KEY_G
		"H": return KEY_H
		"I": return KEY_I
		"J": return KEY_J
		"K": return KEY_K
		"L": return KEY_L
		"M": return KEY_M
		"N": return KEY_N
		"O": return KEY_O
		"P": return KEY_P
		"Q": return KEY_Q
		"R": return KEY_R
		"S": return KEY_S
		"T": return KEY_T
		"U": return KEY_U
		"V": return KEY_V
		"W": return KEY_W
		"X": return KEY_X
		"Y": return KEY_Y
		"Z": return KEY_Z
		"0": return KEY_0
		"1": return KEY_1
		"2": return KEY_2
		"3": return KEY_3
		"4": return KEY_4
		"5": return KEY_5
		"6": return KEY_6
		"7": return KEY_7
		"8": return KEY_8
		"9": return KEY_9
		"Enter": return KEY_ENTER
		"Space": return KEY_SPACE
		"Escape": return KEY_ESCAPE
		"Shift": return KEY_SHIFT
		"Tab": return KEY_TAB
		"Up": return KEY_UP
		"Down": return KEY_DOWN
		"Left": return KEY_LEFT
		"Right": return KEY_RIGHT
	_: return KEY_NONE

func _event_to_string(event: InputEvent) -> String:
	"""Convert InputEvent to string representation."""
	if event is InputEventKey:
		return OS.get_keycode_string(event.keycode)
	elif event is InputEventMouseButton:
		return "Mouse" + str(event.button_index)
	elif event is InputEventJoypadButton:
		return "joy_button_" + str(event.button_index)
	elif event is InputEventJoypadMotion:
		return "joy_axis_" + str(event.axis)
	return "unknown"

func _detect_input_method() -> void:
	"""Detect and update the current input method."""
	# Check gamepad input
	for device_id in Input.get_connected_joypads():
		for axis in range(JOY_AXIS_MAX):
			if abs(Input.get_joy_axis(device_id, axis)) > deadzone:
				last_input_method = "gamepad"
				return
		
		for button in range(JOY_BUTTON_MAX):
			if Input.is_joy_button_pressed(device_id, button):
				last_input_method = "gamepad"
				return
	
	# Check mouse input
	if Input.get_mouse_position() != get_mouse_position():
		last_input_method = "mouse"
		return
	
	# Default to keyboard
	last_input_method = "keyboard"

# ============================================================================
# PROCESSING
# ============================================================================

func _input(event: InputEvent) -> void:
	"""Process input events."""
	_detect_input_method()
	
	# Emit signal for input method change
	input_method_changed.emit(last_input_method)

func _process(delta: float) -> void:
	"""Update input states each frame."""
	# Update action states
	for action_name in active_actions.keys():
		var prev_state = _action_states.get(action_name, false)
		_action_states[action_name + "_prev"] = prev_state
		
		var current_state = Input.is_action_pressed(action_name)
		_action_states[action_name] = current_state
		
		# Track press duration
		if current_state:
			if not _action_press_time.has(action_name):
				_action_press_time[action_name] = 0.0
			_action_press_time[action_name] += delta
		else:
			_action_press_time[action_name] = 0.0
		
		# Emit signals
		if current_state and not prev_state:
			input_action_pressed.emit(action_name)
		elif not current_state and prev_state:
			input_action_released.emit(action_name)
	
	# Update axis values
	for action_name in active_actions.keys():
		if _axis_values.has(action_name):
			_axis_values[action_name] = get_action_strength(action_name)

func get_action_hold_duration(action_name: String) -> float:
	"""Get how long an action has been held continuously."""
	return _action_press_time.get(action_name, 0.0)

# ============================================================================
# INITIALIZATION
# ============================================================================

func _ready() -> void:
	setup_default_input_map()
	print("[InputManager] Initialized with %d standard actions" % STANDARD_ACTIONS.size())
