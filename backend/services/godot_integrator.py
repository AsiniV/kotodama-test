"""
GodotIntegrator — ЭТАП 3: сборщик проекта Godot 4.3 из Game IR и ассетов.

Архитектура "шаблон + контент":
- Шаблон (godot_core/) — неизменяемая база: контроллеры, камера, UI,
  система квестов, аудио-менеджер. Интегратор НЕ переписывает движок.
- Контент генерируется из Game IR: уровни, NPC, диалоги, квесты, ассеты.

Интегратор:
1. Копирует immutable core (godot_core) в workspace/{game_id}/godot_project
2. Копирует ассеты (спрайты .png, SFX .wav, BGM .ogg) в res://assets/
3. Генерирует data-файлы (quests.json, dialogues.json, entities.json)
4. Генерирует сцены уровней (.tscn, текстовый формат Godot 4.x)
5. Генерирует per-entity скрипты (.gd) и регистрирует их в scene_groups.gd
6. Регистрирует AudioManager autoload и обновляет project.godot

Всё это детерминированный Python-код (f-string шаблоны), а не LLM.
"""

import json
import re
import shutil
from pathlib import Path
from typing import Dict, List, Optional

from backend.core.config import get_settings
from backend.schemas.agent_schemas import AudioRequest, EntityRequest, GameIR

settings = get_settings()

# Неэкранированные идентификаторы узлов допустимы только из [A-Za-z0-9_],
# узел не может называться одним из служебных имён базового шаблона.
_RESERVED_NODE_NAMES = {"MainLevel", "Player", "World", "UI", "Modules"}


def _sanitize_node_name(raw: str, prefix: str = "e") -> str:
    """Превращает произвольный ID сущности в валидное имя узла Godot."""
    name = re.sub(r"[^A-Za-z0-9_]", "_", raw)
    if not name or not (name[0].isalpha() or name[0] == "_"):
        name = f"{prefix}_{name}"
    if name in _RESERVED_NODE_NAMES:
        name = f"{prefix}_{name}"
    return name[:80]


