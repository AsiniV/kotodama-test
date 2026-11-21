"""GameIR v2 validator (Phase 9) — deterministic, offline cross-reference checks.

``backend/schemas/agent_schemas.py`` guarantees *structural* validity of a
GameIR via pydantic; this module guarantees *semantic* validity:

- referential integrity: unique ids everywhere; entity ``dialogue_id`` /
  ``sfx_ids``, quest ``npcs_involved`` / ``items_required`` / ``dependencies``,
  dialogue ``npc_id``, component references (interactable→dialogue,
  quest_giver→quest, sprite→asset manifest) and audio-map references all point
  at things that exist in the same IR;
- quest graph is acyclic **and** every quest is reachable from a root quest
  (a quest with no unresolved dependencies);
- spawns (enemy/item spawn points and positioned entities) fall inside rooms
  of the level layout;
- asset manifest paths are well-formed Godot resource paths (``res://`` or an
  absolute filesystem path) and — when a project root is provided — the files
  actually exist on disk;
- every tr() key referenced by dialogues (node/choice ``text_key``), interact
  prompts and quest titles is present in the localization table for the
  default locale.

The validator never raises on bad content: it collects :class:`IRError` items
(code + dot-path + human message) and reports them together with non-fatal
:class:`IRWarning` items (e.g. quests whose declared item requirements are not
modelled as ``type='item'`` entities — the item registry lives outside the IR
today). A corrupted IR is therefore rejected with *precise*, machine-readable
errors instead of one opaque exception.

Usage::

    report = validate_game_ir(ir)            # GameIR | dict
    if not report.ok:
        raise ValueError(report.render())
"""
from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional, Union

from pydantic import ValidationError

from backend.schemas.agent_schemas import GAME_IR_SCHEMA_VERSION, GameIR

__all__ = [
    "IRError",
    "IRWarning",
    "ValidationReport",
    "validate_game_ir",
]

#: Paths accepted in ``AssetManifestEntry.path``: Godot res:// (or user://)
#: resource paths, or absolute filesystem paths.
_PATH_RE = re.compile(r"^(res://|user://|[A-Za-z]:[\\/]|/)[^|]+$")


@dataclass(frozen=True)
class IRError:
    """One precise validation failure."""

    code: str
    path: str
    message: str

    def __str__(self) -> str:
        return f"[{self.code}] {self.path}: {self.message}"


@dataclass(frozen=True)
class IRWarning:
    """Non-fatal consistency observation (does not make the IR invalid)."""

    code: str
    path: str
    message: str

    def __str__(self) -> str:
        return f"[{self.code}] {self.path}: {self.message}"


@dataclass
class ValidationReport:
    """Outcome of :func:`validate_game_ir`."""

    errors: list[IRError]
    warnings: list[IRWarning]

    @property
    def ok(self) -> bool:
        return not self.errors

    @property
    def error_codes(self) -> set[str]:
        return {e.code for e in self.errors}

    def render(self, limit: int = 50) -> str:
        """Human/machine-readable multi-line summary used in logs and CI."""
        lines = [f"GameIR validation: {'PASS' if self.ok else 'FAIL'}"]
        for err in self.errors[:limit]:
            lines.append(f"  ERROR {err}")
        if len(self.errors) > limit:
            lines.append(f"  ... {len(self.errors) - limit} more errors")
        for warn in self.warnings[:limit]:
            lines.append(f"  WARN  {warn}")
        return "\n".join(lines)


def _dedupe(items: Iterable[Union[IRError, IRWarning]]) -> list[Any]:
    seen: set[tuple[str, str, str]] = set()
    out: list[Any] = []
    for item in items:
        key = (item.code, item.path, item.message)
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out


