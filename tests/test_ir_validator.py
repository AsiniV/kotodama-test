"""GameIR v2 + validator tests (Phase 9) — fully offline.

Covers the contract declared in ``backend/schemas/agent_schemas.py`` and
implemented by ``backend/services/ir_validator.py``:

1. A good GameIR v2 validates with zero errors (and zero warnings).
2. Backward compatibility: v1-shaped IR dicts (no schema_version, no v2
   fields) still validate cleanly; a *future* schema_version is rejected.
3. Corrupted payloads are rejected with precise machine-readable error codes:
   quests.cycle / quests.unreachable / refs.* / spawns.outside_room /
   manifest.bad_path / manifest.missing_file / l10n.missing_key /
   ids.duplicate / schema.invalid / schema.version_unsupported.

No GPU, Godot, LLM server or network required.
"""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest

from backend.schemas.agent_schemas import GAME_IR_SCHEMA_VERSION, EntityComponents, GameIR
from backend.services.ir_validator import ValidationReport, validate_game_ir


# --------------------------------------------------------------------------- #
# Fixture: one rich, internally consistent GameIR v2 payload
# --------------------------------------------------------------------------- #

def _good_ir_dict() -> dict[str, Any]:
    return {
        "schema_version": GAME_IR_SCHEMA_VERSION,
        "genre_template_id": "topdown_action",
        "audio_requests": [
            {"id": "bgm_main", "type": "bgm", "description": "calm synthwave"},
            {"id": "sfx_step", "type": "sfx", "description": "wooden footsteps"},
            {"id": "sfx_hit", "type": "sfx", "description": "sword hit"},
        ],
        "entities": [
            {
                "id": "player",
                "type": "player",
                "sprite": "player",
                "position_x": 5,
                "position_y": 5,
                "sfx_ids": ["sfx_step"],
                "components": {
                    "movement": {"behavior": "walk", "speed": 120.0},
                    "sprite": {"asset_id": "spr_player"},
                },
            },
            {
                "id": "npc_elder",
                "type": "npc",
                "dialogue_id": "dlg_elder",
                "position_x": 6,
                "position_y": 24,
                "components": {
                    "interactable": {
                        "trigger": "interact",
                        "prompt_key": "ui.prompt_talk",
                        "dialogue_id": "dlg_elder",
                    },
                    "quest_giver": {"quest_ids": ["q1", "q2"]},
                    "sprite": {"asset_id": "spr_elder"},
                },
            },
            {
                "id": "goblin",
                "type": "enemy",
                "position_x": 20,
                "position_y": 7,
                "sfx_ids": ["sfx_hit"],
                "components": {
                    "movement": {"behavior": "patrol", "speed": 60.0, "patrol_radius": 3.0},
                    "combat": {"damage": 2, "attack_range": 24.0, "attack_cooldown_s": 0.8},
                },
            },
        ],
        "quests": [
            {
                "quest_id": "q1",
                "title": "q1.title",
                "description": "talk to the elder",
                "stages": [
                    {"id": "s1", "description": "go", "type": "objective", "location": "room_0"}
                ],
                "dependencies": [],
                "npcs_involved": ["npc_elder"],
                "items_required": [],
            },
            {
                "quest_id": "q2",
                "title": "q2.title",
                "description": "clear the goblins",
                "stages": [
                    {"id": "s1", "description": "fight", "type": "objective", "location": "room_1"}
                ],
                "dependencies": ["q1"],
                "npcs_involved": ["npc_elder"],
                "items_required": [],
            },
        ],
        "dialogues": [
            {
                "dialogue_id": "dlg_elder",
                "npc_id": "npc_elder",
                "trigger": "interact",
                "nodes": [
                    {
                        "id": "n0",
                        "speaker": "npc_elder",
                        "text_key": "dlg.elder.greet",
                        "choices": [
                            {"text_key": "dlg.elder.choice_yes", "next": "n1"},
                            {"text_key": "dlg.elder.choice_no", "next": "END"},
                        ],
                    },
                    {
                        "id": "n1",
                        "speaker": "npc_elder",
                        "text_key": "dlg.elder.quest",
                        "choices": [{"text_key": "dlg.elder.choice_ok", "next": "END"}],
                    },
                ],
                "conditions": {},
            }
        ],
        "level_layout": {
            "algorithm": "dungeon_rooms",
            "width": 40,
            "height": 30,
            "rooms": [
                {"x": 0, "y": 0, "width": 10, "height": 10, "room_type": "start"},
                {"x": 15, "y": 0, "width": 10, "height": 10, "room_type": "arena"},
                {"x": 0, "y": 20, "width": 10, "height": 10, "room_type": "hub"},
            ],
            "corridors": [
                {"start": (5, 10), "end": (5, 20), "width": 2},
                {"start": (10, 5), "end": (15, 5), "width": 2},
            ],
            "points_of_interest": [],
            "enemy_spawn_points": [[20, 5]],
            "item_spawn_points": [[3, 3]],
            "start_room": "room_0",
            "end_room": "room_1",
        },
        "camera": {"mode": "top_down", "follow_smoothing": 0.15, "zoom": 1.25},
        "asset_manifest": [
            {"id": "spr_player", "path": "res://assets/sprites/player.png", "kind": "sprite",
             "entity_id": "player"},
            {"id": "spr_elder", "path": "res://assets/sprites/npc_elder.png", "kind": "sprite",
             "entity_id": "npc_elder"},
            {"id": "aud_bgm_main", "path": "res://assets/music/bgm_main.ogg", "kind": "music",
             "audio_request_id": "bgm_main"},
        ],
        "localization_table": {
            "default_locale": "en",
            "entries": {
                "en": {
                    "dlg.elder.greet": "Greetings, traveller.",
                    "dlg.elder.choice_yes": "I need help.",
                    "dlg.elder.choice_no": "Not now.",
                    "dlg.elder.quest": "Clear the goblins to the east.",
                    "dlg.elder.choice_ok": "Consider it done.",
                    "ui.prompt_talk": "Talk",
                    "q1.title": "The Elder's Errand",
                    "q2.title": "Goblin Trouble",
                }
            },
        },
        "audio_map": {
            "zones": [
                {"id": "zone_hub", "rect": [0, 20, 10, 10], "bgm_id": "bgm_main",
                 "sfx_ids": ["sfx_step"]},
            ],
            "ambient": ["bgm_main"],
        },
    }


