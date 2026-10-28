# External assets and reproducibility

2026-10-28. The owner selected a **source-only publication**. The source packages,
tests, examples and documentation may be published while the complete Scene v8
package remains local. Unresolved asset redistribution provenance blocks inclusion
of those assets, not publication of the reviewed source.

## Required v8 package

The tested Scene is `scene2-final-contact-review-20261014-932c8f2e / scene-v8-native`,
Manifest SHA `64bff80050a883880e7e6363dd3e5b2f517fd72bb96743e3e529c89a2dfaa3c9`.
The local package is under
`docs/evidence/e01-v8-collision/runspace/relocated/scene-v8-native/`.
It contains **84 Manifest entries, 185,944,113 bytes**, plus its Manifest file.
The inventory records all entries and their supplied SHA-256 values:
[scene-asset-inventory.csv](scene-asset-inventory.csv).

| Required component | Purpose / publication status |
|---|---|
| `scene.json`, `calibration.json`, `provenance.json`, `manifest.json` | Scene identity, frames, binding, provenance and integrity. Excluded with the private package; do not invent replacement calibration. |
| `scene.usda` (84,902,150 bytes) | Exported native scene, including geometry. Derived from assets whose complete redistribution provenance is not established. |
| `scene.xml` (109,022 bytes) | Exported MJCF. Its existence does not replace robot URDF/mesh/physics dependencies. |
| Robot URDF, STL, execution USD layers | Kinematics, visuals, articulation and physics; exact upstream asset revisions and modification/redistribution records are unresolved. |
| Finger convex parts (2,728,123 bytes), pad JSON (2,256 bytes) | Required collision closure; preserve original transforms/material/bindings. Derived geometry provenance requires review too. |
| Object OBJ/PNG, profile/physics/task parameters | Required visual/numeric inputs. Scan/texture ownership and exact licensed source records have not been established. |
| Three NVIDIA OmniPBR MDL files | Each retains an explicit source/binary redistribution notice. This clears only those files' notice requirement, not the whole package. |
| Historical `.source` evidence | Required by current Manifest/Calibration relations; removing it would break the validated package contract. |

Required assets were not rejected merely for being binary. No partial Scene was
copied into a public `assets/` directory and no package references were rewritten.
The current package uses internal relative asset/layer/mesh references and still
passes the existing Scene contract's Manifest/hash/binding validation. Historical
source paths in provenance are not runtime substitutes for missing package files.

## Size and licensing decision

The largest file is about **80.969MiB**. GitHub warns above50MiB and blocks files
larger than100MiB in ordinary Git; size alone does not force LFS for this file.
See [GitHub file limits](https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-large-files-on-github).
Git LFS3.0.2 is installed locally, but this preparation does not enable LFS,
purchase/assume quota, or upload assets without redistribution clearance.

The SO-ARM upstream repository has a published
[license](https://github.com/TheRobotStudio/SO-ARM100/blob/main/LICENSE).
The local package has no asset license/notice manifest tying every mesh, derived
USD, scan and texture to that particular licensed source/revision. Similar names
are insufficient evidence. Neither a GitHub repository's visibility nor a local
asset hash grants redistribution rights.

Before including this package, establish ownership/licensed revision and required
attribution/change notices for robot assets and derivatives, and publication
permission for local scans/textures/calibration evidence. Keep the package's
closure and current identity intact. The owner explicitly authorized publishing
the source while requiring privately supplied Scene assets. No asset permission
is inferred from that authorization and no local asset is deleted or modified.

## What a clone would and would not provide

The source-only Git payload contains three Python packages, tests, SPECs, architecture,
interfaces, history reports, and adapted Recipe/config examples. It excludes local
SDK/Conda/Qt installations, v8 Scene, historical B fixtures, videos, HDF5/Parquet,
checkpoints and pretrained caches.

Static package imports and CLI syntax help can be checked independently. Actual
Scene preparation, physics, data collection, full regression suite, learning and
policy rollout require the appropriate external inputs. The existing launch
script, some UI defaults and historical tests contain workstation-specific paths.
This task does not change product paths or claim clean-machine portability.
Historical reports' `docs/evidence/` links intentionally refer to the preserved
local validation corpus, not files included in the proposed public payload.

The local prior **966 passed** result describes the configured original
workstation. It is not a clean-clone CI result. No fresh physics or training run is
performed for this upload preparation.
