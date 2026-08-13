extends Node
"""
UI Framework for managing UI scenes, navigation, and common UI components.
Provides consistent UI behavior across all generated games.
"""

# ============================================================================
# SIGNALS
# ============================================================================

signal ui_screen_changed(old_screen: String, new_screen: String)
signal ui_back_pressed()
signal ui_confirm_pressed()
signal ui_option_selected(option_id: String)

# ============================================================================
# UI SCREEN ENUMS
# ============================================================================

enum UIScreen {
	NONE,
	MAIN_MENU,
	PAUSE_MENU,
	SETTINGS,
	INVENTORY,
	QUEST_LOG,
	DIALOGUE,
	CRAFTING,
	MAP,
	GAME_OVER,
	VICTORY,
	CREDITS,
	LOAD_GAME,
	SAVE_GAME
}

# ============================================================================
# PROPERTIES
# ============================================================================

var current_screen: UIScreen = UIScreen.NONE
var previous_screen: UIScreen = UIScreen.NONE
var screen_stack: Array[UIScreen] = []

# UI Configuration
var enable_animations: bool = true
var default_transition_time: float = 0.3
var max_screen_history: int = 10

# References (to be set by generated games)
var canvas_layer: CanvasLayer = null
var screens: Dictionary = {} # screen_name -> Node reference

# ============================================================================
# PUBLIC API
# ============================================================================

func show_screen(screen: UIScreen, data: Dictionary = {}) -> void:
	"""Show a UI screen."""
	if current_screen == screen:
		return
	
	previous_screen = current_screen
	
	# Hide current screen
	hide_current_screen()
	
	# Update state
	current_screen = screen
	screen_stack.append(current_screen)
	if screen_stack.size() > max_screen_history:
		screen_stack.pop_front()
	
	# Show new screen
	_show_screen_internal(screen, data)
	
	ui_screen_changed.emit(UIScreen.keys()[previous_screen], UIScreen.keys()[current_screen])

func hide_current_screen() -> void:
	"""Hide the currently visible screen."""
	if current_screen == UIScreen.NONE:
		return
	
	var screen_node = _get_screen_node(current_screen)
	if screen_node:
		if enable_animations:
			_animate_out(screen_node)
			await get_tree().create_timer(default_transition_time).timeout
		screen_node.visible = false
	
	current_screen = UIScreen.NONE

func hide_screen(screen: UIScreen) -> void:
	"""Hide a specific screen."""
	var screen_node = _get_screen_node(screen)
	if screen_node:
		screen_node.visible = false
	
	if current_screen == screen:
		current_screen = previous_screen

func show_all_screens() -> void:
	"""Show all registered screens (debug)."""
	for screen_node in screens.values():
		if screen_node:
			screen_node.visible = true

func hide_all_screens() -> void:
	"""Hide all screens."""
	for screen_node in screens.values():
		if screen_node:
			screen_node.visible = false
	current_screen = UIScreen.NONE

func register_screen(screen: UIScreen, node: Node) -> void:
	"""Register a screen node."""
	screens[screen] = node
	if node is Control:
		node.visible = false

func unregister_screen(screen: UIScreen) -> void:
	"""Unregister a screen node."""
	screens.erase(screen)

func get_current_screen() -> UIScreen:
	"""Get the currently active screen."""
	return current_screen

func get_screen_name(screen: UIScreen = -1) -> String:
	"""Get human-readable name for a screen."""
	if screen == -1:
		screen = current_screen
	return UIScreen.keys()[screen]

func is_screen_visible(screen: UIScreen) -> bool:
	"""Check if a screen is currently visible."""
	return current_screen == screen

func go_back() -> void:
	"""Navigate back to previous screen."""
	if screen_stack.size() < 2:
		ui_back_pressed.emit()
		return
	
	screen_stack.pop_back() # Remove current
	var prev = screen_stack.back()
	show_screen(prev)

func clear_screen_stack() -> void:
	"""Clear the screen navigation stack."""
	screen_stack.clear()
	screen_stack.append(UIScreen.NONE)

# ============================================================================
# CONVENIENCE METHODS
# ============================================================================

func show_main_menu() -> void:
	"""Show main menu screen."""
	show_screen(UIScreen.MAIN_MENU)

func show_pause_menu() -> void:
	"""Show pause menu screen."""
	show_screen(UIScreen.PAUSE_MENU)

func show_inventory() -> void:
	"""Show inventory screen."""
	show_screen(UIScreen.INVENTORY)

func toggle_inventory() -> void:
	"""Toggle inventory visibility."""
	if is_screen_visible(UIScreen.INVENTORY):
		hide_current_screen()
	else:
		show_inventory()

func show_quest_log() -> void:
	"""Show quest log screen."""
	show_screen(UIScreen.QUEST_LOG)

func show_settings() -> void:
	"""Show settings screen."""
	show_screen(UIScreen.SETTINGS)

