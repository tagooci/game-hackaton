# Assets

Sedan and colormap: Kenney, [Car Kit 3.1](https://kenney.nl/assets/car-kit), [CC0](https://creativecommons.org/publicdomain/zero/1.0/).
Original license: `client/public/assets/car-kit/License.txt`.

Ambient world traffic vehicles: sedan, sports sedan, SUV, taxi, van, truck,
ambulance, police car and fire truck from Kenney, [Car Kit 3.1](https://kenney.nl/assets/car-kit), CC0.
The supplied archive does not include a bus model. Files and original license:
`client/public/assets/traffic/`.

Road geometry and signs: Kenney, [City Kit Roads](https://kenney.nl/assets/city-kit-roads), CC0.
Optimized reference vehicles: Kenney Car Kit, CC0.
Original licenses: `client/public/content/assets/environment/License.txt` and
`client/public/content/assets/vehicles/License.txt`.
Map and loader imported from this repository's `frontend` commit `579ca27`.

Railway track: Kenney, [Train Kit](https://kenney.nl/assets/train-kit), CC0.
Archive mirror: [OpenGameArt](https://opengameart.org/sites/default/files/kenney_train-kit_0.zip).
Original license: `client/public/content/assets/railway/License.txt`.
Road ramps and level crossings derive from City Kit Roads.
Tunnel sections, bus shelters, crossing signs and inset rails are generated locally
by `client/scripts/build-road-props.py`; no third-party models are used for them.

Current imported map: user-provided `blender/compact-reference.blend` and its JSON graph.
Kenney models supplied locally from `Downloads/kenney_city-kit-roads/Models/GLB format`.
Imported runtime models: `client/public/content/assets/imported/` (CC0 Kenney geometry
and project-authored decks/supports). License: `assets/imported/License.txt`.

City dressing in blender/compact-city.blend: original houses, trees and benches from user-provided LowPoly_City_01Readyblender.rar; original palette supplied in textures.rar. The local archive is tracked separately from the user-provided CartoCity reference URL; archive authorship/license was not supplied. Geometry was oriented and uniformly scaled; original UV colors are preserved.

## LowPoly City environment

Buildings, trees and benches: user-provided `LowPoly_City_01Readyblender.rar` and `textures.rar`. License information was not included in the archives. Runtime models use vertex colors and shared prototypes; no CC0 status is assumed.

## Scenario road signs

Priority and yield sign models: Keet, [Dodecagon Traffic Signs](https://dodecagon.nl/dodecagontrafficsigns), CC0 1.0 Universal. Imported OBJ geometry and supplied sign textures, scaled to 2.8 m; materials made matte.
