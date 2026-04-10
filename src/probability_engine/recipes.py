from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SimulationRecipe:
    recipe_name: str
    role: str
    innovation_layer: str
    volatility_layer: str
    dependency_layer: str
    jump_layer: str
    regime_layer: str
    estimation_basis: str
    dependency_scope: str
    path_count: int

    @classmethod
    def from_any(cls, value: "SimulationRecipe | dict[str, Any]") -> "SimulationRecipe":
        if isinstance(value, cls):
            return value
        payload = dict(value)
        recipe_name = str(payload.get("recipe_name", "")).strip()
        if recipe_name in RECIPE_REGISTRY:
            base = RECIPE_REGISTRY[recipe_name]
            payload = {**base.__dict__, **payload}
        return cls(
            recipe_name=str(payload.get("recipe_name", "")).strip(),
            role=str(payload.get("role", "")).strip(),
            innovation_layer=str(payload.get("innovation_layer", "")).strip(),
            volatility_layer=str(payload.get("volatility_layer", "")).strip(),
            dependency_layer=str(payload.get("dependency_layer", "")).strip(),
            jump_layer=str(payload.get("jump_layer", "")).strip(),
            regime_layer=str(payload.get("regime_layer", "")).strip(),
            estimation_basis=str(payload.get("estimation_basis", "")).strip(),
            dependency_scope=str(payload.get("dependency_scope", "")).strip(),
            path_count=int(payload.get("path_count", 0)),
        )


PRIMARY_RECIPE_V14 = SimulationRecipe(
    recipe_name="primary_daily_factor_garch_dcc_jump_regime_v1",
    role="primary",
    innovation_layer="student_t",
    volatility_layer="factor_and_product_garch",
    dependency_layer="factor_level_dcc",
    jump_layer="systemic_plus_idio",
    regime_layer="markov_regime",
    estimation_basis="daily_product_formal",
    dependency_scope="factor",
    path_count=4000,
)


RECIPE_REGISTRY: dict[str, SimulationRecipe] = {
    PRIMARY_RECIPE_V14.recipe_name: PRIMARY_RECIPE_V14,
}


def _matches_supported_primary_recipe(recipe: SimulationRecipe) -> bool:
    registered = RECIPE_REGISTRY.get(recipe.recipe_name)
    if registered is None:
        return False
    return (
        registered.role == "primary"
        and recipe.recipe_name == registered.recipe_name
        and recipe.role == registered.role
        and recipe.innovation_layer == registered.innovation_layer
        and recipe.volatility_layer == registered.volatility_layer
        and recipe.dependency_layer == registered.dependency_layer
        and recipe.jump_layer == registered.jump_layer
        and recipe.regime_layer == registered.regime_layer
        and recipe.estimation_basis == registered.estimation_basis
        and recipe.dependency_scope == registered.dependency_scope
        and int(recipe.path_count) > 0
    )


def resolve_recipes(values: list[Any] | None) -> list[SimulationRecipe]:
    if values is None:
        return [PRIMARY_RECIPE_V14]
    return [SimulationRecipe.from_any(item) for item in values]


def primary_recipe(recipes: list[SimulationRecipe]) -> SimulationRecipe:
    if not recipes:
        raise ValueError("Task 4 requires an explicit primary recipe when a recipes list is supplied")
    for recipe in recipes:
        if recipe.role == "primary":
            if not _matches_supported_primary_recipe(recipe):
                raise ValueError(
                    "Task 4 requires a supported formal daily primary recipe; "
                    f"got {recipe.recipe_name or '<unnamed>'}"
                )
            return recipe
    raise ValueError("Task 4 requires a primary recipe in the supplied recipes list")
