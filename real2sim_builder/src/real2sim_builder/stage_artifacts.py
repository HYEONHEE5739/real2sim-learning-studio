"""Typed, byte-verified stage records within the existing Candidate lifecycle.

This module only owns artifact validation and identities. Execution remains in
automation.py; model runtimes remain child processes.
"""
from dataclasses import asdict, dataclass, field
from pathlib import Path
import hashlib
import json
from .files import sha


STAGE_NAMES = (
    'RGB preparation', 'DA3 Nested depth', 'Canonical frame / SAM3 support',
    'World frame / metric QA', 'Scene decomposition', 'Object RGBA preparation',
    'Codex / Blender meshes', 'Mesh pose matching', 'Optional articulation',
    'Scene compilation', 'Collision / properties', 'Physics stabilization',
    'USD package', 'Simulator / sensor integration',
)
STATUSES = {'COMPLETE', 'NEEDS_RUNTIME', 'NEEDS_MORE_DATA', 'NEEDS_REVIEW',
            'FAILED', 'STOPPED', 'NOT_SUPPORTED'}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False,
                                    separators=(',', ':')).encode()).hexdigest()


def cache_key(stage_id, inputs, config, runtime):
    return digest([stage_id, inputs, config, runtime])


def _plain_file(path):
    path = Path(path).absolute()
    if path.is_symlink() or any(p.is_symlink() for p in path.parents):
        raise ValueError('Artifact symlink is forbidden')
    if not path.is_file():
        raise ValueError('Artifact integrity: missing file ' + str(path))
    return path.resolve()


def manifest(paths, data=None):
    files = []
    seen = set()
    for path in paths:
        path = _plain_file(path)
        if str(path) in seen:
            continue
        seen.add(str(path))
        files.append({'path': str(path), 'sha256': sha(path)})
    result = {'files': files, 'data': data or {}}
    digest(result)  # Reject NaN/non-serializable metadata before publishing.
    return result


def verify_manifest(record, *, output_root=None):
    if not isinstance(record, dict) or set(record) != {'files', 'data'}:
        raise ValueError('Expected an explicit file/data manifest')
    seen = set()
    for row in record['files']:
        path = _plain_file(row['path'])
        if output_root is not None and not path.is_relative_to(Path(output_root).resolve()):
            raise ValueError('Artifact output outside stage attempt')
        if str(path) in seen or sha(path) != row['sha256']:
            raise ValueError('Artifact integrity mismatch: ' + str(path))
        seen.add(str(path))
    digest(record)


@dataclass
class StageArtifact:
    stage_id: int
    status: str
    input_manifest: dict
    input_sha256: str
    output_manifest: dict
    output_sha256: str
    runtime_identity: dict
    config_identity: str
    coordinate_frame: str
    units: dict
    provenance: dict
    warnings: list = field(default_factory=list)
    needs: list = field(default_factory=list)
    error: dict | None = None
    schema: str = 'real2sim.stage-artifact/1'

    @classmethod
    def create(cls, stage_id, status, inputs, outputs, *, runtime_identity,
               config, coordinate_frame='not_applicable', warnings=(), needs=(), error=None):
        return cls(stage_id, status, inputs, digest(inputs), outputs, digest(outputs),
                   runtime_identity, digest(config), coordinate_frame,
                   {'length': 'm', 'angle': 'rad'},
                   {'execution': 'mock' if runtime_identity.get('kind') == 'mock' else 'real',
                    'physical_verified': False}, list(warnings), list(needs), error)

    def validate(self, output_root):
        if type(self.stage_id) is not int or not 1 <= self.stage_id <= 14:
            raise ValueError('Invalid stage ID')
        if self.schema != 'real2sim.stage-artifact/1' or self.status not in STATUSES:
            raise ValueError('Invalid stage artifact schema/status')
        if not self.runtime_identity or not self.coordinate_frame:
            raise ValueError('Runtime and coordinate provenance required')
        verify_manifest(self.input_manifest)
        verify_manifest(self.output_manifest, output_root=output_root)
        if digest(self.input_manifest) != self.input_sha256 or digest(self.output_manifest) != self.output_sha256:
            raise ValueError('Artifact integrity digest mismatch')
        if self.status == 'COMPLETE' and not self.output_manifest['files']:
            raise ValueError('A complete stage must retain an actual output artifact')
        if self.provenance.get('execution') not in ('real', 'mock'):
            raise ValueError('Actual/mock execution provenance required')
        return self

    def to_dict(self):
        return asdict(self)