class GodotIntegrator:
    """Собирает проект Godot 4.3 из Game IR и сгенерированных ассетов.

    Работает по принципу: immutable core + generated content.
    """

    def __init__(self, game_id: str, game_ir: GameIR):
        self.game_id = game_id
        self.ir = game_ir
        self.workspace_root = Path(settings.workspace_root) / game_id
        self.godot_core_path = self._resolve_godot_core_path()
        self.output_path = self.workspace_root / "godot_project"

        # id AudioRequest -> путь к файлу спрайта/audio внутри проекта (res://...)
        self.sprite_map: Dict[str, str] = {}   # entity sprite stem -> res path
        self.bgm_files: List[str] = []         # имена .ogg файлов
        self.sfx_files: List[str] = []         # имена .wav файлов

        self._create_directory_structure()

    @staticmethod
    def _resolve_godot_core_path() -> Path:
        """Ищет immutable шаблон godot_core в типовых расположениях."""
        candidates = [
            Path("/app/godot_core"),
            Path(__file__).resolve().parents[2] / "godot_core",
            Path.cwd() / "godot_core",
        ]
        for c in candidates:
            if c.is_dir():
                return c
        return candidates[0]  # дадим _copy_godot_core поднять понятную ошибку

    # ------------------------------------------------------------------
    # Структура папок
    # ------------------------------------------------------------------
    def _create_directory_structure(self):
        """Создаёт структуру папок проекта Godot."""
        dirs = [
            self.output_path / "assets" / "sprites",
            self.output_path / "assets" / "audio",
            self.output_path / "assets" / "music",
            self.output_path / "scenes" / "levels",
            self.output_path / "scenes" / "entities",
            self.output_path / "scripts" / "entities",
            self.output_path / "scripts" / "systems",
            self.output_path / "data",  # JSON-файлы (квесты, диалоги, entities)
        ]
        for d in dirs:
            d.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Точка входа
    # ------------------------------------------------------------------
    def integrate(self) -> str:
        """Главный метод: собирает весь проект.

        Возвращает путь к готовому проекту Godot.
        """
        print(f"🔧 Starting Godot integration for game: {self.game_id}")

        # 1. Копируем immutable core
        self._copy_godot_core()

        # 2. Копируем ассеты (спрайты, звук)
        self._copy_assets()

        # 3. Генерируем данные (квесты, диалоги, entities)
        self._generate_data_files()

        # 4. Генерируем сцены уровней
        self._generate_level_scenes()

        # 5. Генерируем скрипты для специфичной логики
        self._generate_custom_scripts()

        # 6. Обновляем project.godot
        self._update_project_settings()

        print(f"✅ Godot project assembled at: {self.output_path}")
        return str(self.output_path)

    # ------------------------------------------------------------------
    # Шаг 1: immutable core
    # ------------------------------------------------------------------
    def _copy_godot_core(self):
        """Копирует immutable core (шаблон) в output."""
        if not self.godot_core_path.exists():
            raise FileNotFoundError(
                f"Godot core template not found at {self.godot_core_path}"
            )

        # Копируем всё, кроме .import файлов (Godot сгенерирует их сам)
        for item in self.godot_core_path.iterdir():
            dest = self.output_path / item.name
            if item.is_dir():
                shutil.copytree(
                    item, dest, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("*.import", "__pycache__"),
                )
            else:
                shutil.copy2(item, dest)

    # ------------------------------------------------------------------
    # Шаг 2: ассеты
    # ------------------------------------------------------------------
    def _find_assets_root(self) -> Path:
        """Определяет корень ассетов: workspace/{game_id}/assets или
        legacy layout /app/workspace/{game_id}/assets (см. /generate-audio)."""
        candidates = [
            self.workspace_root / "assets",
            Path("/app/workspace") / self.game_id / "assets",
        ]
        for c in candidates:
            if c.exists():
                return c
        return candidates[0]

    def _copy_assets(self):
        """Копирует ассеты из workspace (или MinIO-кэша) в проект Godot."""
        assets_src = self._find_assets_root()

        # Спрайты (.png)
        sprites_src = assets_src / "sprites"
        if sprites_src.exists():
            for file in sorted(sprites_src.glob("*.png")):
                dest = self.output_path / "assets" / "sprites" / file.name
                shutil.copy2(file, dest)
                self.sprite_map[file.stem] = f"res://assets/sprites/{file.name}"

        # Звуковые эффекты (.wav) — Godot предпочитает WAV для коротких SFX
        for audio_dir in (assets_src / "audio", assets_src / "sfx"):
            if audio_dir.exists():
                for file in sorted(audio_dir.glob("*.wav")):
                    dest = self.output_path / "assets" / "audio" / file.name
                    shutil.copy2(file, dest)
                    self.sfx_files.append(file.name)

        # Музыка (.ogg) — Godot предпочитает OGG для BGM
        for music_dir in (assets_src / "music", assets_src / "bgm"):
            if music_dir.exists():
                for file in sorted(music_dir.glob("*.ogg")):
                    dest = self.output_path / "assets" / "music" / file.name
                    shutil.copy2(file, dest)
                    self.bgm_files.append(file.name)

        print(
            f"📦 Assets copied: {len(self.sprite_map)} sprites, "
            f"{len(self.sfx_files)} sfx, {len(self.bgm_files)} bgm"
        )

    # ------------------------------------------------------------------
    # Шаг 3: data-файлы
    # ------------------------------------------------------------------
    def _generate_data_files(self):
        """Генерирует JSON-файлы с данными игры (квесты, диалоги, entities)."""
        data_dir = self.output_path / "data"

        if self.ir.quests:
            quests_data = {"quests": [q.model_dump(mode="json") for q in self.ir.quests]}
            self._write_json(data_dir / "quests.json", quests_data)

        if self.ir.dialogues:
            dialogues_data = {
                "dialogues": [d.model_dump(mode="json") for d in self.ir.dialogues]
            }
            self._write_json(data_dir / "dialogues.json", dialogues_data)

        if self.ir.entities:
            entities_data = {
                "entities": [e.model_dump(mode="json") for e in self.ir.entities]
            }
            self._write_json(data_dir / "entities.json", entities_data)

        if self.ir.audio_requests:
            audio_data = {
                "audio_requests": [a.model_dump(mode="json") for a in self.ir.audio_requests]
            }
            self._write_json(data_dir / "audio.json", audio_data)

        if self.ir.level_layout is not None:
            self._write_json(
                data_dir / "level_layout.json",
                self.ir.level_layout.model_dump(mode="json"),
            )

    @staticmethod
    def _write_json(path: Path, payload: dict):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)

    # ------------------------------------------------------------------
    # Вспомогательные методы для сцен
    # ------------------------------------------------------------------
    def _entity_sprite(self, entity: EntityRequest) -> Optional[str]:
        """Возвращает res:// путь к спрайту сущности, если файл реально скопирован."""
        stem = entity.sprite or entity.id
        return self.sprite_map.get(stem)

    def _entity_script_rel(self, safe_id: str) -> str:
        """Относительный путь к per-entity скрипту (для .tscn)."""
        return f"scripts/entities/{safe_id}.gd"

    def _entity_script_res(self, safe_id: str) -> str:
        return f"res://scripts/entities/{safe_id}.gd"

    def _entity_sfx_paths(self, entity: EntityRequest) -> List[str]:
        """Res-пути к wav-эффектам, привязанным к сущности через sfx_ids."""
        paths = []
        for sfx_id in entity.sfx_ids:
            fname = f"{sfx_id}.wav"
            if fname in self.sfx_files:
                paths.append(f"res://assets/audio/{fname}")
        return paths

    # ------------------------------------------------------------------
    # Шаг 4: сцена уровня (.tscn)
    # ------------------------------------------------------------------
    def _generate_level_scenes(self):
        """Генерирует .tscn файлы для уровней."""
        level_scene = self._create_level_tscn()
        out = self.output_path / "scenes" / "levels" / "main_level.tscn"
        with open(out, "w", encoding="utf-8") as f:
            f.write(level_scene)

    def _create_level_tscn(self) -> str:
        """Генерирует .tscn файл уровня.

        Godot 4.x формат: текстовое представление сцены.
        - [ext_resource] объявляет внешние ресурсы (текстуры, скрипты);
        - [node] создаёт узлы; ExtResource("id") ссылается на ресурс по ID.
        IDs уникальны в пределах файла; load_steps = число ext-ресурсов + 1.
        Файл собирается целиком в конце — сначала собираются все данные.
        """
        player_entities = [e for e in self.ir.entities if e.type == "player"]
        world_entities = [e for e in self.ir.entities if e.type != "player"]

        ext_lines: List[str] = []
        counter: Dict[str, int] = {"n": 0}

        def add_ext(res_type: str, path: str, id_str: str) -> str:
            counter["n"] += 1
            ext_lines.append(
                f'[ext_resource type="{res_type}" path="{path}" id="{id_str}"]'
            )
            return id_str

        # --- игрок: спрайт + скрипт + SFX-плееры ---
        player = player_entities[0] if player_entities else None
        player_tex_id = player_scr_id = None
        player_sfx_ids: List[tuple] = []  # (ext_id, node_name)
        if player is not None:
            pid = _sanitize_node_name(player.id, prefix="p")
            sprite = self._entity_sprite(player)
            if sprite:
                player_tex_id = add_ext("Texture2D", sprite, f"1_player_tex_{pid}")
            player_scr_id = add_ext("Script", self._entity_script_rel(pid), f"2_player_scr_{pid}")
            for j, sfx_path in enumerate(self._entity_sfx_paths(player)):
                sid = add_ext("AudioStream", sfx_path, f"3_psj{j}_{pid}")
                player_sfx_ids.append((sid, f"Sfx{j}"))

        # --- world-сущности: спрайт + скрипт + SFX-плееры ---
        entity_ext: List[Dict] = []
        for entity in world_entities:
            safe_id = _sanitize_node_name(entity.id)
            info = {
                "entity": entity,
                "safe_id": safe_id,
                "texture": None,
                "script": None,
                "sfx": [],
            }
            sprite = self._entity_sprite(entity)
            if sprite:
                info["texture"] = add_ext("Texture2D", sprite, f"tex_{safe_id}")
            info["script"] = add_ext("Script", self._entity_script_rel(safe_id), f"scr_{safe_id}")
            for k, sfx_path in enumerate(self._entity_sfx_paths(entity)):
                sid = add_ext("AudioStream", sfx_path, f"sfx_{safe_id}_{k}")
                info["sfx"].append((sid, f"Sfx{k}"))
            entity_ext.append(info)

        # --- фон (background.png из арт-пайплайна), если существует ---
        background_id = None
        bg = self.sprite_map.get("background")
        if bg:
            background_id = add_ext("Texture2D", bg, "1_background")

        load_steps = len(ext_lines) + 1
        uid = re.sub(r"[^a-z0-9_]", "_", self.game_id.lower())

        t = f'[gd_scene load_steps={load_steps} format=3 uid="uid://{uid}_main"]\n\n'
        t += "\n".join(ext_lines)
        t += "\n\n"

        # --- корневой узел ---
        t += '[node name="MainLevel" type="Node2D"]\n\n'

        # --- фон ---
        if background_id:
            t += '[node name="Background" type="Sprite2D" parent="."]\nz_index = -10\n'
            t += f'texture = ExtResource("{background_id}")\n\n'

        # --- мир ---
        t += '[node name="World" type="Node2D" parent="."]\n\n'

        # --- игрок ---
        if player is not None:
            x = player.position_x if player.position_x is not None else 100
            y = player.position_y if player.position_y is not None else 100
            t += '[node name="Player" type="Sprite2D" parent="World" groups=["player"]]\n'
            if player_tex_id:
                t += f'texture = ExtResource("{player_tex_id}")\n'
            if player_scr_id:
                t += f'script = ExtResource("{player_scr_id}")\n'
            t += f'position = Vector2({x}, {y})\n'
            t += 'metadata/entity_id = "%s"\n\n' % player.id

            # дочерние AudioStreamPlayer2D для SFX игрока
            for sid, node_name in player_sfx_ids:
                t += f'[node name="{node_name}" type="AudioStreamPlayer2D" parent="World/Player"]\n'
                t += f'stream = ExtResource("{sid}")\n\n'

        # --- world-сущности ---
        for info in entity_ext:
            entity = info["entity"]
            safe_id = info["safe_id"]
            x = entity.position_x if entity.position_x is not None else 100
            y = entity.position_y if entity.position_y is not None else 100
            t += f'[node name="{safe_id}" type="Sprite2D" parent="World"]\n'
            if info["texture"]:
                t += f'texture = ExtResource("{info["texture"]}")\n'
            t += f'script = ExtResource("{info["script"]}")\n'
            t += f'position = Vector2({x}, {y})\n'
            t += 'metadata/entity_id = "%s"\n' % entity.id
            t += 'metadata/entity_type = "%s"\n\n' % entity.type
            for sid, node_name in info["sfx"]:
                t += f'[node name="{node_name}" type="AudioStreamPlayer2D" parent="World/{safe_id}"]\n'
                t += f'stream = ExtResource("{sid}")\n\n'

        return t

    # ------------------------------------------------------------------
    # Шаг 5: скрипты
    # ------------------------------------------------------------------
    def _generate_custom_scripts(self):
        """Генерирует .gd скрипты для специфичной логики."""
        # Level Manager (загрузка данных, инициализация)
        level_mgr_script = self._create_level_manager_gd()
        with open(self.output_path / "scripts" / "systems" / "level_manager.gd",
                  "w", encoding="utf-8") as f:
            f.write(level_mgr_script)

        # Per-entity скрипты (диалоги, SFX)
        for entity in self.ir.entities:
            safe_id = _sanitize_node_name(entity.id)
            script = self._create_entity_script_gd(entity, safe_id)
            with open(self.output_path / "scripts" / "entities" / f"{safe_id}.gd",
                      "w", encoding="utf-8") as f:
                f.write(script)

        # Audio Manager (подключение сгенерированной музыки/звуков)
        if self.ir.audio_requests or self.bgm_files or self.sfx_files:
            audio_script = self._create_audio_manager_gd()
            with open(self.output_path / "scripts" / "systems" / "audio_manager.gd",
                      "w", encoding="utf-8") as f:
                f.write(audio_script)

        # Регистрация сущностей в scene_groups.gd (не переписывая движок,
        # а дополняя существующий реестр)
        self._register_entities_in_scene_groups()

    def _create_level_manager_gd(self) -> str:
        """Генерирует GDScript для управления уровнем."""
        return '''extends Node2D
## Level manager: загружает data-файлы (quests/dialogues/entities/audio),
## сгенерированные GodotIntegrator, и инициализирует аудио-менеджер.

var quest_data: Array = []
var dialogue_data: Array = []
var entity_data: Array = []
var audio_data: Array = []

func _ready() -> void:
\tprint("[LevelManager] MainLevel loaded")
\t_load_game_data()
\t_spawn_entities()
\t_start_bgm()

func _load_game_data() -> void:
\tquest_data = _read_json_array("res://data/quests.json", "quests")
\tdialogue_data = _read_json_array("res://data/dialogues.json", "dialogues")
\tentity_data = _read_json_array("res://data/entities.json", "entities")
\taudio_data = _read_json_array("res://data/audio.json", "audio_requests")
\tprint("[LevelManager] quests=%d dialogues=%d entities=%d audio=%d" % [
\t\tquest_data.size(), dialogue_data.size(), entity_data.size(), audio_data.size()])

func _read_json_array(path: String, root_key: String) -> Array:
\tif not FileAccess.file_exists(path):
\t\treturn []
\tvar text := FileAccess.get_file_as_string(path)
\tvar parsed = JSON.parse_string(text)
\tif typeof(parsed) == TYPE_DICTIONARY and parsed.has(root_key):
\t\treturn parsed[root_key]
\treturn []

func _spawn_entities() -> void:
\t# Entities уже размещены интегратором как статические узлы main_level.tscn.
\t# Динамический спавн включается здесь при необходимости (например, враги из
\t# level_layout.json enemy_spawn_points).
\tpass

func _start_bgm() -> void:
\t# AudioManager регистрируется интегратором как autoload "AudioSystem"
\tvar audio_system := get_node_or_null("/root/AudioSystem")
\tif audio_system and audio_system.has_method("play_first_bgm"):
\t\taudio_system.play_first_bgm()
'''

    def _create_entity_script_gd(self, entity: EntityRequest, safe_id: str) -> str:
        """Генерирует per-entity .gd скрипт: диалог по interact + проигрывание SFX.

        Детерминированный шаблон (не LLM). Интерактивные NPC добавляются в
        группу "interactable", хранят dialogue_id и через SignalBus поднимают
        module_dialogue_started; сущности с SFX вызывают play_sfx().
        """
        sfx_paths = self._entity_sfx_paths(entity)
        lines: List[str] = []
        lines.append("extends Sprite2D")
        lines.append(f'## Автогенерация GodotIntegrator: сущность "{entity.id}" ({entity.type}).')
        lines.append(f'const ENTITY_ID := "{entity.id}"')
        lines.append(f'const ENTITY_TYPE := "{entity.type}"')
        if entity.dialogue_id:
            lines.append(f'const DIALOGUE_ID := "{entity.dialogue_id}"')
        lines.append("")
        lines.append("func _ready() -> void:")
        has_ready_stmt = False
        if entity.type in ("npc", "item", "decoration") and entity.dialogue_id:
            lines.append('\tadd_to_group("interactable")')
            has_ready_stmt = True
        if sfx_paths:
            lines.append('\tadd_to_group("has_sfx")')
            has_ready_stmt = True
        if not has_ready_stmt:
            lines.append("\tpass")
        lines.append("")
        if entity.dialogue_id and entity.type in ("npc", "item", "decoration"):
            lines.append("func interact(player: Node) -> void:")
            lines.append('\tif SignalBus and SignalBus.has_method("emit_module_signal"):')
            lines.append('\t\tSignalBus.emit_module_signal("dialogue_started", [DIALOGUE_ID, ENTITY_ID])')
            lines.append("")
        if sfx_paths:
            lines.append("func play_sfx(index: int = 0) -> void:")
            lines.append("\tmatch index:")
            for i, sp in enumerate(sfx_paths):
                lines.append(f"\t\t{i}:")
                lines.append(f"\t\t\t_play_stream(\"{sp}\")")
            lines.append("\t\t_:")
            lines.append("\t\t\t_play_stream(\"%s\")" % sfx_paths[0])
            lines.append("")
            lines.append("func _play_stream(stream_path: String) -> void:")
            lines.append("\tfor child in get_children():")
            lines.append("\t\tif child is AudioStreamPlayer2D and child.stream:")
            lines.append("\t\t\tif child.stream.resource_path == stream_path:")
            lines.append("\t\t\t\tchild.play()")
            lines.append("\t\t\t\treturn")
            lines.append("\t# Fallback: динамический плеер")
            lines.append("\tvar player := AudioStreamPlayer2D.new()")
            lines.append("\tplayer.stream = load(stream_path)")
            lines.append("\tadd_child(player)")
            lines.append("\tplayer.play()")
            lines.append("")
        return "\n".join(lines) + "\n"

    def _create_audio_manager_gd(self) -> str:
        """Генерирует GDScript AudioManager (autoload AudioSystem).

        Управляет BGM (.ogg) и SFX (.wav), подхватывая файлы, скопированные
        интегратором в res://assets/.
        """
        bgm_requests = [a for a in self.ir.audio_requests if a.type == "bgm"]

        script = '''extends Node
## AudioSystem — автогенерированный GodotIntegrator аудио-менеджер.
## Проигрывает BGM (OGG) и предоставляет play_sfx() для SFX (WAV).

var bgm_players: Dictionary = {}
var current_bgm: String = ""
var sfx_pool: Array[AudioStreamPlayer] = []

const BGM_TRACKS := [
'''
        # Список BGM-треков: сначала из IR, затем найденные файлы без записи в IR
        seen = set()
        for req in bgm_requests:
            fname = f"{req.id}.ogg"
            if fname in self.bgm_files or req.id in {Path(n).stem for n in self.bgm_files}:
                loop = "true" if req.loop else "false"
                script += f'\t{{"id": "{req.id}", "path": "res://assets/music/{fname}", "loop": {loop}}},\n'
                seen.add(fname)
        for fname in self.bgm_files:
            if fname not in seen:
                script += f'\t{{"id": "{Path(fname).stem}", "path": "res://assets/music/{fname}", "loop": true}},\n'
        script += ''']

const SFX_PATHS := [
'''
        for fname in self.sfx_files:
            script += f'\t"res://assets/audio/{fname}",\n'
        script += ''']

func _ready() -> void:
\tfor i in range(8):
\t\tvar p := AudioStreamPlayer.new()
\t\tp.bus = "Master"
\t\tadd_child(p)
\t\tsfx_pool.append(p)

func play_bgm(bgm_id: String) -> void:
\tstop_bgm()
\tfor track in BGM_TRACKS:
\t\tif track["id"] == bgm_id and ResourceLoader.exists(track["path"]):
\t\t\tvar stream: AudioStream = load(track["path"])
\t\t\tif track["loop"] and stream is AudioStreamOggVorbis:
\t\t\t\tstream.loop = true
\t\t\tvar player := AudioStreamPlayer.new()
\t\t\tplayer.stream = stream
\t\t\tplayer.bus = "Master"
\t\t\tplayer.volume_db = -10.0
\t\t\tadd_child(player)
\t\t\tplayer.play()
\t\t\tbgm_players[bgm_id] = player
\t\t\tcurrent_bgm = bgm_id
\t\t\tprint("[AudioSystem] Playing BGM: ", bgm_id)
\t\t\treturn
\tprint("[AudioSystem] BGM not found: ", bgm_id)

func play_first_bgm() -> void:
\tif not BGM_TRACKS.is_empty():
\t\tplay_bgm(BGM_TRACKS[0]["id"])

func stop_bgm() -> void:
\tfor id in bgm_players.keys():
\t\tvar p = bgm_players[id]
\t\tp.stop()
\t\tp.queue_free()
\tbgm_players.clear()
\tcurrent_bgm = ""

func play_sfx(path_or_id: String) -> void:
\tvar path := path_or_id
\tif not path.ends_with(".wav") and not path.begins_with("res://"):
\t\tpath = "res://assets/audio/" + path_or_id + ".wav"
\telif not path.begins_with("res://"):
\t\tpath = "res://assets/audio/" + path_or_id
\tif not ResourceLoader.exists(path):
\t\tprint("[AudioSystem] SFX not found: ", path)
\t\treturn
\tfor p in sfx_pool:
\t\tif not p.playing:
\t\t\tp.stream = load(path)
\t\t\tp.play()
\t\t\treturn
'''
        return script

    def _register_entities_in_scene_groups(self):
        """Дополняет scene_groups.gd ядром, регистрируя сгенерированные группы.

        Если файла нет — создаёт минимальный реестр. Это аддитивная операция:
        движок не переписывается, добавляется только блок GENERATED.
        """
        sg_path = self.output_path / "scripts" / "core" / "scene_groups.gd"
        existing = sg_path.read_text(encoding="utf-8") if sg_path.exists() else ""

        generated_block = (
            "# === GENERATED by GodotIntegrator (block between markers) ===\n"
            "const GROUP_PLAYER := \"player\"\n"
            "const GROUP_HAS_SFX := \"has_sfx\"\n"
        )
        for entity in self.ir.entities:
            const_name = f"GROUP_{_sanitize_node_name(entity.id).upper()}"
            generated_block += f"const {const_name} := \"{_sanitize_node_name(entity.id)}\"\n"
        generated_block += "# === END GENERATED ===\n"

        marker_re = re.compile(
            r"# === GENERATED by GodotIntegrator.*# === END GENERATED ===\n?",
            re.DOTALL,
        )
        if marker_re.search(existing):
            new_content = marker_re.sub(generated_block, existing)
        elif existing.strip():
            new_content = existing.rstrip() + "\n\n" + generated_block
        else:
            new_content = "extends Node\n## Scene group registry.\n\n" + generated_block

        sg_path.write_text(new_content, encoding="utf-8")

    # ------------------------------------------------------------------
    # Шаг 6: project.godot
    # ------------------------------------------------------------------
    def _update_project_settings(self):
        """Обновляет project.godot: main scene, AudioManager autoload, аудио."""
        project_file = self.output_path / "project.godot"

        if project_file.exists():
            content = project_file.read_text(encoding="utf-8")
        else:
            content = 'config_version=5\n'

        # Главная сцена → собранный уровень (заменяем или добавляем в [application])
        main_scene_line = 'run/main_scene="res://scenes/levels/main_level.tscn"'
        if "run/main_scene=" in content:
            content = re.sub(
                r'run/main_scene=.*', main_scene_line, content, count=1
            )
        elif "[application]" in content:
            content = content.replace(
                "[application]", "[application]\n" + main_scene_line, 1
            )
        else:
            content += f"\n[application]\n{main_scene_line}\n"

        # Autoload AudioSystem (только если сгенерирован audio_manager.gd)
        audio_manager_res = "res://scripts/systems/audio_manager.gd"
        if (self.output_path / "scripts" / "systems" / "audio_manager.gd").exists():
            if "AudioSystem=" not in content:
                if "[autoload]" in content:
                    content = content.replace(
                        "[autoload]",
                        f'[autoload]\nAudioSystem="*{audio_manager_res}"',
                        1,
                    )
                else:
                    content += (
                        "\n[autoload]\n\n"
                        f'AudioSystem="*{audio_manager_res}"\n'
                    )

        # Секция audio (только если отсутствует — не трогаем настройки ядра)
        if "[audio]" not in content:
            content += "\n[audio]\n\n"

        project_file.write_text(content, encoding="utf-8")


# ============================================================================
# Функция для вызова из API
# ============================================================================
def integrate_godot_project(game_id: str, game_ir: GameIR) -> str:
    """Точка входа для API. Возвращает путь к готовому проекту Godot."""
    integrator = GodotIntegrator(game_id, game_ir)
    return integrator.integrate()
