extends Node
"""
Scene Manager for handling scene loading, transitions, and lifecycle.
Supports async loading, progress tracking, and smooth transitions.
"""

# ============================================================================
# SIGNALS
# ============================================================================

signal scene_load_started(scene_path: String)
signal scene_load_progress(progress: float)
signal scene_load_completed(scene_path: String)
signal scene_load_failed(error: String)
signal scene_transition_started()
signal scene_transition_completed()

# ============================================================================
# PROPERTIES
# ============================================================================

var current_scene_path: String = ""
var previous_scene_path: String = ""
var is_loading: bool = false
var load_progress: float = 0.0

# Configuration
var default_transition_time: float = 0.5
var enable_transitions: bool = true
var max_load_time_seconds: float = 30.0

# Internal
var _loading_thread: Thread = null
var _pending_scene: PackedScene = null
var _transition_canvas: CanvasLayer = null
var _color_rect: ColorRect = null

# ============================================================================
# PUBLIC API
# ============================================================================

func load_scene(scene_path: String, change_tree: bool = true) -> Error:
	"""
	Load a scene asynchronously.
	Returns OK on success, error code on failure.
	"""
	if is_loading:
		push_warning("SceneManager: Already loading a scene")
		return ERR_BUSY
	
	if not ResourceLoader.exists(scene_path):
		var error_msg = "Scene not found: %s" % scene_path
		push_error("SceneManager: " + error_msg)
		scene_load_failed.emit(error_msg)
		return ERR_FILE_NOT_FOUND
	
	scene_load_started.emit(scene_path)
	is_loading = true
	load_progress = 0.0
	
	previous_scene_path = current_scene_path
	current_scene_path = scene_path
	
	# Start async loading
	_loading_thread = Thread.new()
	_loading_thread.start(_load_scene_thread.bind(scene_path, change_tree))
	
	return OK

func load_scene_sync(scene_path: String, change_tree: bool = true) -> Error:
	"""
	Load a scene synchronously (blocking).
	Use only for simple scenes or when async is not needed.
	"""
	if not ResourceLoader.exists(scene_path):
		var error_msg = "Scene not found: %s" % scene_path
		push_error("SceneManager: " + error_msg)
		scene_load_failed.emit(error_msg)
		return ERR_FILE_NOT_FOUND
	
	scene_load_started.emit(scene_path)
	is_loading = true
	
	previous_scene_path = current_scene_path
	current_scene_path = scene_path
	
	var packed_scene = ResourceLoader.load(scene_path)
	if packed_scene == null:
		var error_msg = "Failed to load scene: %s" % scene_path
		push_error("SceneManager: " + error_msg)
		scene_load_failed.emit(error_msg)
		is_loading = false
		return ERR_CANT_CREATE_INSTANCE
	
	is_loading = false
	load_progress = 1.0
	scene_load_completed.emit(scene_path)
	
	if change_tree:
		get_tree().change_scene_to_packed(packed_scene)
	
	return OK

func unload_current_scene() -> void:
	"""Unload the current scene and return to empty state."""
	if current_scene_path.is_empty():
		return
	
	get_tree().change_scene_to_file(null)
	current_scene_path = ""

func reload_current_scene() -> Error:
	"""Reload the current scene."""
	if current_scene_path.is_empty():
		return ERR_DOES_NOT_EXIST
	return load_scene(current_scene_path)

func get_current_scene() -> Node:
	"""Get the root node of the current scene."""
	return get_tree().current_scene

func get_current_scene_path() -> String:
	"""Get the path of the currently loaded scene."""
	return current_scene_path

func get_previous_scene_path() -> String:
	"""Get the path of the previously loaded scene."""
	return previous_scene_path

func cancel_loading() -> void:
	"""Cancel ongoing scene loading."""
	if _loading_thread and _loading_thread.is_alive():
		_loading_thread.wait_to_finish()
		_loading_thread = null
		is_loading = false
		push_warning("SceneManager: Loading cancelled")

func set_transition_enabled(enabled: bool) -> void:
	"""Enable or disable scene transitions."""
	enable_transitions = enabled

func set_transition_time(time: float) -> void:
	"""Set the duration of scene transitions in seconds."""
	default_transition_time = max(0.0, time)

# ============================================================================
# TRANSITION EFFECTS
# ============================================================================

func fade_out(duration: float = -1.0) -> void:
	"""Fade screen to black."""
	if duration < 0:
		duration = default_transition_time
	
	_create_transition_canvas()
	
	var tween = create_tween()
	tween.tween_property(_color_rect, "color", Color.BLACK, duration)
	await tween.finished

