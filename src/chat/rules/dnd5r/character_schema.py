"""Minimum D&D revised/2024 character schema used by import drafts."""

from __future__ import annotations

from src.trpg.schemas import CharacterFieldDefinition, CharacterSchema


DND5R_CHARACTER_SCHEMA = CharacterSchema(
    ruleset_key="dnd5r",
    version=1,
    fields=(
        CharacterFieldDefinition(
            "identity.name",
            "string",
            required=True,
            aliases=("角色名", "人物名", "姓名", "name"),
        ),
        CharacterFieldDefinition(
            "identity.species",
            "string",
            aliases=("种族", "species"),
        ),
        CharacterFieldDefinition(
            "identity.background",
            "string",
            aliases=("背景", "background"),
        ),
        CharacterFieldDefinition(
            "progression.primary_class",
            "string",
            aliases=("职业", "主职业", "class"),
        ),
        CharacterFieldDefinition(
            "progression.total_level",
            "integer",
            aliases=("等级", "总等级", "level"),
            recommended_minimum=1,
            recommended_maximum=20,
        ),
        CharacterFieldDefinition(
            "proficiency_bonus",
            "integer",
            aliases=("熟练", "熟练加值", "proficiency bonus"),
        ),
        *tuple(
            CharacterFieldDefinition(
                f"abilities.{ability}",
                "integer",
                aliases=(alias,),
                recommended_minimum=1,
                recommended_maximum=30,
            )
            for ability, alias in (
                ("strength", "力量"),
                ("dexterity", "敏捷"),
                ("constitution", "体质"),
                ("intelligence", "智力"),
                ("wisdom", "感知"),
                ("charisma", "魅力"),
            )
        ),
        CharacterFieldDefinition(
            "combat.hit_points.current", "integer", aliases=("当前生命",)
        ),
        CharacterFieldDefinition(
            "combat.hit_points.maximum", "integer", aliases=("最大生命",)
        ),
        CharacterFieldDefinition(
            "combat.hit_points.temporary", "integer", aliases=("临时生命",)
        ),
        CharacterFieldDefinition(
            "combat.armor_class", "integer", aliases=("护甲等级 AC",)
        ),
        CharacterFieldDefinition(
            "combat.initiative", "integer", aliases=("先攻",)
        ),
        CharacterFieldDefinition(
            "combat.speed", "integer", aliases=("速度",)
        ),
        CharacterFieldDefinition(
            "combat.spell_save_dc", "integer", aliases=("法术豁免 DC",)
        ),
        CharacterFieldDefinition(
            "senses.passive_perception", "integer", aliases=("被动察觉",)
        ),
    ),
)


__all__ = ["DND5R_CHARACTER_SCHEMA"]