def validate_game_ir(
    ir: Union[GameIR, dict[str, Any], None],
    *,
    project_root: Optional[Path] = None,
    check_files: bool = True,
) -> ValidationReport:
    """Validate a GameIR (v1- or v2-shaped dict, or a GameIR instance).

    Args:
        ir: the intermediate representation to check.
        project_root: Godot project directory (contains the ``res://`` tree).
            Required for on-disk existence checks of manifest paths.
        check_files: when False, manifest paths are only syntax-checked even if
            ``project_root`` is given.
    """
    errors: list[IRError] = []
    warnings: list[IRWarning] = []

    def err(code: str, path: str, message: str) -> None:
        errors.append(IRError(code=code, path=path, message=message))

    def warn(code: str, path: str, message: str) -> None:
        warnings.append(IRWarning(code=code, path=path, message=message))

    # ------------------------------------------------------------------ #
    # Structural load (pydantic) — everything below assumes a GameIR.
    # ------------------------------------------------------------------ #
    if ir is None:
        err("schema.invalid", "$", "GameIR is missing (None)")
        return ValidationReport(errors=_dedupe(errors), warnings=_dedupe(warnings))

    if isinstance(ir, GameIR):
        model = ir
    elif isinstance(ir, dict):
        try:
            model = GameIR.model_validate(ir)
        except ValidationError as exc:
            for issue in exc.errors():
                loc = ".".join(str(p) for p in issue["loc"]) or "$"
                err("schema.invalid", loc, str(issue["msg"]))
            return ValidationReport(errors=_dedupe(errors), warnings=_dedupe(warnings))
    else:
        err("schema.invalid", "$", f"Expected GameIR or dict, got {type(ir).__name__}")
        return ValidationReport(errors=_dedupe(errors), warnings=_dedupe(warnings))

    if model.schema_version > GAME_IR_SCHEMA_VERSION:
        err(
            "schema.version_unsupported",
            "schema_version",
            f"IR schema_version={model.schema_version} is newer than the supported "
            f"v{GAME_IR_SCHEMA_VERSION}; refuse to guess semantics",
        )

    # ------------------------------------------------------------------ #
    # Local id registries + duplicate detection
    # ------------------------------------------------------------------ #
    def collect_ids(objects: Iterable[Any], coll: str, attr: str = "id") -> dict[str, int]:
        registry: dict[str, int] = {}
        for i, obj in enumerate(objects):
            oid = getattr(obj, attr, None)
            if oid is None:
                continue
            if oid in registry:
                err(
                    "ids.duplicate",
                    f"{coll}[{i}].{attr}",
                    f"duplicate {attr} {oid!r} (first seen at {coll}[{registry[oid]}])",
                )
            else:
                registry[oid] = i
        return registry

    entity_ids = collect_ids(model.entities, "entities")
    audio_ids = collect_ids(model.audio_requests, "audio_requests")
    dialogue_ids = collect_ids(model.dialogues, "dialogues", "dialogue_id")
    quest_ids = collect_ids(model.quests, "quests", "quest_id")
    asset_ids = collect_ids(model.asset_manifest, "asset_manifest")
    collect_ids(model.audio_map.zones, "audio_map.zones")

    bgm_ids = {a.id for a in model.audio_requests if a.type == "bgm"}
    audio_sfx_ids = {a.id for a in model.audio_requests if a.type == "sfx"}
    room_ids = {rid for rid, _ in _rooms(model)}

    # ------------------------------------------------------------------ #
    # Referential integrity: entities & their components
    # ------------------------------------------------------------------ #
    for i, ent in enumerate(model.entities):
        base = f"entities[{i}]"
        if ent.dialogue_id is not None and ent.dialogue_id not in dialogue_ids:
            err(
                "refs.missing_dialogue",
                f"{base}.dialogue_id",
                f"entity {ent.id!r} references unknown dialogue_id {ent.dialogue_id!r}",
            )
        for j, sid in enumerate(ent.sfx_ids):
            if sid not in audio_ids:
                err(
                    "refs.missing_audio",
                    f"{base}.sfx_ids[{j}]",
                    f"entity {ent.id!r} references unknown sfx/audio id {sid!r}",
                )
            elif sid not in audio_sfx_ids:
                err(
                    "refs.wrong_audio_type",
                    f"{base}.sfx_ids[{j}]",
                    f"entity {ent.id!r} sfx id {sid!r} refers to a 'bgm' AudioRequest, not 'sfx'",
                )
        comp = ent.components
        if comp.interactable is not None:
            if comp.interactable.dialogue_id and comp.interactable.dialogue_id not in dialogue_ids:
                err(
                    "refs.missing_dialogue",
                    f"{base}.components.interactable.dialogue_id",
                    f"entity {ent.id!r} interactable opens unknown dialogue "
                    f"{comp.interactable.dialogue_id!r}",
                )
        if comp.quest_giver is not None:
            for j, qid in enumerate(comp.quest_giver.quest_ids):
                if qid not in quest_ids:
                    err(
                        "refs.missing_quest",
                        f"{base}.components.quest_giver.quest_ids[{j}]",
                        f"entity {ent.id!r} gives unknown quest {qid!r}",
                    )
        if comp.sprite is not None and comp.sprite.asset_id and comp.sprite.asset_id not in asset_ids:
            err(
                "refs.missing_asset",
                f"{base}.components.sprite.asset_id",
                f"entity {ent.id!r} sprite references unknown asset id {comp.sprite.asset_id!r}",
            )

    # ------------------------------------------------------------------ #
    # Referential integrity: dialogues
    # ------------------------------------------------------------------ #
    for i, dlg in enumerate(model.dialogues):
        base = f"dialogues[{i}]"
        if dlg.npc_id not in entity_ids:
            err(
                "refs.missing_npc",
                f"{base}.npc_id",
                f"dialogue {dlg.dialogue_id!r} belongs to unknown npc_id {dlg.npc_id!r}",
            )
        node_ids = {n.id for n in dlg.nodes}
        for j, node in enumerate(dlg.nodes):
            for k, choice in enumerate(node.choices):
                nxt = choice.next
                if nxt in ("", "END", "end"):
                    continue
                if nxt not in node_ids:
                    err(
                        "refs.missing_dialogue_node",
                        f"{base}.nodes[{j}].choices[{k}].next",
                        f"dialogue {dlg.dialogue_id!r}: choice leads to unknown node {nxt!r}",
                    )

    # ------------------------------------------------------------------ #
    # Referential integrity: quests (+ npcs_involved after components pass)
    # ------------------------------------------------------------------ #
    for i, quest in enumerate(model.quests):
        base = f"quests[{i}]"
        for dep in quest.dependencies:
            if dep not in quest_ids:
                err(
                    "refs.missing_quest_dependency",
                    f"{base}.dependencies",
                    f"quest {quest.quest_id!r} depends on unknown quest {dep!r}",
                )
        for j, stage in enumerate(quest.stages):
            if stage.location and model.level_layout is not None:
                room_names = {r.room_type for r in model.level_layout.rooms}
                if stage.location not in room_names and stage.location not in room_ids:
                    warn(
                        "refs.unknown_location",
                        f"{base}.stages[{j}].location",
                        f"stage {stage.id!r} names location {stage.location!r} not found in "
                        "level rooms (by id or room_type)",
                    )
        for j, npc in enumerate(quest.npcs_involved):
            if npc not in entity_ids:
                err(
                    "refs.missing_npc",
                    f"{base}.npcs_involved[{j}]",
                    f"quest {quest.quest_id!r} involves unknown entity {npc!r}",
                )

    # Quest-giver back-references: every quest should be offered by someone.
    offered: set[str] = set()
    for ent in model.entities:
        if ent.components.quest_giver is not None:
            offered.update(ent.components.quest_giver.quest_ids)
    for i, quest in enumerate(model.quests):
        if quest.quest_id not in offered:
            warn(
                "refs.orphan_quest",
                f"quests[{i}].quest_id",
                f"quest {quest.quest_id!r} is not offered by any quest_giver entity",
            )

    # Item requirements without a matching item entity → warning (the item
    # registry lives outside the IR today; see PHASE_NOTES Phase 9).
    item_entity_ids = {e.id for e in model.entities if e.type == "item"}
    for i, quest in enumerate(model.quests):
        for j, item in enumerate(quest.items_required):
            if item not in item_entity_ids:
                warn(
                    "refs.unmodelled_item",
                    f"quests[{i}].items_required[{j}]",
                    f"quest {quest.quest_id!r} requires {item!r} which is not an "
                    "entity of type 'item' (item registry not part of the IR)",
                )

    # ------------------------------------------------------------------ #
    # Quest graph: acyclic + reachable
    # ------------------------------------------------------------------ #
    resolved_deps: dict[str, list[str]] = {}
    for quest in model.quests:
        resolved_deps[quest.quest_id] = [d for d in quest.dependencies if d in quest_ids]

    cycle = _find_cycle(resolved_deps)
    if cycle:
        err(
            "quests.cycle",
            "quests",
            "quest dependency cycle detected: " + " -> ".join([*cycle, cycle[0]]),
        )

    dependents: dict[str, list[str]] = {qid: [] for qid in quest_ids}
    for qid, deps in resolved_deps.items():
        for d in deps:
            dependents.setdefault(d, []).append(qid)

    roots = [qid for qid, deps in resolved_deps.items() if not deps]
    if quest_ids and not roots:
        err(
            "quests.no_root",
            "quests",
            "quest graph has no root quest (every quest depends on another; "
            + ("cycle above" if cycle else "unresolvable"),
        )

    reached: set[str] = set()
    dq = deque(roots)
    while dq:
        cur = dq.popleft()
        if cur in reached:
            continue
        reached.add(cur)
        dq.extend(dependents.get(cur, []))
    unreachable = sorted(set(quest_ids) - reached)
    if unreachable:
        err(
            "quests.unreachable",
            "quests",
            "quest(s) unreachable from any root: " + ", ".join(unreachable),
        )

    # ------------------------------------------------------------------ #
    # Level layout: spawns inside rooms
    # ------------------------------------------------------------------ #
    layout = model.level_layout
    if layout is not None:
        rooms = list(layout.rooms)
        for label, points in (
            ("enemy_spawn_points", layout.enemy_spawn_points),
            ("item_spawn_points", layout.item_spawn_points),
        ):
            for j, (px, py) in enumerate(points):
                if not any(_in_room(px, py, r) for r in rooms):
                    err(
                        "spawns.outside_room",
                        f"level_layout.{label}[{j}]",
                        f"spawn point ({px}, {py}) lies outside every room of the level layout",
                    )
        for i, ent in enumerate(model.entities):
            if ent.position_x is None or ent.position_y is None:
                continue
            if not any(_in_room(ent.position_x, ent.position_y, r) for r in rooms):
                err(
                    "spawns.entity_outside_room",
                    f"entities[{i}]",
                    f"entity {ent.id!r} at ({ent.position_x}, {ent.position_y}) is outside every room",
                )
        if layout.start_room not in room_ids:
            err(
                "level.unknown_start_room",
                "level_layout.start_room",
                f"start_room {layout.start_room!r} does not match any room id ('room_<i>' "
                "by index, or Room.id when set)",
            )
        if layout.end_room not in room_ids:
            err(
                "level.unknown_end_room",
                "level_layout.end_room",
                f"end_room {layout.end_room!r} does not match any room id",
            )

    # ------------------------------------------------------------------ #
    # Asset manifest: path syntax + on-disk existence
    # ------------------------------------------------------------------ #
    for i, entry in enumerate(model.asset_manifest):
        base = f"asset_manifest[{i}]"
        if entry.entity_id is not None and entry.entity_id not in entity_ids:
            err(
                "refs.missing_entity",
                f"{base}.entity_id",
                f"asset {entry.id!r} references unknown entity {entry.entity_id!r}",
            )
        if entry.audio_request_id is not None and entry.audio_request_id not in audio_ids:
            err(
                "refs.missing_audio",
                f"{base}.audio_request_id",
                f"asset {entry.id!r} references unknown audio request {entry.audio_request_id!r}",
            )
        if not _PATH_RE.match(entry.path):
            err(
                "manifest.bad_path",
                f"{base}.path",
                f"asset {entry.id!r} path {entry.path!r} must be a res:// (or user://) "
                "resource path or an absolute filesystem path",
            )
            continue
        if check_files and project_root is not None and entry.path.startswith(("res://", "user://")):
            rel = entry.path.split("://", 1)[1]
            file_path = Path(project_root) / rel
            if not file_path.exists():
                err(
                    "manifest.missing_file",
                    f"{base}.path",
                    f"asset {entry.id!r} file does not exist: {file_path}",
                )

    # ------------------------------------------------------------------ #
    # Audio map references
    # ------------------------------------------------------------------ #
    for j, aid in enumerate(model.audio_map.ambient):
        if aid not in audio_ids:
            err(
                "refs.missing_audio",
                f"audio_map.ambient[{j}]",
                f"ambient layer {aid!r} is not a known AudioRequest id",
            )
    for i, zone in enumerate(model.audio_map.zones):
        base = f"audio_map.zones[{i}]"
        if zone.bgm_id is not None:
            if zone.bgm_id not in audio_ids:
                err(
                    "refs.missing_audio",
                    f"{base}.bgm_id",
                    f"zone {zone.id!r} references unknown audio id {zone.bgm_id!r}",
                )
            elif zone.bgm_id not in bgm_ids:
                err(
                    "refs.wrong_audio_type",
                    f"{base}.bgm_id",
                    f"zone {zone.id!r} bgm_id {zone.bgm_id!r} refers to an 'sfx' AudioRequest, not 'bgm'",
                )
        for j, sid in enumerate(zone.sfx_ids):
            if sid not in audio_ids:
                err(
                    "refs.missing_audio",
                    f"{base}.sfx_ids[{j}]",
                    f"zone {zone.id!r} references unknown sfx id {sid!r}",
                )

    # ------------------------------------------------------------------ #
    # Localization: every tr() key must exist for the default locale
    # ------------------------------------------------------------------ #
    table = model.localization_table
    default_locale = table.default_locale
    if not table.entries:
        # Backward compatibility (v1 IRs predate localization_table): an IR
        # without any locale data cannot be checked for tr() keys — record a
        # warning and skip the l10n section instead of failing every string.
        warn(
            "l10n.empty_locale",
            "localization_table.entries",
            f"localization table has no entries; {default_locale!r} tr() key "
            "checking skipped (v1-shaped IR?)",
        )
        return ValidationReport(errors=_dedupe(errors), warnings=_dedupe(warnings))
    if default_locale not in table.entries:
        warn(
            "l10n.empty_locale",
            "localization_table.default_locale",
            f"default locale {default_locale!r} has no entries in the localization table",
        )
    defined = table.keys_for(default_locale)

    def require_keys(keys: Iterable[tuple[str, str]], source: str) -> None:
        for path, key in keys:
            if key and key not in defined:
                err(
                    "l10n.missing_key",
                    path,
                    f"tr() key {key!r} used by {source} is not defined in "
                    f"localization_table.entries[{default_locale!r}]",
                )

    def condition_keys(obj: Any, path: str) -> list[tuple[str, str]]:
        """Extract tr() keys from a DialogueTree/QuestGraph ``conditions`` dict.

        Supported shapes (documented in the agent_schemas Phase 9 contract):
        ``{"text_key": ...}``, ``{"keys": [...]}`` and ``{key: display}``
        mappings whose values are plain strings.
        """
        out: list[tuple[str, str]] = []
        conds = getattr(obj, "conditions", None)
        if not isinstance(conds, dict):
            return out
        tk = conds.get("text_key")
        if isinstance(tk, str) and tk:
            out.append((f"{path}.conditions.text_key", tk))
        keys_field = conds.get("keys")
        if isinstance(keys_field, list):
            for j, k in enumerate(keys_field):
                if isinstance(k, str) and k:
                    out.append((f"{path}.conditions.keys[{j}]", k))
        for k, v in conds.items():
            if k in ("text_key", "keys"):
                continue
            if isinstance(v, str) and v:
                out.append((f"{path}.conditions", k))
        return out

    dialogue_keys: list[tuple[str, str]] = []
    for i, dlg in enumerate(model.dialogues):
        dialogue_keys.extend(condition_keys(dlg, f"dialogues[{i}]"))
        for j, node in enumerate(dlg.nodes):
            dialogue_keys.append((f"dialogues[{i}].nodes[{j}].text_key", node.text_key))
            for k, choice in enumerate(node.choices):
                dialogue_keys.append(
                    (f"dialogues[{i}].nodes[{j}].choices[{k}].text_key", choice.text_key)
                )
    require_keys(dialogue_keys, "dialogue trees")

    prompt_keys = [
        (f"entities[{i}].components.interactable.prompt_key", ent.components.interactable.prompt_key)
        for i, ent in enumerate(model.entities)
        if ent.components.interactable is not None
    ]
    require_keys(prompt_keys, "interact prompts")

    title_keys = [(f"quests[{i}].title", q.title) for i, q in enumerate(model.quests)]
    title_keys.extend(
        key for i, q in enumerate(model.quests) for key in condition_keys(q, f"quests[{i}]")
    )
    require_keys(title_keys, "quest titles and quest conditions")

    return ValidationReport(errors=_dedupe(errors), warnings=_dedupe(warnings))