@pytest.fixture()
def good_ir_dict() -> dict[str, Any]:
    return _good_ir_dict()


def _codes(report: ValidationReport) -> set[str]:
    return report.error_codes


def _find(report: ValidationReport, code: str) -> list:
    return [e for e in report.errors if e.code == code]


# --------------------------------------------------------------------------- #
# 1. Good IR passes
# --------------------------------------------------------------------------- #

def test_good_ir_model_passes(good_ir_dict: dict[str, Any]) -> None:
    model = GameIR.model_validate(good_ir_dict)
    report = validate_game_ir(model)
    assert report.ok, report.render()
    assert report.errors == []
    # The fixture is also free of consistency warnings (orphan quests etc.).
    assert report.warnings == [], "\n".join(str(w) for w in report.warnings)


def test_good_ir_dict_passes(good_ir_dict: dict[str, Any]) -> None:
    report = validate_game_ir(good_ir_dict)
    assert report.ok, report.render()


def test_empty_ir_passes() -> None:
    """An empty (all-defaults) v2 IR has nothing to corrupt."""
    report = validate_game_ir(GameIR())
    assert report.ok, report.render()


# --------------------------------------------------------------------------- #
# 2. Backward compatibility (v1 payloads) + version guard
# --------------------------------------------------------------------------- #

def test_v1_dict_backward_compatible() -> None:
    """A serialized v1 IR (no schema_version, no v2 fields) validates cleanly."""
    v1: dict[str, Any] = {
        "audio_requests": [
            {"id": "sfx_step", "type": "sfx", "description": "steps"},
        ],
        "entities": [
            {"id": "npc_a", "type": "npc", "dialogue_id": "dlg_a", "sfx_ids": ["sfx_step"]},
        ],
        "quests": [
            {
                "quest_id": "q1",
                "title": "Hello",
                "description": "meet the npc",
                "stages": [{"id": "s1", "description": "go", "type": "intro"}],
                "dependencies": [],
                "npcs_involved": ["npc_a"],
                "items_required": [],
            }
        ],
        "dialogues": [
            {
                "dialogue_id": "dlg_a",
                "npc_id": "npc_a",
                "trigger": "proximity",
                "nodes": [
                    {"id": "n0", "speaker": "npc_a", "text_key": "dlg.a.hello",
                     "choices": [{"text_key": "dlg.a.bye", "next": "END"}]}
                ],
                "conditions": {},
            }
        ],
        "level_layout": None,
    }
    report = validate_game_ir(v1)
    assert report.ok, report.render()
    # v2 defaults were materialised on load.
    model = GameIR.model_validate(v1)
    assert model.schema_version == GAME_IR_SCHEMA_VERSION
    assert model.camera.mode == "top_down"
    assert model.asset_manifest == []
    assert model.localization_table.entries == {}
    assert model.audio_map.zones == []
    assert model.entities[0].components == EntityComponents()  # v1 entity: empty bundle, no crash