class StageNeeds(RuntimeError):
    def __init__(self, status, message, *, code=None, classification='HARD_BLOCK',
                 scope='stage', object_ids=(), dependencies=(), input_sha256=None):
        if status not in STATUSES - {'COMPLETE'}:
            raise ValueError('Invalid stage stop status')
        self.status = status
        self.code = code
        if classification not in {'HARD_BLOCK','RETRYABLE','OBJECT_REVIEW','ESTIMATED_CONTINUE','DEPENDENCY_BLOCK','FINAL_APPROVAL_BLOCK'}:
            raise ValueError('Invalid gate classification')
        if scope not in ('stage','object','approval'):raise ValueError('Invalid gate scope')
        self.gate = {'classification':classification,'scope':scope,'reason':code or status,
                     'object_ids':list(object_ids),'dependencies':list(dependencies),
                     'input_sha256':input_sha256,'resume_requires_review':classification!='ESTIMATED_CONTINUE'}
        super().__init__(message)


# One explicit pre-semantic-preview baseline. Runtime never invokes Git and never
# rewrites a retained Artifact to pretend it was produced by the current code.
_STAGE12_BASELINE_COMMIT = '8e02b1ae023a856694a40b947881f76b66410624'
_STAGE12_BASELINE_SOURCES = {'__init__.py': 'f6d3b8f49db9d4ae71f6fc98537bf658ac2bc55361383181f08bf907bb8dc69d',
 'asset_view.py': '08dcc69a394c8f2d0213767223826a83e44899bbb88383b37598d4f36c6b8974',
 'authoring.py': 'd5ee53912d22afb92d4b77f8fd4f38a54a67c74681a503a4b173e2764e531864',
 'automation.py': '40a696003aaeaf98a31fc6024ea57e4c9c0ae574fefd10dc2c51c55abc36af12',
 'calibration/__init__.py': '0d8aec53c7a25ec6632dee14c4d599bd5d95e50a0100def05b0da9bb759767a1',
 'calibration/camera.py': '8633076307fe857567be18d6b6dd757441b9e0074021808bc8f6c5059a6e1d2b',
 'calibration/canonicalization.py': '7686175f5d723c21d081a8650cd4a4bbc00d591683792059f9111aba2b538483',
 'calibration/decomposition.py': '567aadc0fe7d84da4255ad1dd17eadeda1ec25597820e507681d4fc62028291a',
 'calibration/frame_selection.py': '64e6ec434f3e9079ac799dca323f2294305bcc2f31f002ef48c8d38db594a434',
 'calibration/geometry.py': 'cbbf4b746372f28ec9913e37852884f0e2ce12ccc767fd6d7984381bed09fa5e',
 'calibration/hybrid.py': '9ed7cc658d22f0dcd11c241717696728f82a9ecb6221352f15c632d6066c6c96',
 'calibration/joint.py': '7eb43564185228d7c5990fc2ea20cd2886625d221f47983717eb2bf39a22626b',
 'calibration/physics.py': '60ea7b50b7f8c72c6221413d98c522def145e09f5987f1de64818749a933e12c',
 'calibration/registration.py': 'e2e5747378ed047634c0ad0a162227b07c5befd5198561fa3d58a8cf9df3bd77',
 'calibration/simfoundry.py': '882cb9e2035a9280f2873b11027e13ea2d57f59b89e6ec8138d5249d57128bd7',
 'calibration/wrist.py': 'fc3374e2973ef93b593b63dc828372e131e7e4cae230ccbda1ca505392861a54',
 'cameras.py': '571daa2f879120462734b61909945b4e003c15e91d53b41b9c6853f7164b2038',
 'candidate.py': 'fd21bac4e931f3874e574adff8ece1d0b884b3752efa507ca7a1ce10d812aa18',
 'capture.py': 'aa12d92f784767e01bff9ed501b2ec6446a1c8da0a84e256258ed799f066aea0',
 'cli.py': '0fdc940d9d2b71b3a497ce11759501802e3e2b6ada27a6e6e7ce5058587b318d',
 'codex_cli.py': '206aacf703901b1b30030a2c7381c76e69e0a8ea5a3b7a5c6244d3e522cbca7f',
 'comfy_edit.py': 'e4fbff45790c6e203652cf2e511580448a958a420440fdc0f9c0f231cd6cd4da',
 'editing.py': '708074d52c322e1b9c44828065dcca4ee4a573f8821ed81e7020d82422dfb8e4',
 'evidence.py': '3198b9162a8ac94121feaccbbeb78f6c812c2857b7e128487a5bcee76d71ef7e',
 'export.py': 'f0114ae62e0d8384d773ce8e18e1a4672867fb9bfe98232a9b5cedf0bc569819',
 'exporters/__init__.py': 'f607eec8797d05d1d46bcec1f568f5e6d80f673ac581c1981369ba456881ae52',
 'exporters/mjcf.py': '06fa765163ed54c549dd427b1f12bec95438985f1dba161cbe17880050d5d7ef',
 'exporters/usd.py': 'fe8d50e4272596802cefdd32f63b524073836c16e96db3846c6ed1af4f5e6d42',
 'files.py': '17fb54d8668ded5d2620c1d457c46fb3b9b4192519005bb13a3daf99a206eecb',
 'inference.py': '9822e58a6fb4dc03ed8938d6bb32c58a0e9dd7f547cf056850c1753f73910b66',
 'initialization.py': '82baf1b9e6702d04efc506795999871bc6c7c56fc1dceae1d4b26c871d80da54',
 'isaac_render.py': '0063ff715369cc655be62e673500f4a02a88bb21f1d0a0c93ab9a446da985a80',
 'object_assets.py': '0be36a3742f4302cad7d013efaf4730fb5efe2e5ecbe24426eb3cb71e57331ab',
 'observations.py': '7cc10dd47ee18bc86f1b0c29ebf09da35c678629a99c51ada2f1ac443a30fc78',
 'project.py': '1f964ff0dc46e48c706e2e96e6b5a2f4d80ce94074bb077ad606251506c31154',
 'reconstruction.py': '776e4faeaa8e4ea666cf09f898d92c4959d4931336966aa2beb36f4eaf74686c',
 'reconstruction_stages.py': '3dbc481e6c750f50d9702d65564254b1df77552b3d86357e46b93af296ba8b93',
 'registration.py': 'b262f055690aaf198a908923d18be6793da052ef074d58c1e2d86be4ea8d2aeb',
 'rendering.py': '4fca7dc4408e0e9e7904041c0462ccf8153124ddacbe1235e825664d1f9fd308',
 'sam31_adapter.py': '97e3aeeb562af0718db026a93d5877fae2837c4fd8b4ae32372dbf2ff52330b5',
 'scene.py': '476c9d163e10b8afd11919f06252afa6b0c7333fe704d46245ddc9b46daeb8d9',
 'stage_artifacts.py': '35bd72c53c95d11396a69efc9baef23e26d5ef82a001f318278b962d8f799e45',
 'stage_runtime.py': '36a9d64e41cdb6c5a29f2dea2bc1466c2930714b2952e8b855015920825a1aac',
 'stage_workers.py': 'e0cedc6c9bd0d79fbb002e77fac28e3b89932be15ad9b59b8a3b9f273ced01f7',
 'ui.py': 'df8e0443c75b30aeef1d38fce484fc2ec6ac4a757336d7f779e9e6a5c9458b10',
 'ui_reconstruction.py': '00abc12d6aad7db1664b68d5e082d02976127e72a4338a17c9a5a616e1723eec',
 'validation.py': 'ff94c23c9df8c87bb22eacb803371dade45bedde606129e3720908458f169bab',
 'visual_evidence.py': '8d3418725bb98f76bbf030f7568284da83f79ba37b049134979406aff7e37dcf'}
