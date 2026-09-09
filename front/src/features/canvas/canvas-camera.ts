/**
 * Camera-direction vocabulary: bodies, glass, focal lengths and apertures, and
 * the prompt language each one implies.
 *
 * Why this exists as prompt *text* rather than as generation parameters: no
 * provider this platform routes to accepts a focal length or an f-stop as a
 * request field (see `zaolang-agent-gateway` — the video models take a prompt,
 * first/last frames and reference media, and nothing else). Lens language
 * therefore reaches the model as words or it does not reach it at all.
 *
 * The catalogue is deliberately short. Every entry has to earn its slot in a
 * dropdown a director scans mid-thought, so this offers one clear option per
 * *look* — not every body and lens on the rental sheet. Product names are the
 * makers' own; the descriptions and the prompt fragments are ours.
 */

/** What the camera panel has set on a card. */
export interface CameraControlOptions {
  enabled: boolean;
  camera: string;
  lens: string;
  focalLength: number;
  aperture: number;
}

/** One catalogue entry.
 *
 * Bodies and glass carry exactly the same fields — both are "a thing you pick
 * that contributes a sentence to the prompt" — so they share one type instead
 * of two identical declarations that would drift apart.
 */
export interface OpticProfile {
  id: string;
  /** The maker's product name, shown verbatim in the picker. */
  label: string;
  zhName: string;
  /** Compact form used in the trailing summary tag. */
  shortTag: string;
  /** The sentence this choice contributes to the prompt. */
  profilePrompt: string;
  /** One line of 中文 explanation under the option. */
  description: string;
  /** What a director would reach for it for. */
  useCase: string;
}

export type CameraProfile = OpticProfile;
export type LensProfile = OpticProfile;

export const CAMERA_PROFILES: readonly CameraProfile[] = [
  {
    id: 'arri_alexa_35',
    label: 'ARRI Alexa 35',
    zhName: '阿莱 Alexa 35',
    shortTag: 'ARRI Alexa 35',
    profilePrompt:
      'captured on an ARRI Alexa 35, Super35 sensor with ARRI Reveal color, exceptionally wide exposure latitude, highlights that compress gently instead of clipping, skin rendered warm and dimensional',
    description: '当代剧集与广告的通用基准机，高光过渡最柔，肤色最稳。',
    useCase: '剧情、人物戏、品牌广告',
  },
  {
    id: 'arri_alexa_mini_lf',
    label: 'ARRI Alexa Mini LF',
    zhName: '阿莱 Mini LF',
    shortTag: 'ARRI Alexa Mini LF',
    profilePrompt:
      'captured on an ARRI Alexa Mini LF, large-format sensor, shallower apparent depth at equal framing, gentle falloff from face to background, restrained and filmic contrast',
    description: '大画幅版本，同样构图下背景更松，空间更立体。',
    useCase: '院线长片、大场面叙事',
  },
  {
    id: 'sony_venice_2',
    label: 'Sony Venice 2',
    zhName: '索尼 Venice 2',
    shortTag: 'Sony Venice 2',
    profilePrompt:
      'captured on a Sony Venice 2, full-frame sensor with dual native sensitivity, shadows that stay clean and noise-free deep into underexposure, precise saturated color without harshness',
    description: '双原生感光度，暗部干净，夜戏几乎不起噪点。',
    useCase: '夜戏、弱光、高端广告',
  },
  {
    id: 'red_v_raptor_8k',
    label: 'RED V-Raptor 8K VV',
    zhName: 'RED V-Raptor 8K',
    shortTag: 'RED V-Raptor 8K',
    profilePrompt:
      'captured on a RED V-Raptor 8K VV, very high resolution rendering fine texture — fabric weave, skin pores, hair strands — with punchy contrast and vivid but believable color',
    description: '极高分辨率，织物、毛发、皮肤纹理纤毫毕现。',
    useCase: '科幻、特效合成、产品特写',
  },
  {
    id: 'red_komodo_x',
    label: 'RED Komodo-X 6K',
    zhName: 'RED Komodo-X 6K',
    shortTag: 'RED Komodo-X 6K',
    profilePrompt:
      'captured on a RED Komodo-X 6K, compact global-shutter body, fast motion frozen without skew or wobble, crisp edges, clean deep shadows',
    description: '全局快门，快速横摇与高速运动不变形。',
    useCase: '动作戏、无人机、车拍',
  },
  {
    id: 'panavision_dxl2',
    label: 'Panavision Millennium DXL2',
    zhName: '潘那维申 DXL2',
    shortTag: 'Panavision DXL2',
    profilePrompt:
      'captured on a Panavision Millennium DXL2, 8K large-format sensor with Panavision color, dense saturated blacks, luminous rolled-off highlights, an unmistakably expensive theatrical image',
    description: '顶级院线质感，黑位厚实，高光通透。',
    useCase: '大制作、奢侈品广告',
  },
  {
    id: 'blackmagic_ursa_cine_12k',
    label: 'Blackmagic URSA Cine 12K',
    zhName: '黑魔法 URSA Cine 12K',
    shortTag: 'Blackmagic URSA Cine 12K',
    profilePrompt:
      'captured on a Blackmagic URSA Cine 12K, generous resolution with slightly cooler neutral color, honest unglamorised rendering, independent-film character',
    description: '中性偏冷，不修饰，独立电影气质。',
    useCase: '独立电影、实验影像、MV',
  },
  {
    id: 'canon_eos_c400',
    label: 'Canon EOS C400',
    zhName: '佳能 C400',
    shortTag: 'Canon EOS C400',
    profilePrompt:
      'captured on a Canon EOS C400, full-frame sensor with Canon color, warm forgiving skin tones, pleasing natural reds and golds, broadcast-clean image',
    description: '佳能色彩，暖调肤色讨喜，红金还原漂亮。',
    useCase: '电视剧、婚礼电影、访谈',
  },
] as const;