def test_future_schema_version_rejected(good_ir_dict: dict[str, Any]) -> None:
    bad = dict(good_ir_dict, schema_version=GAME_IR_SCHEMA_VERSION + 1)
    report = validate_game_ir(bad)
    assert not report.ok
    err = _find(report, "schema.version_unsupported")[0]
    assert err.path == "schema_version"
    assert str(GAME_IR_SCHEMA_VERSION + 1) in err.message


# --------------------------------------------------------------------------- #
# 3. Structural / schema errors
# --------------------------------------------------------------------------- #

def test_none_input_is_invalid() -> None:
    report = validate_game_ir(None)
    assert not report.ok
    assert _find(report, "schema.invalid")
    assert report.errors[0].path == "$"


def test_non_model_input_is_invalid() -> None:
    report = validate_game_ir(["not", "an", "ir"])  # type: ignore[arg-type]
    assert not report.ok
    assert "schema.invalid" in _codes(report)


def test_bad_field_payload_reports_precise_paths(good_ir_dict: dict[str, Any]) -> None:
    bad = copy.deepcopy(good_ir_dict)
    bad["entities"][0]["type"] = "spaceship"          # invalid Literal
    bad["audio_requests"][0]["duration_sec"] = 999    # le=120 violation
    report = validate_game_ir(bad)
    assert not report.ok
    errs = _find(report, "schema.invalid")
    assert errs
    paths = {e.path for e in errs}
    assert "entities.0.type" in paths
    assert "audio_requests.0.duration_sec" in paths
    # structural failure short-circuits cross-reference checks
    assert _codes(report) == {"schema.invalid"}


def test_missing_required_field(good_ir_dict: dict[str, Any]) -> None:
    bad = copy.deepcopy(good_ir_dict)
    del bad["entities"][1]["id"]
    report = validate_game_ir(bad)
    assert not report.ok
    assert any(e.path.startswith("entities.1") for e in _find(report, "schema.invalid"))


# --------------------------------------------------------------------------- #
# 4. Duplicate ids
# --------------------------------------------------------------------------- #

def test_duplicate_entity_id(good_ir_dict: dict[str, Any]) -> None:
    bad = copy.deepcopy(good_ir_dict)
    dupe = copy.deepcopy(bad["entities"][1])
    dupe["components"]["quest_giver"] = None
    dupe["components"]["interactable"] = None
    bad["entities"].append(dupe)
    report = validate_game_ir(bad)
    errs = _find(report, "ids.duplicate")
    assert errs
    assert errs[0].path == "entities[3].id"
    assert "npc_elder" in errs[0].message


def test_duplicate_quest_id(good_ir_dict: dict[str, Any]) -> None:
    bad = copy.deepcopy(good_ir_dict)
    dupe = copy.deepcopy(bad["quests"][0])
    dupe["dependencies"] = ["q2"]  # keep the graph simple enough to isolate the code
    bad["quests"].append(dupe)
    report = validate_game_ir(bad)
    assert "ids.duplicate" in _codes(report)


# --------------------------------------------------------------------------- #
# 5. Referential integrity (refs.*)
# --------------------------------------------------------------------------- #

def test_entity_unknown_dialogue(good_ir_dict: dict[str, Any]) -> None:
    bad = copy.deepcopy(good_ir_dict)
    bad["entities"][1]["dialogue_id"] = "dlg_ghost"
    bad["entities"][1]["components"]["interactable"]["dialogue_id"] = "dlg_ghost"
    report = validate_game_ir(bad)
    errs = _find(report, "refs.missing_dialogue")
    assert len(errs) == 2
    assert {e.path for e in errs} == {
        "entities[1].dialogue_id",
        "entities[1].components.interactable.dialogue_id",
    }
    assert all("dlg_ghost" in e.message for e in errs)


def test_entity_unknown_sfx(good_ir_dict: dict[str, Any]) -> None:
    bad = copy.deepcopy(good_ir_dict)
    bad["entities"][0]["sfx_ids"] = ["sfx_nonexistent"]
    report = validate_game_ir(bad)
    errs = _find(report, "refs.missing_audio")
    assert [e.path for e in errs] == ["entities[0].sfx_ids[0]"]