# ====================================================================== #
# helpers
# ====================================================================== #


def _rooms(model: GameIR) -> list[tuple[str, Any]]:
    """Return [(stable room id, Room)] for the IR's level layout (empty if none)."""
    if model.level_layout is None:
        return []
    return [
        (room.id if room.id is not None else f"room_{idx}", room)
        for idx, room in enumerate(model.level_layout.rooms)
    ]


def _in_room(px: float, py: float, room: Any) -> bool:
    """Tile-space containment: room.x/y is the top-left corner, width/height span."""
    return (
        room.x <= px < room.x + room.width
        and room.y <= py < room.y + room.height
    )


def _find_cycle(deps: dict[str, list[str]]) -> Optional[list[str]]:
    """DFS over the quest-dependency graph; returns a cycle path if any."""
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {qid: WHITE for qid in deps}
    stack: list[str] = []

    def visit(node: str) -> Optional[list[str]]:
        color[node] = GRAY
        stack.append(node)
        for nxt in deps.get(node, []):
            if color.get(nxt, WHITE) == GRAY:
                start = stack.index(nxt)
                return stack[start:]
            if color.get(nxt, WHITE) == WHITE:
                found = visit(nxt)
                if found:
                    return found
        stack.pop()
        color[node] = BLACK
        return None

    for qid in deps:
        if color[qid] == WHITE:
            found = visit(qid)
            if found:
                return found
    return None
