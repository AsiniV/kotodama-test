"""
Bot-Player Simulation Script for Godot 4.3+

This script implements the enhanced AI Playtester bot-player as specified in Section 7.2.
It simulates basic player actions to test game passability and functionality.

Actions:
- move (40%): Move to random position on navmesh
- interact (20%): Interact with nearest interactable object
- collect (15%): Collect nearest item
- attack (15%): Attack nearest enemy
- talk (10%): Start dialogue with nearest NPC

The bot logs all actions and metrics for the playtester to parse.
"""

extends Node
class_name BotPlayer

# Configuration
@export var max_frames: int = 900
@export var action_weights: Dictionary = {
	"move": 0.4,
	"interact": 0.2,
	"collect": 0.15,
	"attack": 0.15,
	"talk": 0.1
}

# Metrics tracking
var items_collected: int = 0
var npcs_interacted: int = 0
var quests_started: int = 0
var quests_completed: int = 0
var dialogues_opened: int = 0
var player_deaths: int = 0
var stuck_frames: int = 0
var consecutive_stuck_frames: int = 0
var last_position: Vector2 = Vector2.ZERO

# References
var player: Node2D = null
var frame_count: int = 0
var bot_enabled: bool = false

# Action names for weighted selection
var actions: Array[String] = ["move", "interact", "collect", "attack", "talk"]


func _ready() -> void:
	# Check if bot-player is enabled via command line
	var args = OS.get_cmdline_args()
	for arg in args:
		if "bot_player_enabled=true" in arg:
			bot_enabled = true
			break
	
	if not bot_enabled:
		queue_free()
		return
	
	# Find player node (common naming conventions)
	player = _find_player_node()
	
	if player == null:
		print("BotPlayer: WARNING - Player node not found")
		queue_free()
		return
	
	last_position = player.global_position if player else Vector2.ZERO
	
	# Connect to player death signal if available
	if player.has_signal("died"):
		player.died.connect(_on_player_died)
	
	print("BotPlayer: Initialized and ready")


func _process(_delta: float) -> void:
	if not bot_enabled or player == null:
		return
	
	frame_count += 1
	
	if frame_count >= max_frames:
		_report_metrics()
		get_tree().quit()
		return
	
	# Perform weighted random action
	var action = _weighted_random_action()
	_execute_action(action)
	
	# Check if stuck
	_check_stuck_status()


func _find_player_node() -> Node2D:
	"""Find player node using common naming conventions."""
	var possible_names = ["Player", "player", "Character", "character", "Hero", "hero"]
	
	for name in possible_names:
		var node = get_node_or_null("/root/Game/" + name)
		if node:
			return node as Node2D
	
	# Try to find by group
	var players = get_tree().get_nodes_in_group("player")
	if players.size() > 0:
		return players[0] as Node2D
	
	# Try to find by class
	for node in get_tree().get_current_scene().get_children():
		if node is Node2D and "player" in node.name.to_lower():
			return node
	
	return null


func _weighted_random_action() -> String:
	"""Select action based on weights."""
	var total_weight: float = 0.0
	for weight in action_weights.values():
		total_weight += weight
	
	var rand: float = randf() * total_weight
	var cumulative: float = 0.0
	
	for i in range(actions.size()):
		cumulative += action_weights[actions[i]]
		if rand < cumulative:
			return actions[i]
	
	return "move"  # Fallback


func _execute_action(action: String) -> void:
	"""Execute the selected action."""
	match action:
		"move":
			_action_move()
		"interact":
			_action_interact()
		"collect":
			_action_collect()
		"attack":
			_action_attack()
		"talk":
			_action_talk()


func _action_move() -> void:
	"""Move to a random position on the navmesh/within bounds."""
	if player == null:
		return
	
	# Get viewport size for bounds
	var viewport_size = get_viewport().get_visible_rect().size
	var target_x = randf_range(100, viewport_size.x - 100)
	var target_y = randf_range(100, viewport_size.y - 100)
	var target = Vector2(target_x, target_y)
	
	# Try to use navigation if available
	var nav_region = _find_navigation_region()
	if nav_region:
		var path = nav_region.get_simple_path(player.global_position, target)
		if path.size() > 0:
			target = path[-1]
	
	# Move player (assumes standard movement methods)
	if player.has_method("move_to"):
		player.move_to(target)
	elif player.has_method("_move_toward"):
		player._move_toward(target)
	else:
		# Direct position update as fallback
		player.global_position = target


func _find_navigation_region() -> NavigationRegion2D:
	"""Find navigation region for pathfinding."""
	var nav_regions = get_tree().get_nodes_in_group("nav_region")
	if nav_regions.size() > 0:
		return nav_regions[0] as NavigationRegion2D
	
	# Search manually
	for node in get_tree().get_current_scene().get_children():
		if node is NavigationRegion2D:
			return node
	
	return null


func _action_interact() -> void:
	"""Interact with nearest interactable object."""
	var interactables = _find_nodes_by_group_or_name("interactable", "Interactable")
	var nearest = _find_nearest_node(interactables)
	
	if nearest:
		if nearest.has_method("interact"):
			nearest.interact()
			print("BotPlayer:interacted:" + nearest.name)
		elif nearest.has_signal("interacted"):
			nearest.emit_signal("interacted")
			print("BotPlayer:interacted:" + nearest.name)