_STAGE12_PROTECTED_AST = {'authoring.py': {'_codex_guidance': '756eeac4fbfb9c0f2e6a15880ae69a60a3a3ad5ce4b6849aa2fd29127f48bee2',
                  '_stage_source_views': 'e9c98017a5248d636ac60969f1dcf1ce8201b167d6a9c02b389fc4edf471ae8a',
                  'analysis_required': '444ec7d6b292b50375f170db406c79249d1a612d2241bd2489c62893897ed1e2',
                  'apply_scene_plan': 'ac09e2d890c5a5fdcded80ec53dcf6964b71935363b537b71dcd111081f59098',
                  'attach_modeled_assets': '0547726d518a7bc64474dd6da4417ba2f4ac07470f7b145f7697279f5af0a6d0',
                  'exclusive': '2658ade58f354d0fd6611a4585a30d38f740ecc3a56c3d74152a026bdf698e26',
                  'fitting_review': '4ff507b4d5ad49bf1dd32f3132afed1d26322fe7ae4390f36daac9eb15265f94',
                  'geometry_specs': '3d17edca04fb4742e83f1d70c450c307be269525bc999d9de4bd394f9f388471',
                  'group_asset': '1c322ee1bccdd777f5d61f238a3430d265f7dee4820a57a12c424dcc13e55b83',
                  'memo_dimension_claims': '440214ebba9add5948711fa89ae23784d70839f104aad7ea1e747b2fe7b6f8c9',
                  'memo_dimension_relations': '6d85a46860841e931296ab3f0563646ef562ed2ff4892e27349befbf63026ae1',
                  'modeling_groups': '00f951238480fb9f9e46d43c467b470a781a62ea3abec2407e9eb502c71a4e99',
                  'modeling_tasks': '804a182acbd62505542609cfc37ae648393a1c04b66c8dd4cb5b028bee5399e7',
                  'numbered_path': '57b1f459a575009fbd2de98ba2f30f5edcd8fa5019a25735d48e69e37ceec195',
                  'parse_scene_analysis': '763046e147d753dfd6d96ea4c94b97017f615325c7c46045c3539b1cf6536d95',
                  'read': '966280caa19e7e76ec4da9f83c0dfaf7840b6b1324878c62641a5b6b32b3abb6',
                  'record_modeling_results': '6248f2fcb05e32a53d6d7047dfe90c136e5c066be3eca96b62a11e13aea2c25c',
                  'review_decision': '57da7156d2442255fc532f761658a02700b456cb594544112a2367b6e5095b6c',
                  'run_codex_modeling': '234e1cc7c20e4ea059a98073029b3966cd0a6e5f021c55d1f2d8f37c8bfc068d',
                  'run_codex_vlm': '2f9c8906e14dd6705f10b38071767766b690904d30581d31dbbbc85823ca87e9',
                  'save_configuration': 'b05599eeb5b1008e2669aa11dd664fd9e498026957ae10491b76b9d4095e3a7a',
                  'scene_analysis_schema': '49507311e94e4d6b781ce425f21d21d68ab2dbc3fe60c8db0df8fed3e39952e9',
                  'scene_plan_schema': 'c6859929173ce123f4a4c0b5f95433fe59078c28b9936edf3a629d8b35ecbeea',
                  'sha': '78c706afa9bb0827683e36d4e8ce056bfeaeba777172ac22bcec6d8b8255dab0',
                  'stage_digest': 'ce3023cff6190888c394790980922e60de2b3ec24d29cd6069420a7b8ebf4ae2',
                  'task_intent': 'a6328f3dc399671ba5c5f10648de64a020cd7872d95deffe2949d549ffc1876d',
                  'visual_policy': '1a43c6e02e9d6ce28d9208f6713e60937a6b896b62583ad973f6e5d5a9a97bf9',
                  'write': '92d47ff0f20c417c333330a95036bd82636e5eb038f0d24d946f2a7a62392057'},
 'automation.py': {'Candidate': 'e78e8e54de391e0da44fa8d7e8d9448e73f8d504d012d6b8be2822f50c784fcb',
                   'analysis_required': '2c40301c248b94562343dc7d8fc5475fb1583e7a9f1db843aa32276eb247c5d4',
                   'attach_modeled_assets': 'e832649791775c6d72f2ce0272fa33634537a9c88562cc0553a435542310d7a1',
                   'copy': '33e554a09588607f47c37f53babe8c268271234110ee05725315e1f269aea608',
                   'exclusive': '2658ade58f354d0fd6611a4585a30d38f740ecc3a56c3d74152a026bdf698e26',
                   'modeling_tasks': 'dad4f89403087eb7d18baa328100096658b7bc42c39c71430c6ecf65580734c0',
                   'numbered_path': '57b1f459a575009fbd2de98ba2f30f5edcd8fa5019a25735d48e69e37ceec195',
                   'read': '966280caa19e7e76ec4da9f83c0dfaf7840b6b1324878c62641a5b6b32b3abb6',
                   'sha': '78c706afa9bb0827683e36d4e8ce056bfeaeba777172ac22bcec6d8b8255dab0',
                   'write': '92d47ff0f20c417c333330a95036bd82636e5eb038f0d24d946f2a7a62392057'},
 'reconstruction_stages.py': {'Path': '59051b17634cdcb5a576ceb58fdc0a4e5652ed3b60d66667e92ddefd931abeca',
                              'StageNeeds': '7b7a238b2ed60451eade29ec655687a8124404e4a13594e98c2832e2b566d558',
                              'backproject': '4576890fbe7dca74d5b9e560c41ea20e0d393cee0db11dda3600bdc42c0f8de0',
                              'copy': '33e554a09588607f47c37f53babe8c268271234110ee05725315e1f269aea608',
                              'depth': '3af163df7a4e6de17eaff3a41b74391915ddcceb1be676c660d6f480d6d0a788',
                              'json': '211ee42757705c7e350e70e36b762987a737f5e9c268f2a343e2dbfcb8fbea75',
                              'merge_chunks': '32787b0e1e18ca92bd91eb423da17ad121e466bce4c9c3163d362e644bbbb26e',
                              'metric_qa': 'c1c47b44b79ddd7ccd6b12ceebbb65b413d1fcfcffbdc08c29330d91fa030a16',
                              'np': '271fc31378e1108a9784c29c3c4768de571ce080301b4ad9721ba767fcf5842b',
                              'plan_chunks': '863efaf815b394cba586de34b8fd630e777b995fe0a5d471a4f7a57d48c05879',
                              'prepare': '24636c24d59f26c2a810f4589cb980d39f1302ff726c904324752f83511b9579',
                              'read': '966280caa19e7e76ec4da9f83c0dfaf7840b6b1324878c62641a5b6b32b3abb6',
                              'sha': '78c706afa9bb0827683e36d4e8ce056bfeaeba777172ac22bcec6d8b8255dab0',
                              'stage_digest': 'ce3023cff6190888c394790980922e60de2b3ec24d29cd6069420a7b8ebf4ae2',
                              'support_transform': '39942e62fc2eb179535b1b573e95ec3a34fd5565f10817df58308a2ccdfab240',
                              'world_points': 'c058539e2849c2e3e58fb0974de9b66d13f20c9bfbeb72f055eb9bda4d114e1b',
                              'write': '92d47ff0f20c417c333330a95036bd82636e5eb038f0d24d946f2a7a62392057'},
 'stage_artifacts.py': {'Path': '59051b17634cdcb5a576ceb58fdc0a4e5652ed3b60d66667e92ddefd931abeca',
                        'STAGE_NAMES': '6359ae7c70530eeb946941cb87b3efcc30fdc202314fc56af32a47d5fda80b63',
                        'STATUSES': '55abbdf35b47b252a03d553585d195f46e26eb31961eafd144013be1cd1eb50a',
                        'StageArtifact': '8836acf77cbf9e44d32316345e1754329e014087490566a89cfc3ac8dde4a8ac',
                        'StageNeeds': '2089a40b16f4e7470acaea2e9017443114a148959b0e0710e70947b129f1b152',
                        '_plain_file': '38715ef8103ae3667249a44a239bd6f20317a880d8759c7348f96dfb5a8c87ba',
                        'asdict': '400d7764c2a2b8cabf9a4dc4cd172f3f6e19abcbe53e771b676ad31a327775fa',
                        'cache_key': 'b4500759e21ba522fd2c75bb49989650a1f320bee3084a5648af94e159e73b83',
                        'dataclass': '321ed2ed3afceb74be547c9905ed4c676e453b1a68fe7cb2d3e214caeac2624d',
                        'digest': '703befd204aab9e040f951d29f6af2758fcb277f2f187db9253fac11ba5be260',
                        'field': 'eb1a3172ab0cffa940ac85581d4ff42904aa4ad7403efe269c12f47c80a13413',
                        'hashlib': '092cb77ae0770f1627b29bf41b2732722fbcc3a0e1d77a79674801800a2721d1',
                        'json': '211ee42757705c7e350e70e36b762987a737f5e9c268f2a343e2dbfcb8fbea75',
                        'manifest': '1c2d7dd908d5f38c04458166bc774aa43bb22aeedf74b058c222db3caf6b6951',
                        'sha': '78c706afa9bb0827683e36d4e8ce056bfeaeba777172ac22bcec6d8b8255dab0',
                        'verify_manifest': 'b9b261bd04ca31d81773c8abb51b5a0deabbc906cf884947df0d941d57433c88'},
 'stage_workers.py': {'Path': '59051b17634cdcb5a576ceb58fdc0a4e5652ed3b60d66667e92ddefd931abeca',
                      '_geometry': 'f6a12f9b06d9e44895e1ebd334ce5e3dea6e46df9f55fe8c4b1af3374961f0fd',
                      '_module': '7d00563d6123d477ebdfe540321b2af951f02f2f39f5833075ea517d4ed9a39e',
                      'da3': '0de66160ef1af14de051c13569e30aa8f2aa412e2a683eabc701e43912a7b6de',
                      'importlib': '866a97c0a29d398dc2bf8a74409548dccd9bb5221f4bf0f58ad1a37ef83e5260',
                      'json': '211ee42757705c7e350e70e36b762987a737f5e9c268f2a343e2dbfcb8fbea75',
                      'main': '63434daf81c90abb1252430b821de18d34d23406f3063e110bf26a85a2024ee0',
                      'os': 'ac3a74d6dd975a8e8fe4b7f85fce794793a9355595b850e3926964913948d386',
                      'sys': 'f7252e3c1dbe1d5edf1f34c020a58a05b55f706b2c1d9479eae91f9a9d4be275',
                      'video': 'c1943ed14aaf0dc55f1410751acb3ea0b5771cf4de59a3fdca615a1d578a2e96'},
 'evidence.py': {'Image': 'eb355e0b2477a9d207a50accb1e41c8347717cb90a6348625683dd4c9e8e9888',
                 'ImageOps': 'ff523233b47a3171d966cfebc614e700960e4d56ef59290c89d326db0bd3e1f0',
                 'PROVENANCE': 'c67b9c53bda849876321c4dcace83786294bcbf6a9543f037deb02d4806fd858',
                 'Path': '59051b17634cdcb5a576ceb58fdc0a4e5652ed3b60d66667e92ddefd931abeca',
                 'add_image': '9e88f7824659b5216ab55b4a7e0db3bb8afd51a801bae68e52a515faa9d09561',
                 'add_video': '9e4f8a10b41ecd6a313bdd44880e160d24a1121fa634be3d6f67f99a6c3db6fc',
                 'asset_importer': '1aa7cb669ccad86b433c1b58c445ee00441bec191775e617e08e9676dbf72604',
                 'copy': '33e554a09588607f47c37f53babe8c268271234110ee05725315e1f269aea608',
                 'copy_input': '2bc66c812ea804328d2921a82259f6875c2db0ce121cd67e0cb05ed70978857f',
                 'empty': '0678b6d4775956151fb8e43c22b9b420a74ef5389ffe4bcd75dc79bc2232b69f',
                 'extract_videos': 'abf6fcc6956ef60e5448b6ab611fd03b94515f2caa3e1d90fc2494e396c28d52',
                 'identifier': '3599f55b35ccc5d4c7539df8ee440e01858cc41486b53df021e7adcdd17fd46a',
                 'import_metadata': 'befda884ac28131bf23ee752755ad9592be5636d0db60e5cf9b3439f1626de7d',
                 'import_reference': 'b08e599d9a039c371aa542ae0ec40ca33e4c00906344d3b8c3b29d362db8c6ba',
                 'import_robot': '3ec7885b9691184456fe699c26e78e85482ac98c4a92a8af656280bbd0c4aefe',
                 'import_scene': '745e1a59d518786ec84302d27f08c773ebec70353924d7ae31d3b09e76fd2436',
                 'local_path': '07cab76c53b57ac5fad8020b44d13ab1b5cde8a072b2cb5d47f38850d72c5337',
                 'np': '271fc31378e1108a9784c29c3c4768de571ce080301b4ad9721ba767fcf5842b',
                 'read': '966280caa19e7e76ec4da9f83c0dfaf7840b6b1324878c62641a5b6b32b3abb6',
                 'save_reconstruction_memo': '34dcd310529eb9f5377a2595ea70aa9f6d3f1f55e166b93821583694ac237300',
                 'save_scene_memo': 'f81dae901ef98825fe549ae308425795ad0662b349f3f18008cd38391da484f5',
                 'scene_memo': '2fac23c00a6c65664d777508fc46626d1e72e461fde01a59f288b2b010b40f55',
                 'sha': '78c706afa9bb0827683e36d4e8ce056bfeaeba777172ac22bcec6d8b8255dab0',
                 'shutil': 'b461ae95c16c1e73a466fdd306ad6da693ead3a324e5d33627958cc4a2f47e36',
                 'validate': '2ddd405684121cd926cd8399110aa670e37524928a9e6077ced375935fc47a2c',
                 'value': '8f07b0d94aa66ec675b4c7d40869eaaebb8855ed5e7ddbb4340f6dfc460a03ec',
                 'write': '92d47ff0f20c417c333330a95036bd82636e5eb038f0d24d946f2a7a62392057'}}