func fade_in(duration: float = -1.0) -> void:
	"""Fade screen from black to clear."""
	if duration < 0:
		duration = default_transition_time
	
	if _color_rect == null:
		_color_rect = ColorRect.new()
		_color_rect.color = Color.BLACK
		_color_rect.set_anchors_preset(Control.PRESET_FULL_RECT)
	
	var tween = create_tween()
	tween.tween_property(_color_rect, "color", Color.TRANSPARENT, duration)
	await tween.finished
	
	_remove_transition_canvas()

func transition_with_fade(new_scene_path: String, duration: float = -1.0) -> Error:
	"""
	Load a new scene with fade transition.
	Fade out → Load scene → Fade in
	"""
	if not enable_transitions:
		return load_scene(new_scene_path)
	
	scene_transition_started.emit()
	
	await fade_out(duration)
	
	var error = load_scene_sync(new_scene_path)
	if error != OK:
		return error
	
	await fade_in(duration)
	
	scene_transition_completed.emit()
	return OK

# ============================================================================
# INTERNAL METHODS
# ============================================================================

func _load_scene_thread(scene_path: String, change_tree: bool) -> void:
	"""Thread function for async scene loading."""
	var start_time = Time.get_ticks_msec()
	
	# Use ResourceLoader for async loading
	var loader = ResourceLoader.load_threaded_request(scene_path)
	
	while true:
		var status = ResourceLoader.load_threaded_get_status(scene_path)
		
		match status:
			ResourceLoader.THREAD_LOAD_IN_PROGRESS:
				var progress_arr = []
				ResourceLoader.load_threaded_get_progress(scene_path, progress_arr)
				load_progress = progress_arr[0] if progress_arr.size() > 0 else 0.0
				scene_load_progress.emit(load_progress)
			
			ResourceLoader.THREAD_LOAD_LOADED:
				var loaded_resource = ResourceLoader.load_threaded_get(scene_path)
				if loaded_resource:
					load_progress = 1.0
					scene_load_progress.emit(load_progress)
					
					# Switch to main thread for tree change
					call_deferred("_on_scene_loaded", loaded_resource, change_tree)
				else:
					call_deferred("_on_scene_load_failed", "Failed to get loaded resource")
				break
			
			ResourceLoader.THREAD_LOAD_FAILED:
				call_deferred("_on_scene_load_failed", "Thread load failed")
				break
			
			ResourceLoader.THREAD_LOAD_INVALID_RESOURCE:
				call_deferred("_on_scene_load_failed", "Invalid resource")
				break
		
		# Timeout check
		if Time.get_ticks_msec() - start_time > max_load_time_seconds * 1000:
			call_deferred("_on_scene_load_failed", "Load timeout")
			break
		
		# Small sleep to prevent busy waiting
		OS.delay_msec(16) # ~60 FPS

func _on_scene_loaded(packed_scene: PackedScene, change_tree: bool) -> void:
	"""Called when scene is successfully loaded."""
	is_loading = false
	load_progress = 1.0
	scene_load_completed.emit(current_scene_path)
	
	if change_tree:
		get_tree().change_scene_to_packed(packed_scene)
	
	if _loading_thread:
		_loading_thread.wait_to_finish()
		_loading_thread = null

func _on_scene_load_failed(error: String) -> void:
	"""Called when scene loading fails."""
	is_loading = false
	push_error("SceneManager: " + error)
	scene_load_failed.emit(error)
	
	if _loading_thread:
		_loading_thread.wait_to_finish()
		_loading_thread = null

func _create_transition_canvas() -> void:
	"""Create canvas layer for transitions."""
	if _transition_canvas:
		return
	
	_transition_canvas = CanvasLayer.new()
	_transition_canvas.name = "TransitionCanvas"
	_transition_canvas.layer = 100
	
	_color_rect = ColorRect.new()
	_color_rect.name = "FadeRect"
	_color_rect.color = Color.TRANSPARENT
	_color_rect.set_anchors_preset(Control.PRESET_FULL_RECT)
	
	_transition_canvas.add_child(_color_rect)
	get_tree().root.add_child(_transition_canvas)

func _remove_transition_canvas() -> void:
	"""Remove transition canvas."""
	if _transition_canvas:
		_transition_canvas.queue_free()
		_transition_canvas = null
		_color_rect = null

# ============================================================================
# INITIALIZATION
# ============================================================================

func _ready() -> void:
	# Track current scene
	var current_scene = get_tree().current_scene
	if current_scene:
		current_scene_path = current_scene.scene_file_path
	
	print("[SceneManager] Initialized")