def test_entity_bgm_used_as_sfx(good_ir_dict: dict[str, Any]) -> None:
    bad = copy.deepcopy(good_ir_dict)
    bad["entities"][0]["sfx_ids"] = ["bgm_main"]
    report = validate_game_ir(bad)
    errs = _find(report, "refs.wrong_audio_type")
    assert [e.path for e in errs] == ["entities[0].sfx_ids[0]"]
    assert "bgm" in errs[0].message


def test_quest_giver_unknown_quest(good_ir_dict: dict[str, Any]) -> None:
    bad = copy.deepcopy(good_ir_dict)
    bad["entities"][1]["components"]["quest_giver"]["quest_ids"] = ["q1", "q2", "q99"]
    report = validate_game_ir(bad)
    errs = _find(report, "refs.missing_quest")
    assert [e.path for e in errs] == ["entities[1].components.quest_giver.quest_ids[2]"]


def test_sprite_unknown_asset(good_ir_dict: dict[str, Any]) -> None:
    bad = copy.deepcopy(good_ir_dict)
    bad["entities"][0]["components"]["sprite"]["asset_id"] = "spr_phantom"
    report = validate_game_ir(bad)
    errs = _find(report, "refs.missing_asset")
    assert [e.path for e in errs] == ["entities[0].components.sprite.asset_id"]


def test_dialogue_unknown_npc(good_ir_dict: dict[str, Any]) -> None:
    bad = copy.deepcopy(good_ir_dict)
    bad["dialogues"][0]["npc_id"] = "npc_nobody"
    report = validate_game_ir(bad)
    errs = _find(report, "refs.missing_npc")
    assert errs[0].path == "dialogues[0].npc_id"


def test_quest_unknown_npc(good_ir_dict: dict[str, Any]) -> None:
    bad = copy.deepcopy(good_ir_dict)
    bad["quests"][1]["npcs_involved"] = ["npc_ghost"]
    report = validate_game_ir(bad)
    errs = _find(report, "refs.missing_npc")
    assert [e.path for e in errs] == ["quests[1].npcs_involved[0]"]


def test_quest_unknown_dependency(good_ir_dict: dict[str, Any]) -> None:
    bad = copy.deepcopy(good_ir_dict)
    bad["quests"][1]["dependencies"] = ["q_dne"]
    report = validate_game_ir(bad)
    errs = _find(report, "refs.missing_quest_dependency")
    assert [e.path for e in errs] == ["quests[1].dependencies"]
    assert "q_dne" in errs[0].message


def test_dialogue_choice_unknown_node(good_ir_dict: dict[str, Any]) -> None:
    bad = copy.deepcopy(good_ir_dict)
    bad["dialogues"][0]["nodes"][0]["choices"][0]["next"] = "n42"
    report = validate_game_ir(bad)
    errs = _find(report, "refs.missing_dialogue_node")
    assert [e.path for e in errs] == ["dialogues[0].nodes[0].choices[0].next"]


def test_manifest_unknown_refs(good_ir_dict: dict[str, Any]) -> None:
    bad = copy.deepcopy(good_ir_dict)
    bad["asset_manifest"].append(
        {"id": "spr_orphan", "path": "res://assets/sprites/orphan.png",
         "entity_id": "npc_ghost", "audio_request_id": "bgm_ghost"}
    )
    report = validate_game_ir(bad)
    assert _find(report, "refs.missing_entity")
    assert _find(report, "refs.missing_audio")


def test_audio_map_unknown_and_wrong_type(good_ir_dict: dict[str, Any]) -> None:
    bad = copy.deepcopy(good_ir_dict)
    bad["audio_map"]["ambient"] = ["audio_ghost"]
    bad["audio_map"]["zones"][0]["bgm_id"] = "sfx_step"   # sfx used as bgm
    bad["audio_map"]["zones"][0]["sfx_ids"] = ["sfx_ghost"]
    report = validate_game_ir(bad)
    assert [e.path for e in _find(report, "refs.missing_audio")] == [
        "audio_map.ambient[0]",
        "audio_map.zones[0].sfx_ids[0]",
    ]
    wrong = _find(report, "refs.wrong_audio_type")
    assert [e.path for e in wrong] == ["audio_map.zones[0].bgm_id"]


# --------------------------------------------------------------------------- #
# 6. Quest graph: cycles + reachability
# --------------------------------------------------------------------------- #