_STAGE12_MODULE_CODE_AST = {'evidence.py': [], 'authoring.py': [],
 'automation.py': [],
 'reconstruction_stages.py': [],
 'stage_artifacts.py': [],
 'stage_workers.py': ['2bfa5d9c5accbccdc257b287a419748e048b2318f263f856ab271139ef0077d1']}

# Exact reviewed non-inference changes: JSON fast parsing preserves capture
# numbers; export registration only shares default post-reconstruction settings.
# Capture comparison only adds a lossless PNG compression argument, default 6.
# Neither changes Stage1/2 Worker/math. Unknown future edits remain invalidating.
# The reviewed Reconstruction dialog change only replaces stylesheet literals;
# its non-style AST is unchanged. Pin its exact bytes, not every future UI edit.
_STAGE12_AUDITED_STORAGE_SOURCES = {
    'files.py':'e395f91268b05b182de35046a9fe59ceb4de82a6cac9ca9677366e27701e1abc',
    'registration.py':'7e50302e895c5f867887415f5b5eb17d5c2ee12567c2f2732240986cdd34187c',
    'validation.py':'9effb37f804be8b9eeb5de89b8301428487f0ea7402e542568612bc64ef23499',
    'ui_reconstruction.py':'cebb0fd72b557783ca63fc3c5ce08b36b996e467392cddeff9286648fd46b635',
}


