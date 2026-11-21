"""GameIR v2 assembler + validation-error attribution (Phase 11).

Turns the *agent outputs* held in :class:`GenerationState` into a single
validated :class:`~backend.schemas.agent_schemas.GameIR`:

- ``assemble_game_ir(state)`` maps every upstream output (GDD, quest graphs,
  dialogue trees, level layout, art assets, localization entries) onto the IR
  fields — entities with ECS components, rooms/spawns from ``LevelLayout``,
  ``asset_manifest``, ``audio_map``, ``localization_table`` — and runs the
  deterministic Phase-9 semantic validator (:func:`validate_game_ir`) over the
  result.  It never raises on bad content: structural problems are converted
  into :class:`IRError` items so callers always receive a
  :class:`AssemblyResult` with an actionable report.
- ``attribute_ir_errors(report)`` maps each :class:`IRError` back to the agent
  node responsible for the offending IR section (e.g. ``refs.missing_dialogue``
  under ``entities[3]`` → ``dialogue_writer``, the same error under a
  ``components.interactable`` path → ``quest_designer``) and renders per-agent
  feedback text that can be injected into the retrying agent's prompt.

The orchestrator wires ``ir_assembler`` between ``persist_files`` and ``qa``:
on validation failure it routes back to the responsible agent (bounded by
``MAX_IR_RETRIES``), after which the run fails/rolls back with the assembled
error text.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Optional, Union

from pydantic import ValidationError

from backend.schemas.agent_schemas import (
    AudioMap,
    AudioMapZone,
    AudioRequest,
    CameraConfig,
    DialogueTree,
    EntityRequest,
    GameDesignDocument,
    GameIR,
    InteractableComponent,
    LevelLayout,
    QuestGraph,
    QuestGiverComponent,
    SpriteComponent,
)
from backend.services.ir_validator import (
    IRError,
    ValidationReport,
    _dedupe,
    validate_game_ir,
)

__all__ = [
    "AssemblyResult",
    "assemble_game_ir",
    "attribute_ir_errors",
    "format_agent_feedback",
    "AGENT_NODE_FOR_SECTION",
    "MAX_IR_RETRIES",
]

#: Bounded retries for IR-validation feedback loops inside the graph.
MAX_IR_RETRIES = 2

#: IR top-level section (dot-path prefix) -> agent node that owns it.  Used as
#: the fallback attribution when no more specific rule matches.
AGENT_NODE_FOR_SECTION: dict[str, str] = {
    "design_document": "designer",
    "audio_requests": "showrunner",
    "entities": "coder",
    "quests": "quest_designer",
    "dialogues": "dialogue_writer",
    "level_layout": "level_generator",
    "asset_manifest": "art_director",
    "audio_map": "level_generator",
    "localization_table": "localization",
    "camera": "architect",
}

#: Error codes owned by the Localization Manager regardless of their path —
#: every tr() key referenced anywhere in the IR must exist in its table.
_LOCALIZATION_CODES = frozenset({"l10n.missing_key"})


def _section_of(path: str) -> str:
    """Top-level IR section name of a validator dot-path (``$`` → ``''``)."""
    if not path or path == "$":
        return ""
    head = path.split(".", 1)[0]
    return head.split("[", 1)[0]


def attribute_ir_errors(report: ValidationReport) -> dict[str, list[IRError]]:
    """Group validation errors by the agent node responsible for fixing them.

    Attribution rules (most specific wins):

    1. ``l10n.*`` codes → ``localization`` (the Localization Manager owns the
       tr() table, wherever the missing key is referenced);
    2. entity paths containing ``components.interactable`` → ``quest_designer``
       (the coder mirrors quest/objective definitions into interactable
       components, so dangling interaction targets are its contract violation);
    3. any other path → :data:`AGENT_NODE_FOR_SECTION` lookup on the path's
       top-level section; unknown sections fall back to ``coder`` (it authors
       the code-side IR inputs).
    """
    grouped: dict[str, list[IRError]] = {}
    for err in report.errors:
        grouped.setdefault(_responsible_node(err), []).append(err)
    return grouped


def _responsible_node(err: IRError) -> str:
    if err.code in _LOCALIZATION_CODES or _section_of(err.path) == "localization_table":
        return "localization"
    if _section_of(err.path) == "entities" and "components.interactable" in err.path:
        return "quest_designer"
    return AGENT_NODE_FOR_SECTION.get(_section_of(err.path), "coder")


def format_agent_feedback(node: str, errors: Iterable[IRError]) -> str:
    """Actionable, multi-line feedback text for one agent's retry prompt."""
    lines = [f"GameIR validation failed. Fix these {node} issues and re-run:"]
    for err in errors:
        lines.append(f"- [{err.code}] {err.path}: {err.message}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Assembly helpers
# --------------------------------------------------------------------------- #


def _model(obj: Any, model_cls: type, *, strict: bool = True) -> Any:
    """Coerce a model instance / dict / None into *model_cls*.

    With ``strict=False`` invalid inputs degrade to ``None`` instead of raising
    (used for optional state fields fed by stub/partial agents).
    """
    if obj is None:
        return None
    if isinstance(obj, model_cls):
        return obj
    if isinstance(obj, Mapping):
        try:
            return model_cls.model_validate(obj)
        except ValidationError:
            if strict:
                raise
            return None
    if strict:
        return model_cls.model_validate(obj)
    return None  # pragma: no cover - defensive


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def _room_id(room: Any, index: int) -> str:
    rid = getattr(room, "id", None)
    if isinstance(rid, str) and rid:
        return rid
    return f"room_{index}"


def _in_room(layout: Any, x: float, y: float) -> bool:  # pragma: no cover - parity helper
    for room in getattr(layout, "rooms", []) or []:
        rx = getattr(room, "x", 0)
        ry = getattr(room, "y", 0)
        rw = getattr(room, "width", 0)
        rh = getattr(room, "height", 0)
        if rx <= x < rx + rw and ry <= y < ry + rh:
            return True
    return False


def _first_spawn_in_room(layout: Any, points: Iterable[Any], room: Any) -> Optional[tuple[int, int]]:
    for point in points or []:
        try:
            px, py = int(point[0]), int(point[1])
        except (TypeError, ValueError, IndexError):
            continue
        if (
            getattr(room, "x", 0) <= px < getattr(room, "x", 0) + getattr(room, "width", 0)
            and getattr(room, "y", 0) <= py < getattr(room, "y", 0) + getattr(room, "height", 0)
        ):
            return (px, py)
    return None


def _slot_entity_type(slot: str) -> str:
    return {
        "player": "player",
        "npc": "npc",
        "enemy": "enemy",
        "item": "item",
        "hazard": "hazard",
    }.get(slot, "decoration")


def _default_audio_requests(wizard: Any) -> list[AudioRequest]:
    """Baseline audio budget derived from the wizard config.

    No agent currently emits :class:`AudioRequest`s (see PHASE_NOTES Phase 11
    adjacent bug #1), so the assembler seeds one looping BGM request plus one
    UI blip SFX; the API audio endpoint and the godot integrator consume them.
    """
    theme = (getattr(wizard, "setting", "") or "").strip() or (
        getattr(wizard, "genre", "") or "game"
    )
    return [
        AudioRequest(
            id="bgm_main_theme",
            type="bgm",
            description=f"Looping main theme for {theme}",
            duration_sec=60,
            loop=True,
        ),
        AudioRequest(
            id="sfx_ui_select",
            type="sfx",
            description="Short UI selection blip",
            duration_sec=5,
            loop=False,
        ),
    ]


def _collect_npc_ids(state: Mapping[str, Any]) -> list[str]:
    """Stable de-duplicated NPC ids from quests, dialogues and entities."""
    ids: list[str] = []
    for quest in _as_list(state.get("quest_graphs")):
        ids.extend(str(n) for n in (getattr(quest, "npcs_involved", None) or []))
    for dlg in _as_list(state.get("dialogue_trees")):
        npc = getattr(dlg, "npc_id", None)
        if npc:
            ids.append(str(npc))
    for ent in _as_list(state.get("entities")):
        eid = getattr(ent, "id", None) or (ent.get("id") if isinstance(ent, Mapping) else None)
        etype = getattr(ent, "type", None) or (ent.get("type") if isinstance(ent, Mapping) else None)
        if eid and (etype in (None, "npc")):
            ids.append(str(eid))
    seen: set[str] = set()
    out: list[str] = []
    for i in ids:
        if i and i not in seen:
            seen.add(i)
            out.append(i)
    return out


def _build_entities(
    state: Mapping[str, Any],
    layout: Any,
    dialogue_ids: set[str],
    quest_by_id: Mapping[str, Any],
    asset_ids: set[str],
    audio_request_ids: set[str],
) -> list[EntityRequest]:
    """Merge slot-derived entities, quest NPCs and explicit entity requests."""
    entities: dict[str, EntityRequest] = {}

    def get_or_create(eid: str, etype: str = "npc") -> EntityRequest:
        ent = entities.get(eid)
        if ent is None:
            ent = EntityRequest(id=eid, name=eid.replace("_", " ").title(), type=etype)
            entities[eid] = ent
        return ent

    # 1. Art slots → one visual entity per generated sprite slot.
    for asset in _as_list(state.get("generated_assets")):
        if getattr(asset, "asset_type", None) != "sprite":
            continue
        slot = str(asset.slot)
        ent = get_or_create(slot, _slot_entity_type(slot))
        if slot in asset_ids:
            ent.components.sprite = SpriteComponent(asset_id=slot)

    # 2. Quest NPCs → npc entities wired to their dialogue + given quests.
    for npc_id in _collect_npc_ids(state):
        ent = get_or_create(npc_id, "npc")
        for dlg in _as_list(state.get("dialogue_trees")):
            if str(getattr(dlg, "npc_id", "")) == npc_id:
                did = str(dlg.dialogue_id)
                if did in dialogue_ids:
                    ent.dialogue_id = did
                    ent.components.interactable = InteractableComponent(
                        trigger="interact",
                        prompt_key=f"{did}_prompt",
                        dialogue_id=did,
                    )
                break
        given = [qid for qid, q in quest_by_id.items() if npc_id in [str(n) for n in (q.npcs_involved or [])]]
        if given:
            ent.components.quest_giver = QuestGiverComponent(quest_ids=given)

    # 3. Explicit entity requests (upstream agents / future designer output).
    for raw in _as_list(state.get("entities")):
        try:
            ent = raw if isinstance(raw, EntityRequest) else EntityRequest.model_validate(raw)
        except ValidationError:
            continue  # structural problems surface via the GameIR load below
        existing = entities.get(ent.id)
        if existing is None:
            entities[ent.id] = ent
            continue
        merged = ent.model_copy(update={"components": existing.components})
        merged.components = existing.components.model_copy(deep=True)
        for comp_name in ("movement", "combat", "interactable", "quest_giver", "sprite"):
            incoming = getattr(ent.components, comp_name)
            if incoming is not None:
                setattr(merged.components, comp_name, incoming)
        entities[ent.id] = merged

    result = list(entities.values())

    # 4. Positions: place entities inside rooms deterministically (tile space).
    if layout is not None and layout.rooms:
        rooms = list(layout.rooms)
        enemy_rooms = [r for r in rooms if getattr(r, "room_type", "") in ("enemy", "combat", "boss")] or rooms
        item_rooms = [r for r in rooms if getattr(r, "room_type", "") in ("item", "treasure")] or rooms
        enemy_i = item_i = generic_i = 0
        for ent in result:
            if ent.position_x is not None and ent.position_y is not None:
                continue
            room = None
            if ent.type == "enemy":
                room = enemy_rooms[enemy_i % len(enemy_rooms)]
                enemy_i += 1
            elif ent.type == "item":
                room = item_rooms[item_i % len(item_rooms)]
                item_i += 1
            elif ent.type in ("npc", "player"):
                room = rooms[generic_i % len(rooms)]
                generic_i += 1
            if room is None:
                continue
            center_x = room.x + max(room.width // 2, 1)
            center_y = room.y + max(room.height // 2, 1)
            spawn = _first_spawn_in_room(layout, layout.enemy_spawn_points, room) if ent.type == "enemy" else None
            if spawn is None:
                spawn = _first_spawn_in_room(layout, layout.item_spawn_points, room) if ent.type == "item" else None
            ent.position_x, ent.position_y = spawn if spawn is not None else (center_x, center_y)

    # 5. Reference sanitisation: keep only references that resolve inside the IR.
    for ent in result:
        if ent.dialogue_id is not None and ent.dialogue_id not in dialogue_ids:
            ent.dialogue_id = None
        ent.sfx_ids = [s for s in ent.sfx_ids if s in audio_request_ids]
        interactable = ent.components.interactable
        if interactable is not None and interactable.dialogue_id not in (None, "") \
                and interactable.dialogue_id not in dialogue_ids:
            interactable.dialogue_id = None
        if interactable is not None and interactable.dialogue_id is None \
                and ent.components.quest_giver is None:
            # An interactable without any target would be dead weight.
            ent.components.interactable = None
        giver = ent.components.quest_giver
        if giver is not None:
            giver.quest_ids = [q for q in giver.quest_ids if q in quest_by_id]
            if not giver.quest_ids:
                ent.components.quest_giver = None
        sprite = ent.components.sprite
        if sprite is not None and sprite.asset_id not in asset_ids:
            ent.components.sprite = None

    return result


def _build_localization_table(
    state: Mapping[str, Any],
    quests: list[Any],
    dialogues: list[Any],
    entities: list[EntityRequest],
    default_locale: str,
) -> dict[str, dict[str, str]]:
    """Locale map guaranteed to define every tr() key the IR references.

    Seeds from the Localization Manager's ``LocalizationOutput`` (best effort —
    it may legitimately be absent since that stage runs after assembly), then
    fills in quest titles/stages, dialogue node/choice keys and interact
    prompts with humanised placeholder strings so the validator's l10n pass is
    meaningful.  The Localization Manager refines the values later.
    """
    table: dict[str, dict[str, str]] = {}
    loc_output = state.get("localization_output")
    for loc_file in getattr(loc_output, "localization_files", None) or []:
        locale = str(loc_file.locale)
        bucket = table.setdefault(locale, {})
        bucket.update({str(k): str(v) for k, v in (loc_file.strings or {}).items()})
    entries = getattr(loc_output, "entries", None)
    if entries and default_locale not in table:
        table[default_locale] = {
            str(e.key): str(e.value) for e in entries
        }

    def humanise(key: str) -> str:
        return key.replace("_", " ").strip().title() or key

    def put(key: str, value: Optional[str] = None) -> None:
        if not key:
            return
        bucket = table.setdefault(default_locale, {})
        bucket.setdefault(key, value if value is not None else humanise(key))

    def _put_condition_keys(emit, conditions: Any) -> None:
        """Mirror ir_validator's condition tr() extraction (keys/text_key/{k:v})."""
        if not isinstance(conditions, dict):
            return
        text_key = conditions.get("text_key")
        if isinstance(text_key, str) and text_key:
            emit(text_key)
        keys_field = conditions.get("keys")
        if isinstance(keys_field, list):
            for k in keys_field:
                if isinstance(k, str) and k:
                    emit(k)
        for k, v in conditions.items():
            if k in ("text_key", "keys"):
                continue
            if isinstance(v, str) and v:
                emit(k)

    for quest in quests:
        put(quest.title)
        for stage in quest.stages:
            put(f"{quest.quest_id}_{stage.id}")
            # QuestStage.conditions is checked by ir_validator via getattr on
            # the *stage* object (condition_keys(stage, ...)).
            _put_condition_keys(put, getattr(stage, "conditions", None))
    for dlg in dialogues:
        _put_condition_keys(put, dlg.conditions)
        for node in dlg.nodes:
            put(node.text_key)
            for choice in node.choices:
                put(choice.text_key)
    for ent in entities:
        interactable = ent.components.interactable
        if interactable is not None and interactable.prompt_key:
            put(interactable.prompt_key, f"Interact with {ent.name or ent.id}")
    return table


def _asset_id(asset: Any) -> str:
    """Stable manifest id for a GeneratedAsset (no ``id`` field on the model)."""
    explicit = getattr(asset, "id", None)
    if isinstance(explicit, str) and explicit:
        return explicit
    from pathlib import Path as _P

    stem = _P(str(asset.path)).stem
    return f"{asset.asset_type}_{stem}".replace("-", "_")


def _build_asset_manifest(state: Mapping[str, Any], entities: list[EntityRequest]) -> list[dict[str, Any]]:
    ent_ids = {e.id for e in entities}
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for asset in _as_list(state.get("generated_assets")):
        aid = _asset_id(asset)
        if aid in seen:
            continue
        seen.add(aid)
        kind = {
            "sprite": "sprite",
            "texture": "other",
            "sound": "audio",
            "music": "music",
            "ui": "ui",
        }.get(str(getattr(asset, "asset_type", "sprite")), "other")
        entry: dict[str, Any] = {"id": aid, "path": str(asset.path), "kind": kind}
        if kind == "sprite":
            slot = str(asset.slot)
            if slot in ent_ids:
                entry["entity_id"] = slot
        entries.append(entry)
    return entries


def _build_audio_map(state: Mapping[str, Any], layout: Any, audio_requests: list[AudioRequest]) -> AudioMap:
    bgm_ids = [a.id for a in audio_requests if a.type == "bgm"]
    sfx_ids = [a.id for a in audio_requests if a.type == "sfx"]
    zones: list[AudioMapZone] = []
    if layout is not None:
        for idx, room in enumerate(layout.rooms):
            zone: dict[str, Any] = {
                "id": f"zone_{_room_id(room, idx)}",
                "rect": (float(room.x), float(room.y), float(room.width), float(room.height)),
            }
            if idx == 0 and bgm_ids:
                zone["bgm_id"] = bgm_ids[0]
            if sfx_ids:
                zone["sfx_ids"] = [sfx_ids[0]]
            zones.append(AudioMapZone.model_validate(zone))
    return AudioMap(zones=zones, ambient=list(bgm_ids[:1]))


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #


@dataclass
class AssemblyResult:
    """Outcome of :func:`assemble_game_ir`."""

    ir: Optional[GameIR]
    report: ValidationReport
    #: ``agent node -> actionable feedback text`` for routing retries.
    agent_feedback: dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.report.ok

    @property
    def error_summary(self) -> str:
        return self.report.render()


def assemble_game_ir(
    state: Union[Mapping[str, Any], Any],
    *,
    default_locale: str = "en",
    genre_template_id: Optional[str] = None,
    check_files: bool = False,
    project_root: Any = None,
) -> AssemblyResult:
    """Build a validated GameIR v2 from orchestrator ``GenerationState`` outputs.

    Accepts a mapping (state dict) or any object exposing the state keys as
    attributes.  Never raises on invalid agent content: structural failures
    become ``schema.invalid`` errors in the returned report, and semantic
    failures come from :func:`validate_game_ir` (run with ``check_files=False``
    by default — generated files may not be persisted yet at assembly time).
    """
    def get(key: str, default: Any = None) -> Any:
        if isinstance(state, Mapping):
            return state.get(key, default)
        return getattr(state, key, default)

    design_document = _model(get("gdd"), GameDesignDocument, strict=False)

    layout = _model(get("level_layout"), LevelLayout, strict=False)
    if layout is not None and getattr(layout, "rooms", None):
        # Stable room ids ('room_<i>') so start/end_room and zone refs resolve.
        for idx, room in enumerate(layout.rooms):
            if not getattr(room, "id", None):
                room.id = _room_id(room, idx)

    quests = [q for q in (_model(q, QuestGraph) for q in _as_list(get("quest_graphs"))) if q is not None]
    dialogues = [d for d in (_model(d, DialogueTree) for d in _as_list(get("dialogue_trees"))) if d is not None]

    audio_raw = get("audio_requests")
    audio_requests = [
        a
        for a in (
            _model(x, AudioRequest)
            for x in (_as_list(audio_raw) or _default_audio_requests(get("wizard_input")))
        )
        if a is not None
    ]

    camera = _model(get("camera"), CameraConfig, strict=False) or CameraConfig()
    perspective = (getattr(get("wizard_input"), "perspective", "") or "").lower()
    if not isinstance(get("camera"), (CameraConfig, Mapping)) and "platform" in perspective:
        camera.mode = "platformer"

    dialogue_ids = {d.dialogue_id for d in dialogues}
    quest_by_id = {q.quest_id: q for q in quests}

    pre_manifest = _build_asset_manifest(state, [])
    asset_ids = {str(e["id"]) for e in pre_manifest}
    audio_request_ids = {a.id for a in audio_requests}

    entities = _build_entities(state, layout, dialogue_ids, quest_by_id, asset_ids, audio_request_ids)

    manifest = _build_asset_manifest(state, entities)
    localization_entries = _build_localization_table(state, quests, dialogues, entities, default_locale)
    audio_map = _build_audio_map(state, layout, audio_requests)

    payload: dict[str, Any] = {
        "schema_version": 2,
        "genre_template_id": genre_template_id,
        "design_document": design_document,
        "audio_requests": audio_requests,
        "entities": entities,
        "quests": quests,
        "dialogues": dialogues,
        "level_layout": layout,
        "camera": camera,
        "asset_manifest": manifest,
        "localization_table": {"default_locale": default_locale, "entries": localization_entries},
        "audio_map": audio_map,
    }

    errors: list[IRError] = []
    model: Optional[GameIR] = None
    try:
        model = GameIR.model_validate(payload)
    except ValidationError as exc:
        for issue in exc.errors():
            loc = ".".join(str(p) for p in issue["loc"]) or "$"
            errors.append(IRError(code="schema.invalid", path=loc, message=str(issue["msg"])))

    if model is not None:
        report = validate_game_ir(model, project_root=project_root, check_files=check_files)
        errors = _dedupe([*errors, *report.errors])
        warnings = report.warnings
    else:
        warnings = []

    final_report = ValidationReport(errors=errors, warnings=warnings)
    grouped = attribute_ir_errors(final_report)
    feedback = {node: format_agent_feedback(node, errs) for node, errs in grouped.items()}
    return AssemblyResult(ir=model, report=final_report, agent_feedback=feedback)