def test_quest_cycle_detected(good_ir_dict: dict[str, Any]) -> None:
    bad = copy.deepcopy(good_ir_dict)
    bad["quests"][0]["dependencies"] = ["q2"]  # q1 -> q2 -> q1
    report = validate_game_ir(bad)
    errs = _find(report, "quests.cycle")
    assert errs
    msg = errs[0].message
    assert "q1 -> q2 -> q1" in msg or "q2 -> q1 -> q2" in msg


def test_quest_self_cycle_detected(good_ir_dict: dict[str, Any]) -> None:
    bad = copy.deepcopy(good_ir_dict)
    bad["quests"][0]["dependencies"] = ["q1"]
    report = validate_game_ir(bad)
    assert _find(report, "quests.cycle")


def test_quest_unreachable(good_ir_dict: dict[str, Any]) -> None:
    bad = copy.deepcopy(good_ir_dict)
    bad["quests"].append(
        {
            "quest_id": "q3",
            "title": "q3.title",
            "description": "island quest depending on a missing branch",
            "stages": [{"id": "s1", "description": "x", "type": "objective"}],
            "dependencies": ["q_deadbeef"],  # unknown dep stays unresolved...
            "npcs_involved": [],
            "items_required": [],
        }
    )
    # ...but an unknown dependency must NOT count as resolved: q3 would be a
    # root then. Instead make q3 depend on a real quest that itself sits in a
    # disconnected cycle-free island unreachable from roots is impossible with
    # only deps — so craft: q3 depends on q4, q4 depends on q5, q5 depends on
    # q4 (cycle) is covered elsewhere. For pure unreachability use a quest
    # whose only dependency was pruned because it does not exist AND give it a
    # second variant below. Here we verify the unknown-dep ref error instead:
    report = validate_game_ir(bad)
    assert _find(report, "refs.missing_quest_dependency")
    assert not _find(report, "quests.unreachable")  # unknown dep keeps it a root


def test_quest_unreachable_isolated_chain(good_ir_dict: dict[str, Any]) -> None:
    """Every quest depends (transitively) on another → no root, all unreachable."""
    bad = copy.deepcopy(good_ir_dict)
    bad["quests"][0]["dependencies"] = ["q2"]
    bad["quests"][1]["dependencies"] = ["q1"]
    report = validate_game_ir(bad)
    assert "quests.cycle" in _codes(report)
    assert "quests.no_root" in _codes(report)
    assert "quests.unreachable" in _codes(report)


# --------------------------------------------------------------------------- #
# 7. Spawns inside rooms
# --------------------------------------------------------------------------- #

def test_enemy_spawn_outside_room(good_ir_dict: dict[str, Any]) -> None:
    bad = copy.deepcopy(good_ir_dict)
    bad["level_layout"]["enemy_spawn_points"] = [[20, 5], [39, 29]]
    report = validate_game_ir(bad)
    errs = _find(report, "spawns.outside_room")
    assert [e.path for e in errs] == ["level_layout.enemy_spawn_points[1]"]
    assert "(39, 29)" in errs[0].message


def test_item_spawn_outside_room(good_ir_dict: dict[str, Any]) -> None:
    bad = copy.deepcopy(good_ir_dict)
    bad["level_layout"]["item_spawn_points"] = [[-1, 3]]
    report = validate_game_ir(bad)
    assert _find(report, "spawns.outside_room")


def test_positioned_entity_outside_room(good_ir_dict: dict[str, Any]) -> None:
    bad = copy.deepcopy(good_ir_dict)
    bad["entities"][2]["position_x"] = 12  # corridor gap between room_0 and room_1
    bad["entities"][2]["position_y"] = 25
    report = validate_game_ir(bad)
    errs = _find(report, "spawns.entity_outside_room")
    assert [e.path for e in errs] == ["entities[2]"]
    assert "goblin" in errs[0].message


def test_start_end_room_must_resolve(good_ir_dict: dict[str, Any]) -> None:
    bad = copy.deepcopy(good_ir_dict)
    bad["level_layout"]["start_room"] = "room_99"
    bad["level_layout"]["end_room"] = "nowhere"
    report = validate_game_ir(bad)
    assert _find(report, "level.unknown_start_room")
    assert _find(report, "level.unknown_end_room")


# --------------------------------------------------------------------------- #
# 8. Asset manifest paths
# --------------------------------------------------------------------------- #

