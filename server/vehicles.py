"""Server-owned vehicle catalog and unlock policy."""

from dataclasses import dataclass

from .vehicle import VehicleConfig


@dataclass(frozen=True)
class VehicleDefinition:
    id: str
    unlock_level: int
    asset_id: str
    asset_url: str
    asset_bytes: int
    physics: VehicleConfig


VEHICLES: dict[str, VehicleDefinition] = {
    "car": VehicleDefinition(
        id="car",
        unlock_level=1,
        asset_id="car-kit/sedan.glb.bin",
        asset_url="/assets/car-kit/sedan.glb.bin",
        asset_bytes=24889,
        physics=VehicleConfig(),
    ),
    # Kept for accounts created by the previous profile implementation.
    "truck": VehicleDefinition(
        id="truck",
        unlock_level=3,
        asset_id="car-kit/sedan.glb.bin",
        asset_url="/assets/car-kit/sedan.glb.bin",
        asset_bytes=24889,
        physics=VehicleConfig(maxForwardSpeed=18.0, acceleration=3.5),
    ),
    # The asset is intentionally registered before the client model is added.
    "super-sedan": VehicleDefinition(
        id="super-sedan",
        unlock_level=3,
        asset_id="car-kit/super-sedan.glb.bin",
        asset_url="/assets/car-kit/super-sedan.glb.bin",
        asset_bytes=0,
        physics=VehicleConfig(
            maxForwardSpeed=27.0,
            acceleration=5.5,
            maxLateralAcceleration=9.0,
        ),
    ),
}


def vehicle_definition(vehicle_type: str) -> VehicleDefinition:
    try:
        return VEHICLES[vehicle_type]
    except KeyError as exc:
        raise ValueError(f"unsupported vehicle type: {vehicle_type}") from exc


def unlocked_vehicle_types(level: int) -> list[str]:
    return [
        definition.id
        for definition in VEHICLES.values()
        if definition.unlock_level <= level
    ]


def vehicle_profile(level: int) -> list[dict[str, object]]:
    return [
        {
            "id": definition.id,
            "unlockLevel": definition.unlock_level,
            "assetId": definition.asset_id,
            "unlocked": definition.unlock_level <= level,
        }
        for definition in VEHICLES.values()
    ]
