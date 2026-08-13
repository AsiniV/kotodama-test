extends Node
"""
Global Signal Bus for inter-module communication.
All modules communicate exclusively through this bus using signals.
Core engine signals are fixed; module channels are dynamic.
"""

# ============================================================================
# CORE SIGNALS (Fixed - Cannot be modified by modules)
# ============================================================================

# Game lifecycle
signal game_started()
signal game_paused()
signal game_resumed()
signal game_ended(reason: String)
signal scene_changed(old_scene: String, new_scene: String)

# Player state
signal player_spawned(player_node: Node)
signal player_died()
signal player_health_changed(old_health: float, new_health: float)
signal player_inventory_changed()

# Save/Load system
signal save_requested(slot: int)
signal save_completed(success: bool, slot: int)
signal load_requested(slot: int)
signal load_completed(success: bool, slot: int)

# UI events
signal ui_show_main_menu()
signal ui_show_pause_menu()
signal ui_show_game_over()
signal ui_show_victory()

# ============================================================================
# MODULE CHANNELS (Dynamic - Registered by modules)
# ============================================================================

# Module channel registry
var _channel_registry: Dictionary = {}

# Module-specific signals (examples)
signal module_enemy_defeated(enemy_id: String, score: int)
signal module_item_collected(item_id: String, count: int)
signal module_quest_started(quest_id: String)
signal module_quest_completed(quest_id: String, rewards: Array)
signal module_quest_stage_changed(quest_id: String, stage_id: String)
signal module_dialogue_started(dialogue_id: String, npc_id: String)
signal module_dialogue_ended(dialogue_id: String)
signal module_level_loaded(level_id: String)
signal module_checkpoint_reached(checkpoint_id: String)

# ============================================================================
# PUBLIC API
# ============================================================================

func register_channel(channel_name: String) -> bool:
	"""
	Register a new module channel.
	Returns true if successful, false if channel already exists.
	"""
	if channel_name in _channel_registry:
		push_warning("SignalBus: Channel '%s' already registered" % channel_name)
		return false
	
	_channel_registry[channel_name] = true
	return true

func unregister_channel(channel_name: String) -> void:
	"""Unregister a module channel."""
	_channel_registry.erase(channel_name)

func is_channel_registered(channel_name: String) -> bool:
	"""Check if a channel is registered."""
	return channel_name in _channel_registry

func get_registered_channels() -> Array:
	"""Get list of all registered channels."""
	return _channel_registry.keys()

func validate_module_signals(module_name: String, required_signals: Array) -> Dictionary:
	"""
	Validate that a module has all required signals connected.
	Returns {valid: bool, missing: Array, errors: Array}
	"""
	var result = {
		"valid": true,
		"missing": [],
		"errors": []
	}
	
	for signal_name in required_signals:
		var full_signal = "module_%s" % signal_name
		if not has_signal(full_signal):
			result.valid = false
			result.missing.append(signal_name)
			result.errors.append("Module '%s' missing signal: %s" % [module_name, signal_name])
	
	return result

func emit_module_signal(signal_name: String, args: Array = []) -> void:
	"""
	Emit a module signal with optional arguments.
	Signal name should include 'module_' prefix.
	"""
	if not signal_name.begins_with("module_"):
		push_error("SignalBus: Module signals must start with 'module_' prefix")
		return
	
	if not has_signal(signal_name):
		push_warning("SignalBus: Attempting to emit unregistered signal: %s" % signal_name)
		return
	
	match signal_name:
		"module_enemy_defeated":
			module_enemy_defeated.emit(args[0] if args.size() > 0 else "", args[1] if args.size() > 1 else 0)
		"module_item_collected":
			module_item_collected.emit(args[0] if args.size() > 0 else "", args[1] if args.size() > 1 else 1)
		"module_quest_started":
			module_quest_started.emit(args[0] if args.size() > 0 else "")
		"module_quest_completed":
			module_quest_completed.emit(args[0] if args.size() > 0 else "", args[1] if args.size() > 1 else [])
		"module_quest_stage_changed":
			module_quest_stage_changed.emit(args[0] if args.size() > 0 else "", args[1] if args.size() > 1 else "")
		"module_dialogue_started":
			module_dialogue_started.emit(args[0] if args.size() > 0 else "", args[1] if args.size() > 1 else "")
		"module_dialogue_ended":
			module_dialogue_ended.emit(args[0] if args.size() > 0 else "")
		"module_level_loaded":
			module_level_loaded.emit(args[0] if args.size() > 0 else "")
		"module_checkpoint_reached":
			module_checkpoint_reached.emit(args[0] if args.size() > 0 else "")
		_:
			push_warning("SignalBus: Unknown module signal: %s" % signal_name)

# ============================================================================
# CONNECTION HELPERS
# ============================================================================

func connect_to_signal(signal_name: String, callable: Callable, flags: int = 0) -> Error:
	"""
	Connect a callable to a signal.
	Returns OK on success, error code on failure.
	"""
	if has_signal(signal_name):
		return connect(signal_name, callable, flags)
	else:
		push_error("SignalBus: Cannot connect to non-existent signal: %s" % signal_name)
		return ERR_DOES_NOT_EXIST

func disconnect_from_signal(signal_name: String, callable: Callable) -> Error:
	"""
	Disconnect a callable from a signal.
	Returns OK on success, error code on failure.
	"""
	if has_signal(signal_name) and is_connected(signal_name, callable):
		return disconnect(signal_name, callable)
	else:
		return ERR_DOES_NOT_EXIST

# ============================================================================
# INITIALIZATION
# ============================================================================

func _ready() -> void:
	# Register default module channels
	var default_channels = [
		"enemy_defeated",
		"item_collected",
		"quest_started",
		"quest_completed",
		"quest_stage_changed",
		"dialogue_started",
		"dialogue_ended",
		"level_loaded",
		"checkpoint_reached"
	]
	
	for channel in default_channels:
		register_channel(channel)
	
	print("[SignalBus] Initialized with %d default channels" % default_channels.size())