def test_manifest_bad_path(good_ir_dict: dict[str, Any]) -> None:
    bad = copy.deepcopy(good_ir_dict)
    bad["asset_manifest"][0]["path"] = "assets/sprites/player.png"  # no res://
    report = validate_game_ir(bad)
    errs = _find(report, "manifest.bad_path")
    assert [e.path for e in errs] == ["asset_manifest[0].path"]


def test_manifest_missing_file_with_project_root(good_ir_dict: dict[str, Any], tmp_path: Path) -> None:
    project = tmp_path / "godot_project"
    (project / "assets" / "sprites").mkdir(parents=True)
    (project / "assets" / "sprites" / "player.png").write_bytes(b"\x89PNG")
    (project / "assets" / "sprites" / "npc_elder.png").write_bytes(b"\x89PNG")
    # bgm_main.ogg deliberately absent
    report = validate_game_ir(good_ir_dict, project_root=project)
    errs = _find(report, "manifest.missing_file")
    assert [e.path for e in errs] == ["asset_manifest[2].path"]
    assert "bgm_main.ogg" in errs[0].message


def test_manifest_files_present_passes(good_ir_dict: dict[str, Any], tmp_path: Path) -> None:
    project = tmp_path / "godot_project"
    for rel in ("assets/sprites/player.png", "assets/sprites/npc_elder.png",
                "assets/music/bgm_main.ogg"):
        f = project / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"x")
    report = validate_game_ir(good_ir_dict, project_root=project)
    assert report.ok, report.render()


def test_manifest_check_files_disabled(good_ir_dict: dict[str, Any], tmp_path: Path) -> None:
    report = validate_game_ir(good_ir_dict, project_root=tmp_path, check_files=False)
    assert report.ok, report.render()


# --------------------------------------------------------------------------- #
# 9. Localization tr() keys
# --------------------------------------------------------------------------- #

def test_missing_dialogue_text_key(good_ir_dict: dict[str, Any]) -> None:
    bad = copy.deepcopy(good_ir_dict)
    bad["localization_table"]["entries"]["en"].pop("dlg.elder.greet")
    report = validate_game_ir(bad)
    errs = _find(report, "l10n.missing_key")
    assert [e.path for e in errs] == ["dialogues[0].nodes[0].text_key"]
    assert "dlg.elder.greet" in errs[0].message


def test_missing_choice_and_prompt_and_title_keys(good_ir_dict: dict[str, Any]) -> None:
    bad = copy.deepcopy(good_ir_dict)
    en = bad["localization_table"]["entries"]["en"]
    en.pop("dlg.elder.choice_yes")
    en.pop("ui.prompt_talk")
    en.pop("q2.title")
    report = validate_game_ir(bad)
    paths = {e.path for e in _find(report, "l10n.missing_key")}
    assert paths == {
        "dialogues[0].nodes[0].choices[0].text_key",
        "entities[1].components.interactable.prompt_key",
        "quests[1].title",
    }


def test_localization_conditions_keys_checked(good_ir_dict: dict[str, Any]) -> None:
    bad = copy.deepcopy(good_ir_dict)
    bad["dialogues"][0]["conditions"] = {"dlg.elder.locked": "Locked"}
    report = validate_game_ir(bad)
    errs = _find(report, "l10n.missing_key")
    assert [e.path for e in errs] == ["dialogues[0].conditions"]


# --------------------------------------------------------------------------- #
# 10. Warnings (non-fatal) — the good fixture avoids them; corruptions trigger
# --------------------------------------------------------------------------- #

def test_orphan_quest_and_unmodelled_item_warnings(good_ir_dict: dict[str, Any]) -> None:
    bad = copy.deepcopy(good_ir_dict)
    bad["entities"][1]["components"]["quest_giver"]["quest_ids"] = ["q1"]  # q2 orphaned
    bad["quests"][1]["items_required"] = ["rusty_sword"]
    report = validate_game_ir(bad)
    assert report.ok  # warnings never invalidate
    warn_codes = {w.code for w in report.warnings}
    assert "refs.orphan_quest" in warn_codes
    assert "refs.unmodelled_item" in warn_codes
    orphan = next(w for w in report.warnings if w.code == "refs.orphan_quest")
    assert orphan.path == "quests[1].quest_id"


def test_report_render_contains_codes(good_ir_dict: dict[str, Any]) -> None:
    bad = copy.deepcopy(good_ir_dict)
    bad["entities"][0]["sfx_ids"] = ["sfx_ghost"]
    rendered = validate_game_ir(bad).render()
    assert "FAIL" in rendered
    assert "[refs.missing_audio]" in rendered