export const LENS_PROFILES: readonly LensProfile[] = [
  {
    id: 'arri_signature_prime',
    label: 'ARRI Signature Prime',
    zhName: '阿莱 Signature 定焦',
    shortTag: 'ARRI Signature Prime',
    profilePrompt:
      'through an ARRI Signature Prime, round untextured bokeh, contrast that stays soft in the shadows, flares that bloom wide and pale rather than streaking',
    description: '圆形柔和虚化，暗部对比低，光晕淡而散。',
    useCase: '人物特写、高级感画面',
  },
  {
    id: 'cooke_s7i',
    label: 'Cooke S7/i',
    zhName: '库克 S7/i',
    shortTag: 'Cooke S7/i',
    profilePrompt:
      'through a Cooke S7/i, warm color bias, focus that falls away softly rather than snapping, gentle rendering of faces, classic British cinema character',
    description: '暖调偏移，焦点过渡绵软，经典英伦味。',
    useCase: '年代戏、人物叙事',
  },
  {
    id: 'zeiss_supreme_prime',
    label: 'Zeiss Supreme Prime',
    zhName: '蔡司 Supreme 定焦',
    shortTag: 'Zeiss Supreme Prime',
    profilePrompt:
      'through a Zeiss Supreme Prime, neutral color with no warm or cool cast, very high micro-contrast, edge-to-edge sharpness, clinically clean bokeh',
    description: '零色偏，微反差极高，全画面锐利。',
    useCase: '科技广告、建筑、产品',
  },
  {
    id: 'leitz_summilux_c',
    label: 'Leitz Summilux-C',
    zhName: '徕兹 Summilux-C',
    shortTag: 'Leitz Summilux-C',
    profilePrompt:
      'through a Leitz Summilux-C, crisp central detail paired with a fast falloff into smooth background, cool-neutral color, restrained flare',
    description: '中心锐利、背景迅速化开，冷中性色。',
    useCase: '现代剧情、夜景人像',
  },
  {
    id: 'cooke_anamorphic_i',
    label: 'Cooke Anamorphic/i',
    zhName: '库克变形宽银幕',
    shortTag: 'Cooke Anamorphic/i',
    profilePrompt:
      'through a Cooke Anamorphic/i, oval stretched bokeh, horizontal blue streak across bright sources, curved edge distortion, wide 2.39:1 cinematic framing',
    description: '椭圆虚化、水平蓝色拉丝、宽银幕构图。',
    useCase: '科幻、夜戏、大片感',
  },
  {
    id: 'atlas_orion_anamorphic',
    label: 'Atlas Orion Anamorphic',
    zhName: 'Atlas Orion 变形',
    shortTag: 'Atlas Orion Anamorphic',
    profilePrompt:
      'through an Atlas Orion anamorphic, oval bokeh with cyan horizontal flares, cleaner and more modern than vintage anamorphic, mild edge softness',
    description: '现代变形镜，青色光晕，边缘轻柔。',
    useCase: 'MV、风格化广告',
  },
  {
    id: 'canon_k35_vintage',
    label: 'Canon K35 (vintage)',
    zhName: '佳能 K35 老镜',
    shortTag: 'Canon K35',
    profilePrompt:
      'through a vintage Canon K35, glowing halation around highlights, lowered contrast, soft corners, warm amber cast, 1970s film character',
    description: '高光晕散、对比压低、四角发软，七十年代味。',
    useCase: '怀旧、梦境、文艺片',
  },
  {
    id: 'macro_probe',
    label: 'Macro probe lens',
    zhName: '微距探头镜',
    shortTag: 'macro probe lens',
    profilePrompt:
      'through a macro probe lens, extreme close-up from an unusually low and near vantage, exaggerated foreground scale, paper-thin focus plane, background dissolved to pure color',
    description: '贴近拍摄，前景被放大，景深薄如纸。',
    useCase: '美食、珠宝、微观特写',
  },
] as const;

