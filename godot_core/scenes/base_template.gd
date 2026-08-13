extends Node2D
"""
Base template scene for all generated games.
This is the main scene that gets instantiated for every new game.
Modules are added as children of this node.
"""

@onready var signal_bus = $SignalBus
@onready var state_machine = $StateMachine
@onready var scene_manager = $SceneManager
@onready var input_manager = $InputManager
@onready var ui_manager = $UIManager

# Module containers (modules are added as children)
@onready var modules_container = $Modules
@onready var world_container = $World
@onready var ui_container = $UI

# Game configuration (set by generation system)
var game_config: Dictionary = {}
var player_scene: PackedScene = null
var start_position: Vector2 = Vector2.ZERO
var end_position: Vector2 = Vector2.ZERO

# State tracking
var game_started: bool = false
var play_time: float = 0.0

func _ready() -> void:
	print("[BaseTemplate] Game initialized")
	
	# Connect core signals
	_connect_core_signals()
	
	# Initialize game state
	state_machine.change_state(StateMachine.GameState.MENU)
	
	# Show main menu
	ui_manager.show_main_menu()
	
	print("[BaseTemplate] Ready - showing main menu")

func _process(delta: float) -> void:
	if game_started:
		play_time += delta

func _connect_core_signals() -> void:
	# Game lifecycle
	signal_bus.game_started.connect(_on_game_started)
	signal_bus.game_paused.connect(_on_game_paused)
	signal_bus.game_resumed.connect(_on_game_resumed)
	signal_bus.game_ended.connect(_on_game_ended)
	
	# UI events
	signal_bus.ui_show_main_menu.connect(_on_ui_show_main_menu)
	signal_bus.ui_show_pause_menu.connect(_on_ui_show_pause_menu)
	signal_bus.ui_show_game_over.connect(_on_ui_show_game_over)
	signal_bus.ui_show_victory.connect(_on_ui_show_victory)
	
	# Save/Load
	signal_bus.save_requested.connect(_on_save_requested)
	signal_bus.load_requested.connect(_on_load_requested)

func start_game() -> void:
	"""Start the game, spawning player and entering PLAYING state."""
	if game_started:
		return
	
	game_started = true
	
	# Spawn player if scene is set
	if player_scene:
		var player = player_scene.instantiate()
		player.name = "Player"
		world_container.add_child(player)
		player.global_position = start_position
		
		# Emit signal for modules to connect
		signal_bus.player_spawned.emit(player)
	
	# Change to playing state
	state_machine.start_game()
	
	# Hide menu
	ui_manager.hide_all_screens()
	
	print("[BaseTemplate] Game started")

func pause_game() -> void:
	"""Pause the game."""
	state_machine.pause_game()
	ui_manager.show_pause_menu()

func resume_game() -> void:
	"""Resume the game from pause."""
	state_machine.resume_game()
	ui_manager.hide_current_screen()

func quit_to_menu() -> void:
	"""Quit back to main menu."""
	game_started = false
	state_machine.enter_menu()
	ui_manager.show_main_menu()
	
	# Clean up world
	_cleanup_world()

func _cleanup_world() -> void:
	"""Remove all dynamic objects from world."""
	for child in world_container.get_children():
		if child.name != "TileMap" and child.name != "StaticColliders":
			child.queue_free()

# ============================================================================
# SIGNAL HANDLERS
# ============================================================================

func _on_game_started() -> void:
	print("[BaseTemplate] Game started signal received")

func _on_game_paused() -> void:
	print("[BaseTemplate] Game paused")

func _on_game_resumed() -> void:
	print("[BaseTemplate] Game resumed")

func _on_game_ended(reason: String) -> void:
	print("[BaseTemplate] Game ended: %s" % reason)
	game_started = false

func _on_ui_show_main_menu() -> void:
	ui_manager.show_main_menu()

func _on_ui_show_pause_menu() -> void:
	ui_manager.show_pause_menu()

func _on_ui_show_game_over() -> void:
	ui_manager.show_game_over()

func _on_ui_show_victory() -> void:
	ui_manager.show_victory()

func _on_save_requested(slot: int) -> void:
	"""Handle save request."""
	if has_node("SaveSystem"):
		var save_system = get_node("SaveSystem")
		if save_system.has_method("save_game"):
			save_system.save_game(slot)

func _on_load_requested(slot: int) -> void:
	"""Handle load request."""
	if has_node("SaveSystem"):
		var save_system = get_node("SaveSystem")
		if save_system.has_method("load_game"):
			save_system.load_game(slot)

# ============================================================================
# MODULE MANAGEMENT
# ============================================================================

func add_module(module_name: String, module_node: Node) -> void:
	"""Add a module to the game."""
	module_node.name = module_name
	modules_container.add_child(module_node)
	print("[BaseTemplate] Added module: %s" % module_name)

func remove_module(module_name: String) -> void:
	"""Remove a module from the game."""
	if modules_container.has_node(module_name):
		var module = modules_container.get_node(module_name)
		module.queue_free()
		print("[BaseTemplate] Removed module: %s" % module_name)

func get_module(module_name: String) -> Node:
	"""Get a module by name."""
	return modules_container.get_node_or_null(module_name)

func has_module(module_name: String) -> bool:
	"""Check if a module exists."""
	return modules_container.has_node(module_name)

# ============================================================================
# UTILITY METHODS
# ============================================================================

func get_play_time() -> float:
	"""Get total play time in seconds."""
	return play_time

func get_play_time_formatted() -> String:
	"""Get formatted play time (HH:MM:SS)."""
	var hours = int(play_time / 3600)
	var minutes = int((play_time % 3600) / 60)
	var seconds = int(play_time % 60)
	return "%02d:%02d:%02d" % [hours, minutes, seconds]

func register_signal_channel(channel_name: String) -> bool:
	"""Register a new signal channel for modules."""
	return signal_bus.register_channel(channel_name)

func emit_module_signal(signal_name: String, args: Array = []) -> void:
	"""Emit a module signal."""
	signal_bus.emit_module_signal(signal_name, args)
