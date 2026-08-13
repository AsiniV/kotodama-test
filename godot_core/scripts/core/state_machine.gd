extends Node
"""
Global State Machine for managing game states.
Handles transitions between game states (Menu, Playing, Paused, GameOver, etc.)
"""

# ============================================================================
# STATE ENUMS
# ============================================================================

enum GameState {
	MENU,
	LOADING,
	PLAYING,
	PAUSED,
	GAME_OVER,
	VICTORY,
	CUTSCENE,
	DIALOGUE,
	TRANSITION
}

# ============================================================================
# SIGNALS
# ============================================================================

signal state_changed(old_state: GameState, new_state: GameState)
signal state_entered(state: GameState)
signal state_exited(state: GameState)

# ============================================================================
# PROPERTIES
# ============================================================================

var current_state: GameState = GameState.MENU
var previous_state: GameState = GameState.MENU
var state_history: Array[GameState] = []
var max_history_size: int = 10

# State metadata
var state_data: Dictionary = {}
var transition_callbacks: Dictionary = {}

# ============================================================================
# PUBLIC API
# ============================================================================

func change_state(new_state: GameState, data: Dictionary = {}) -> bool:
	"""
	Change to a new game state.
	Returns true if successful, false if transition is invalid.
	"""
	if not _can_transition_to(new_state):
		push_warning("StateMachine: Invalid transition from %s to %s" % [
			GameState.keys()[current_state],
			GameState.keys()[new_state]
		])
		return false
	
	previous_state = current_state
	
	# Exit current state
	_on_state_exit(current_state)
	state_exited.emit(current_state)
	
	# Update state
	current_state = new_state
	state_history.append(current_state)
	if state_history.size() > max_history_size:
		state_history.pop_front()
	
	# Store state data
	if not data.is_empty():
		state_data[current_state] = data
	
	# Enter new state
	_on_state_enter(current_state)
	state_entered.emit(current_state)
	
	# Notify listeners
	state_changed.emit(previous_state, current_state)
	
	# Execute transition callback if registered
	if transition_callbacks.has(current_state):
		var callback = transition_callbacks[current_state]
		if callback is Callable:
			callback.call(data)
	
	return true

func revert_to_previous_state() -> bool:
	"""Revert to the previous state in history."""
	if state_history.size() < 2:
		return false
	
	state_history.pop_back() # Remove current state
	var prev = state_history.back()
	return change_state(prev)

func get_state_name(state: GameState = -1) -> String:
	"""Get human-readable name for a state."""
	if state == -1:
		state = current_state
	return GameState.keys()[state]

func is_in_state(state: GameState) -> bool:
	"""Check if currently in specified state."""
	return current_state == state

func is_in_any_of(states: Array[GameState]) -> bool:
	"""Check if currently in any of the specified states."""
	return current_state in states

func set_transition_callback(state: GameState, callback: Callable) -> void:
	"""Set a callback to be executed when entering a state."""
	transition_callbacks[state] = callback

func clear_transition_callback(state: GameState) -> void:
	"""Remove transition callback for a state."""
	transition_callbacks.erase(state)

func get_state_data(state: GameState = -1) -> Dictionary:
	"""Get data associated with a state."""
	if state == -1:
		state = current_state
	return state_data.get(state, {})

func clear_state_data(state: GameState = -1) -> void:
	"""Clear data for a state."""
	if state == -1:
		state = current_state
	state_data.erase(state)

# ============================================================================
# STATE VALIDATION
# ============================================================================

func _can_transition_to(new_state: GameState) -> bool:
	"""
	Validate if transition to new state is allowed.
	Override this method for custom transition rules.
	"""
	# Basic validation rules
	match current_state:
		GameState.MENU:
			return new_state in [GameState.LOADING, GameState.PLAYING]
		
		GameState.LOADING:
			return new_state in [GameState.PLAYING, GameState.MENU]
		
		GameState.PLAYING:
			return new_state in [GameState.PAUSED, GameState.GAME_OVER, GameState.VICTORY, GameState.CUTSCENE, GameState.DIALOGUE, GameState.MENU]
		
		GameState.PAUSED:
			return new_state in [GameState.PLAYING, GameState.MENU]
		
		GameState.GAME_OVER:
			return new_state in [GameState.MENU, GameState.LOADING]
		
		GameState.VICTORY:
			return new_state in [GameState.MENU, GameState.LOADING]
		
		GameState.CUTSCENE:
			return new_state in [GameState.PLAYING, GameState.GAME_OVER, GameState.VICTORY]
		
		GameState.DIALOGUE:
			return new_state in [GameState.PLAYING, GameState.GAME_OVER]
		
		GameState.TRANSITION:
			return new_state in [GameState.PLAYING, GameState.LOADING]
	
	return true

# ============================================================================
# STATE HOOKS
# ============================================================================

func _on_state_enter(state: GameState) -> void:
	"""Called when entering a state. Override for custom behavior."""
	match state:
		GameState.MENU:
			Engine.time_scale = 1.0
			get_tree().paused = false
		
		GameState.PLAYING:
			Engine.time_scale = 1.0
			get_tree().paused = false
		
		GameState.PAUSED:
			Engine.time_scale = 0.0
			get_tree().paused = true
		
		GameState.GAME_OVER:
			Engine.time_scale = 1.0
			get_tree().paused = false
		
		GameState.VICTORY:
			Engine.time_scale = 1.0
			get_tree().paused = false
		
		GameState.DIALOGUE:
			# Optionally pause game during dialogue
			pass
		
		GameState.CUTSCENE:
			# Disable player input during cutscene
			pass

func _on_state_exit(state: GameState) -> void:
	"""Called when exiting a state. Override for custom behavior."""
	match state:
		GameState.PAUSED:
			Engine.time_scale = 1.0
			get_tree().paused = false

# ============================================================================
# CONVENIENCE METHODS
# ============================================================================

func start_game() -> bool:
	"""Start the game (transition to PLAYING)."""
	return change_state(GameState.PLAYING)

func pause_game() -> bool:
	"""Pause the game."""
	if current_state == GameState.PLAYING:
		return change_state(GameState.PAUSED)
	return false

func resume_game() -> bool:
	"""Resume the game from pause."""
	if current_state == GameState.PAUSED:
		return change_state(GameState.PLAYING)
	return false

func game_over(reason: String = "") -> bool:
	"""Trigger game over state."""
	if current_state in [GameState.PLAYING, GameState.CUTSCENE, GameState.DIALOGUE]:
		state_data[GameState.GAME_OVER] = {"reason": reason}
		return change_state(GameState.GAME_OVER)
	return false

func victory() -> bool:
	"""Trigger victory state."""
	if current_state in [GameState.PLAYING, GameState.CUTSCENE]:
		return change_state(GameState.VICTORY)
	return false

func enter_menu() -> bool:
	"""Return to main menu."""
	return change_state(GameState.MENU)

func is_game_active() -> bool:
	"""Check if game is actively playing (not paused, not in menu)."""
	return current_state == GameState.PLAYING

func is_game_paused() -> bool:
	"""Check if game is paused."""
	return current_state == GameState.PAUSED

# ============================================================================
# INITIALIZATION
# ============================================================================

func _ready() -> void:
	# Initialize state history
	state_history.append(current_state)
	print("[StateMachine] Initialized in state: %s" % get_state_name())