export const FOCAL_LENGTHS = [14, 18, 24, 35, 40, 50, 65, 85, 100, 135, 200] as const;
export const APERTURES = [1.2, 1.4, 1.8, 2, 2.8, 4, 5.6, 8, 11, 16] as const;

export type FocalLengthValue = (typeof FOCAL_LENGTHS)[number];
export type ApertureValue = (typeof APERTURES)[number];

/** Copy shown beside each option in the picker. */
export interface OptionMeta {
  zhName: string;
  description: string;
  useCase: string;
}

export const FOCAL_LENGTH_META: Record<number, OptionMeta> = {
  14: {
    zhName: '超广角',
    description: '视野极宽，直线向外弯曲',
    useCase: '狭小室内、全景、主观视角',
  },
  18: { zhName: '超广角', description: '纵深被拉长，前后距离夸张', useCase: '建筑、街景、跟拍' },
  24: { zhName: '广角', description: '人物与环境同时交代', useCase: '大场面、群戏、纪实' },
  35: { zhName: '小广角', description: '最常用的叙事焦段', useCase: '对话戏、跟随镜头' },
  40: { zhName: '准标准', description: '介于叙事与人像之间', useCase: '文艺片、半身构图' },
  50: { zhName: '标准', description: '空间关系接近肉眼所见', useCase: '日常、街拍、通用' },
  65: { zhName: '中焦', description: '背景开始收拢，五官不变形', useCase: '双人对话、半身像' },
  85: { zhName: '中长焦', description: '经典人像焦段，主体干净剥离', useCase: '特写、情绪镜头' },
  100: { zhName: '长焦', description: '背景压缩明显，层次变平', useCase: '特写、微距、抓拍' },
  135: { zhName: '长焦', description: '强烈压缩，人物贴在背景上', useCase: '剧情特写、舞台' },
  200: {
    zhName: '超长焦',
    description: '空间被压到极致，戏剧感强',
    useCase: '偷窥视角、远距离捕捉',
  },
};

export const APERTURE_META: Record<number, OptionMeta> = {
  1.2: { zhName: '极大光圈', description: '合焦范围薄到只剩眼睛', useCase: '梦幻特写、极暗环境' },
  1.4: { zhName: '大光圈', description: '背景彻底化开成色块', useCase: '夜戏人像、氛围镜头' },
  1.8: { zhName: '大光圈', description: '主体剥离明显，仍留一点环境', useCase: '半身人像、弱光' },
  2: { zhName: '大光圈', description: '虚化柔和且锐度充足', useCase: '通用人像、日常' },
  2.8: { zhName: '较大光圈', description: '两三个人能同时在焦内', useCase: '对话戏、群像' },
  4: { zhName: '中光圈', description: '背景可辨但不抢戏', useCase: '婚礼、电视剧、访谈' },
  5.6: { zhName: '中光圈', description: '环境信息完整保留', useCase: '纪实、生活场景' },
  8: { zhName: '小光圈', description: '画质最佳区，前后皆实', useCase: '风光、建筑、全景' },
  11: { zhName: '小光圈', description: '景深极大，几乎处处清晰', useCase: '大场景、平铺产品' },
  16: { zhName: '极小光圈', description: '点光源出现星芒', useCase: '日光风光、星芒效果' },
};

export const DEFAULT_CAMERA: CameraProfile = CAMERA_PROFILES[0]!;
export const DEFAULT_LENS: LensProfile = LENS_PROFILES[0]!;

/** A band in a lookup table, keyed by the largest value it covers.
 *
 * Table-driven rather than an if-chain so the coverage is checkable by eye:
 * the bands are in one place, in order, and the final entry is the open-ended
 * tail. A gap would be visible; in a chain of early returns it would not be.
 */
interface Band {
  /** Inclusive upper bound. `Infinity` on the last entry. */
  readonly upTo: number;
  readonly render: (value: number) => string;
}