def _audited_stage12_sources(root, current_sources):
    """Conservative local dependency proof, not a general artifact migration."""
    import ast
    actual={str(p.relative_to(root)):sha(p)for p in root.rglob('*.py')}
    if actual!=current_sources or set(actual)!=set(_STAGE12_BASELINE_SOURCES):return False
    changed={name for name in actual if actual[name]!=_STAGE12_BASELINE_SOURCES[name]}
    other=changed-set(_STAGE12_PROTECTED_AST)
    if any(actual[name]!=_STAGE12_AUDITED_STORAGE_SOURCES.get(name)for name in other):return False
    def node_sha(node):return hashlib.sha256(ast.dump(node,include_attributes=False).encode()).hexdigest()
    for name,expected in _STAGE12_PROTECTED_AST.items():
        rows={};module_code=[]
        try:tree=ast.parse((root/name).read_text())
        except (OSError,SyntaxError,UnicodeError):return False
        for node in tree.body:
            bound=[]
            if isinstance(node,(ast.Import,ast.ImportFrom)):
                for alias in node.names:
                    key=alias.asname or(alias.name.split('.')[0]if isinstance(node,ast.Import)else alias.name)
                    single=ast.Import(names=[alias])if isinstance(node,ast.Import)else ast.ImportFrom(module=node.module,names=[alias],level=node.level)
                    if key in expected:rows.setdefault(key,[]).append(node_sha(single))
            elif isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)):
                if node.name in expected:rows.setdefault(node.name,[]).append(node_sha(node))
            elif isinstance(node,(ast.Assign,ast.AnnAssign)):
                bound=[n.id for n in ast.walk(node)if isinstance(n,ast.Name)and isinstance(n.ctx,ast.Store)]
                for key in bound:
                    if key in expected:rows.setdefault(key,[]).append(node_sha(node))
                if not set(bound)&set(expected):
                    # New literal constants are harmless. Import-time calls or
                    # globals()/exec side effects cannot bypass frozen bindings.
                    try:ast.literal_eval(node.value)
                    except (ValueError,TypeError):return False
            elif not(isinstance(node,ast.Expr)and isinstance(node.value,ast.Constant)and isinstance(node.value.value,str)):
                module_code.append(node_sha(node))
        if any(rows.get(name)!=[digest]for name,digest in expected.items()):return False
        if module_code!=_STAGE12_MODULE_CODE_AST[name]:return False
    return True