func show_game_over(reason: String = "") -> void:
	"""Show game over screen."""
	var screen_node = _get_screen_node(UIScreen.GAME_OVER)
	if screen_node:
		var reason_label = screen_node.get_node_or_null("ReasonLabel")
		if reason_label:
			reason_label.text = reason
	show_screen(UIScreen.GAME_OVER)

func show_victory() -> void:
	"""Show victory screen."""
	show_screen(UIScreen.VICTORY)

func show_dialogue_box() -> void:
	"""Show dialogue box screen."""
	show_screen(UIScreen.DIALOGUE)

func hide_dialogue_box() -> void:
	"""Hide dialogue box screen."""
	hide_current_screen()

func show_save_screen() -> void:
	"""Show save game screen."""
	show_screen(UIScreen.SAVE_GAME)

func show_load_screen() -> void:
	"""Show load game screen."""
	show_screen(UIScreen.LOAD_GAME)

# ============================================================================
# UI COMPONENT HELPERS
# ============================================================================

func create_button(text: String, callback: Callable = null) -> Button:
	"""Create a styled button."""
	var button = Button.new()
	button.text = text
	button.custom_minimum_size = Vector2(200, 50)
	
	if callback:
		button.pressed.connect(callback)
	
	return button

func create_label(text: String, size: int = 16, bold: bool = false) -> Label:
	"""Create a styled label."""
	var label = Label.new()
	label.text = text
	
	var font_size = size
	# Apply styling via theme or custom fonts in generated games
	
	return label

func create_panel() -> PanelContainer:
	"""Create a styled panel container."""
	var panel = PanelContainer.new()
	panel.custom_minimum_size = Vector2(400, 300)
	return panel

func create_grid_container(columns: int = 2) -> GridContainer:
	"""Create a grid container."""
	var grid = GridContainer.new()
	grid.columns = columns
	return grid

func create_vbox() -> VBoxContainer:
	"""Create a vertical box container."""
	return VBoxContainer.new()

func create_hbox() -> HBoxContainer:
	"""Create a horizontal box container."""
	return HBoxContainer.new()

func center_control(control: Control) -> void:
	"""Center a control in the viewport."""
	if not control or not is_instance_valid(control):
		return
	
	control.set_anchors_preset(Control.PRESET_CENTER)
	control.offset_left = -control.size.x / 2
	control.offset_top = -control.size.y / 2
	control.offset_right = control.size.x / 2
	control.offset_bottom = control.size.y / 2

# ============================================================================
# ANIMATIONS
# ============================================================================

func _animate_in(node: Node) -> void:
	"""Animate a screen appearing."""
	if node is Control:
		var control = node as Control
		control.modulate.a = 0.0
		
		var tween = create_tween()
		tween.tween_property(control, "modulate:a", 1.0, default_transition_time)
		tween.tween_property(control, "position", control.position, default_transition_time * 0.8)

func _animate_out(node: Node) -> void:
	"""Animate a screen disappearing."""
	if node is Control:
		var control = node as Control
		
		var tween = create_tween()
		tween.tween_property(control, "modulate:a", 0.0, default_transition_time)

# ============================================================================
# INTERNAL METHODS
# ============================================================================

func _show_screen_internal(screen: UIScreen, data: Dictionary = {}) -> void:
	"""Internal method to show a screen."""
	var screen_node = _get_screen_node(screen)
	if not screen_node:
		push_warning("UIManager: Screen not found: %s" % UIScreen.keys()[screen])
		return
	
	screen_node.visible = true
	
	if enable_animations:
		_animate_in(screen_node)
	
	# Pass data to screen if it has a setup method
	if screen_node.has_method("setup"):
		screen_node.setup(data)

func _get_screen_node(screen: UIScreen) -> Node:
	"""Get the node for a screen."""
	if screens.has(screen):
		return screens[screen]
	return null

func _find_screen_node_by_name(name: String) -> Node:
	"""Find a screen node by its scene name."""
	for screen_enum in screens.keys():
		var node = screens[screen_enum]
		if node and node.name == name:
			return node
	return null

# ============================================================================
# INPUT HANDLING
# ============================================================================

func _input(event: InputEvent) -> void:
	"""Handle global UI input."""
	if event.is_action_pressed("pause"):
		if current_screen == UIScreen.PAUSE_MENU:
			hide_current_screen()
			get_tree().paused = false
		elif current_screen == UIScreen.NONE:
			show_pause_menu()
			get_tree().paused = true
		ui_back_pressed.emit()
	
	elif event.is_action_pressed("ui_accept") or event.is_action_pressed("interact"):
		ui_confirm_pressed.emit()
	
	elif event.is_action_pressed("ui_cancel") or event.is_action_pressed("inventory"):
		if current_screen != UIScreen.NONE:
			go_back()

# ============================================================================
# INITIALIZATION
# ============================================================================

func _ready() -> void:
	# Create canvas layer if not provided
	if not canvas_layer:
		canvas_layer = CanvasLayer.new()
		canvas_layer.name = "UICanvas"
		canvas_layer.layer = 10
		add_child(canvas_layer)
	
	print("[UIManager] Initialized")