const FOCAL_BANDS: readonly Band[] = [
  {
    upTo: 20,
    render: (mm) =>
      `${mm}mm ultra-wide framing, sweeping field of view, straight lines bowing outward toward the corners, foreground looming large against a distant background`,
  },
  {
    upTo: 28,
    render: (mm) =>
      `${mm}mm wide framing, subject read together with the space around it, distances between planes exaggerated`,
  },
  {
    upTo: 40,
    render: (mm) =>
      `${mm}mm slightly wide framing, the everyday storytelling focal length, environment present but not overwhelming`,
  },
  {
    upTo: 58,
    render: (mm) =>
      `${mm}mm standard framing, spatial relationships close to unaided human vision, no perspective exaggeration in either direction`,
  },
  {
    upTo: 90,
    render: (mm) =>
      `${mm}mm short-telephoto framing, facial features rendered without distortion, background gathered in and softened behind the subject`,
  },
  {
    upTo: 140,
    render: (mm) =>
      `${mm}mm telephoto framing, noticeable compression flattening the planes, subject cleanly lifted off its background`,
  },
  {
    upTo: Number.POSITIVE_INFINITY,
    render: (mm) =>
      `${mm}mm long-telephoto framing, severe compression stacking foreground and background into one plane, subject observed from a distance`,
  },
];

const APERTURE_BANDS: readonly Band[] = [
  {
    upTo: 1.4,
    render: (f) =>
      `wide open at f/${f}, extremely shallow depth of field, the plane of focus barely thicker than the eyes, everything else dissolved into smooth color`,
  },
  {
    upTo: 2,
    render: (f) =>
      `at f/${f}, very shallow depth of field, background reduced to soft shapes, strong separation between subject and surroundings`,
  },
  {
    upTo: 2.8,
    render: (f) =>
      `at f/${f}, shallow depth of field, background recognisable but clearly soft, subject unambiguously the point of focus`,
  },
  {
    upTo: 4,
    render: (f) =>
      `at f/${f}, moderate depth of field, background legible and gently blurred, several subjects able to hold focus together`,
  },
  {
    upTo: 5.6,
    render: (f) =>
      `at f/${f}, balanced depth of field, the setting fully readable while the subject stays sharpest`,
  },
  {
    upTo: 8,
    render: (f) =>
      `at f/${f}, deep depth of field, foreground and background both sharp, an observational documentary rendering`,
  },
  {
    upTo: Number.POSITIVE_INFINITY,
    render: (f) =>
      `stopped down to f/${f}, very wide depth of field, sharpness carried from the nearest object to the horizon, point light sources breaking into starbursts`,
  },
];

function renderBand(bands: readonly Band[], value: number): string {
  const band = bands.find((candidate) => value <= candidate.upTo);
  // `bands` always ends at Infinity, so `find` cannot miss — but this repo
  // compiles with `noUncheckedIndexedAccess`, so state the tail rather than
  // asserting it.
  return (band ?? bands[bands.length - 1]!).render(value);
}

/** Describe how a focal length reshapes the space in frame. */
export function describeFocalLength(mm: number): string {
  return renderBand(FOCAL_BANDS, mm);
}

/** Describe the depth of field an aperture implies. */
export function describeAperture(f: number): string {
  return renderBand(APERTURE_BANDS, f);
}

/** Tells the model the camera is the *viewpoint*, not a prop.
 *
 * Without this, naming a body and a lens reliably gets you a photograph of a
 * camera sitting on a tripod. The instruction has to be first, before any of
 * the equipment names it is qualifying.
 */
const VIEWPOINT_GUARDRAIL =
  'the following describes the viewpoint this image is rendered from — optics and exposure only, never things to place in the scene; no camera, lens, tripod, rig or crew may appear anywhere in the image';

const SUBJECT_GUARDRAIL =
  'leave the subject, setting and action exactly as described above; change only how they are photographed';

/** The camera-direction clauses, in the order they should reach the model. */
export function cameraDirectionSegments(control: CameraControlOptions): string[] {
  const camera = CAMERA_PROFILES.find((item) => item.id === control.camera) ?? DEFAULT_CAMERA;
  const lens = LENS_PROFILES.find((item) => item.id === control.lens) ?? DEFAULT_LENS;
  return [
    VIEWPOINT_GUARDRAIL,
    camera.profilePrompt,
    lens.profilePrompt,
    describeFocalLength(control.focalLength),
    describeAperture(control.aperture),
    SUBJECT_GUARDRAIL,
    `[${camera.shortTag} · ${lens.shortTag} · ${control.focalLength}mm · f/${control.aperture}]`,
  ];
}

/** Append camera direction to an author's prompt.
 *
 * A no-op while the panel is off, so callers can pipe every prompt through it
 * unconditionally. The author's own text always comes first — the optical
 * language qualifies their idea, it does not compete with it.
 */
export function applyCameraPrompt(prompt: string, control?: CameraControlOptions): string {
  if (!control?.enabled) return prompt;
  const direction = cameraDirectionSegments(control).join(', ');
  return prompt ? `${prompt}, ${direction}` : direction;
}