def audited_stage12_compatibility(stage_id, artifact, *, inputs, config, current_runtime, saved_key):
    """Recognize only audited unchanged Stage1/2 computation from one baseline.

    Caller must first validate the COMPLETE Artifact's file/closure bytes. The
    result is new report metadata; the old runtime identity and key stay intact.
    A missing proof returns None so normal cache invalidation remains in force.
    """
    if (type(stage_id)is not int or stage_id not in(1,2)or artifact.stage_id!=stage_id
        or artifact.schema!='real2sim.stage-artifact/1'or artifact.status!='COMPLETE'
        or artifact.provenance.get('execution')!='real'):return None
    old=artifact.runtime_identity;required={'kind','operations','stage_implementation_sha256'}
    if (set(old)!=required or set(current_runtime)!=required or old['kind']!='real'
        or current_runtime['kind']!='real'or old['stage_implementation_sha256']!=_STAGE12_BASELINE_SOURCES):return None
    if (artifact.input_sha256!=digest(inputs)or digest(artifact.input_manifest)!=artifact.input_sha256
        or artifact.config_identity!=digest(config)or artifact.output_sha256!=digest(artifact.output_manifest)
        or cache_key(stage_id,inputs,config,old)!=saved_key):return None
    operation='video'if stage_id==1 else'da3'
    if set(old['operations'])!={operation}or set(current_runtime['operations'])!={operation}:return None
    previous=old['operations'][operation];current=current_runtime['operations'][operation]
    if not isinstance(previous,dict)or not isinstance(current,dict):return None
    if (previous.get('kind')!='real'or previous.get('operation')!=operation
        or previous.get('worker_sha256')!=_STAGE12_BASELINE_SOURCES['stage_workers.py']):return None
    root=Path(__file__).parent;sources=current_runtime['stage_implementation_sha256']
    if current.get('worker_sha256')!=sources.get('stage_workers.py'):return None
    # Every setting/model/path/file/adapter/precision field must match. Only the
    # worker file's proven unrelated edits may differ, never its DA3/video path.
    if {k:v for k,v in previous.items()if k!='worker_sha256'}!={k:v for k,v in current.items()if k!='worker_sha256'}:return None
    if not _audited_stage12_sources(root,sources):return None
    return {'kind':'audited-code-compatibility','stage_id':stage_id,
            'baseline_commit':_STAGE12_BASELINE_COMMIT,
            'original_runtime_sha256':digest(old),'current_runtime_sha256':digest(current_runtime),
            'changed_modules':sorted(name for name in sources if sources[name]!=_STAGE12_BASELINE_SOURCES[name]),
            'original_artifact_provenance_preserved':True}
