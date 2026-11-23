extends CharacterBody2D
"""
Player controller (immutable core, Phase 12).

The GodotIntegrator attaches this script to the Player CharacterBody2D inside
every assembled ``main_level.tscn`` — the player is no longer a bare Sprite2D,
so the skeleton is movable and collides with the world out of the box.

Movement uses the canonical input actions defined by the template
``project.godot``: move_left / move_right / move_up / move_down and jump.
Behavior adapts to the camera mode recorded in the IR:

- "top_down": free 8-directional movement, no gravity (default).
- "platformer" / "first_person": side-scrolling physics with gravity + jump.

All runtime tuning values are injected by the integrator from the GameIR
(player EntityRequest.components.movement, CameraConfig.mode) via the
``apply_ir_config(data: Dictionary)`` method; sensible defaults keep the
controller playable even without it.
"""

## Movement speed in pixels/second (overridden from IR movement.speed * TILE_SIZE).
@export var move_speed: float = 200.0
## Downward acceleration for platformer mode (px/s^2).
@export var gravity: float = 1400.0
## Initial upward velocity on jump (px/s).
@export var jump_velocity: float = -450.0
## True when the level is a side-view platformer (gravity + jump enabled).
@export var platformer_mode: bool = false

var _input_enabled: bool = true


func _ready() -> void:
	add_to_group("player")


func set_input_enabled(enabled: bool) -> void:
	"""Enable/disable player input (dialogues, menus, cutscenes)."""
	_input_enabled = enabled
	if not enabled:
		velocity = Vector2.ZERO


func _physics_process(_delta: float) -> void:
	var input_vector := Vector2.ZERO
	if _input_enabled:
		input_vector = Input.get_vector("move_left", "move_right", "move_up", "move_down")

	if platformer_mode:
		velocity.x = input_vector.x * move_speed
		if not is_on_floor():
			velocity += get_gravity()
		if input_vector.y < -0.5 and is_on_floor():
			velocity.y = jump_velocity
	else:
		velocity = input_vector * move_speed

	move_and_slide()


func apply_ir_config(data: Dictionary) -> void:
	"""Inject gameplay parameters assembled from the GameIR by the integrator.

	Recognized keys (all optional): ``move_speed`` (px/s), ``platformer``
	(bool), ``gravity``, ``jump_velocity``.
	"""
	if data.has("move_speed"):
		move_speed = float(data["move_speed"])
	if data.has("platformer"):
		platformer_mode = bool(data["platformer"])
	if data.has("gravity"):
		gravity = float(data["gravity"])
	if data.has("jump_velocity"):
		jump_velocity = float(data["jump_velocity"])