func _action_collect() -> void:
	"""Collect nearest item."""
	var items = _find_nodes_by_group_or_name("item", "Item")
	items.append_array(_find_nodes_by_group_or_name("pickup", "Pickup"))
	var nearest = _find_nearest_node(items)
	
	if nearest:
		if nearest.has_method("collect"):
			nearest.collect()
		elif nearest.has_method("pick_up"):
			nearest.pick_up()
		else:
			# Emit signal or queue_free
			if nearest.has_signal("collected"):
				nearest.emit_signal("collected")
			nearest.queue_free()
		
		items_collected += 1
		print("BotPlayer:items_collected:" + str(items_collected))


func _action_attack() -> void:
	"""Attack nearest enemy."""
	var enemies = _find_nodes_by_group_or_name("enemy", "Enemy")
	enemies.append_array(_find_nodes_by_group_or_name("hostile", "Hostile"))
	var nearest = _find_nearest_node(enemies)
	
	if nearest:
		if player.has_method("attack"):
			player.attack(nearest)
		elif player.has_method("_attack"):
			player._attack(nearest)
		print("BotPlayer:attacked:" + nearest.name)


func _action_talk() -> void:
	"""Start dialogue with nearest NPC."""
	var npcs = _find_nodes_by_group_or_name("npc", "NPC")
	npcs.append_array(_find_nodes_by_group_or_name("character", "Character"))
	var nearest = _find_nearest_node(npcs)
	
	if nearest:
		if nearest.has_method("start_dialogue"):
			nearest.start_dialogue(player)
			dialogues_opened += 1
			print("BotPlayer:dialogues_opened:" + str(dialogues_opened))
		elif nearest.has_method("talk"):
			nearest.talk(player)
			dialogues_opened += 1
			print("BotPlayer:dialogues_opened:" + str(dialogues_opened))
		elif nearest.has_signal("dialogue_started"):
			nearest.emit_signal("dialogue_started", player)
			dialogues_opened += 1
			print("BotPlayer:dialogues_opened:" + str(dialogues_opened))
		
		npcs_interacted += 1


func _find_nodes_by_group_or_name(group: String, name_pattern: String) -> Array:
	"""Find nodes by group membership or name pattern."""
	var results: Array = []
	
	# By group
	var grouped = get_tree().get_nodes_in_group(group)
	results.append_array(grouped)
	
	# By name pattern (search top-level children)
	for node in get_tree().get_current_scene().get_children():
		if name_pattern.to_lower() in node.name.to_lower():
			results.append(node)
	
	return results


func _find_nearest_node(nodes: Array) -> Node:
	"""Find the nearest node to the player."""
	if nodes.is_empty() or player == null:
		return null
	
	var nearest: Node = null
	var min_distance: float = INF
	
	for node in nodes:
		if node is Node2D:
			var dist = player.global_position.distance_to(node.global_position)
			if dist < min_distance:
				min_distance = dist
				nearest = node
	
	return nearest


func _check_stuck_status() -> void:
	"""Check if the bot is stuck (not moving)."""
	if player == null:
		return
	
	var current_pos = player.global_position
	var distance_moved = current_pos.distance_to(last_position)
	
	if distance_moved < 1.0:  # Less than 1 pixel movement
		consecutive_stuck_frames += 1
	else:
		consecutive_stuck_frames = 0
	
	if consecutive_stuck_frames > 60:  # Stuck for more than 1 second at 60 FPS
		stuck_frames = consecutive_stuck_frames
		if consecutive_stuck_frames % 120 == 0:  # Report every 2 seconds
			print("BotPlayer:stuck_frames:" + str(stuck_frames))
	
	last_position = current_pos


func _on_player_died() -> void:
	"""Handle player death event."""
	player_deaths += 1
	print("BotPlayer:player_deaths:" + str(player_deaths))
	
	# Respawn or continue based on game mechanics
	if player.has_method("respawn"):
		player.respawn()


func _report_metrics() -> void:
	"""Report final metrics before quitting."""
	print("\n=== BotPlayer Final Report ===")
	print("Frames processed: " + str(frame_count))
	print("BotPlayer:items_collected:" + str(items_collected))
	print("BotPlayer:npcs_interacted:" + str(npcs_interacted))
	print("BotPlayer:quests_started:" + str(quests_started))
	print("BotPlayer:quests_completed:" + str(quests_completed))
	print("BotPlayer:dialogues_opened:" + str(dialogues_opened))
	print("BotPlayer:player_deaths:" + str(player_deaths))
	print("BotPlayer:stuck_frames:" + str(stuck_frames))
	
	# Detect game features
	var has_items = not _find_nodes_by_group_or_name("item", "Item").is_empty()
	var has_dialogues = not _find_nodes_by_group_or_name("npc", "NPC").is_empty()
	var has_quests = _has_quest_system()
	
	if has_items:
		print("GameHasItems:true")
	if has_dialogues:
		print("GameHasDialogues:true")
	if has_quests:
		print("GameHasQuests:true")
	
	print("=== End BotPlayer Report ===")


func _has_quest_system() -> bool:
	"""Check if game has quest system."""
	# Look for quest manager or quest-related nodes
	var quest_nodes = _find_nodes_by_group_or_name("quest", "Quest")
	quest_nodes.append_array(_find_nodes_by_group_or_name("mission", "Mission"))
	return not quest_nodes.is_empty()


func _on_quest_started(_quest_id: String) -> void:
	"""Callback when a quest is started."""
	quests_started += 1
	print("BotPlayer:quests_started:" + str(quests_started))


func _on_quest_completed(_quest_id: String) -> void:
	"""Callback when a quest is completed."""
	quests_completed += 1
	print("BotPlayer:quests_completed:" + str(quests_completed))
