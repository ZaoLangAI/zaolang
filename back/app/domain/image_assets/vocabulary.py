"""The closed vocabularies a character/scene image request is written in.

One source of truth for three readers — the Pydantic request model
(`GenerationParams`, and through `make openapi` the frontend's TS unions),
`prompt_builder`, and the planner/copy prompts — so a preset the studio
offers is always one the pipeline can phrase. Mirrors
`app.domain.blocking.vocabulary`.

Every entry carries a short Chinese `label` (UI copy and write-back labels),
a `prompt` fragment written as concrete visual facts the image model can
render (facial muscles, colour temperature, light direction, era fixtures —
never a bare mood word), and a `negative` fragment naming the mistakes
models actually make for that preset.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, get_args

CharacterExpression = Literal[
    "neutral",
    "smile",
    "laugh",
    "smirk",
    "restrained",
    "breakdown",
    "anger",
    "shock",
    "fear",
    "sad",
    "shy",
    "cold_gaze",
]
SceneLighting = Literal[
    "dawn",
    "day",
    "dusk",
    "night_interior",
    "night_exterior",
    "candle",
    "neon",
    "overcast",
]
SceneWeather = Literal["clear", "rain", "snow", "fog", "sandstorm"]
SceneState = Literal[
    "intact",
    "messy",
    "searched",
    "damage_light",
    "damage_medium",
    "damage_heavy",
    "ruins",
    "festive",
]
ScenePeriod = Literal["ancient", "republic", "1980s", "1990s", "contemporary", "near_future"]
# A prop's condition (道具状态, AC-4) — one prop card's variants.
PropState = Literal["new", "worn", "damaged", "broken"]
# A character look's age stage (P2-6): the same person at another age.
AgeStage = Literal["child", "teen", "youth", "adult", "middle_aged", "elderly"]

CHARACTER_EXPRESSIONS: tuple[str, ...] = get_args(CharacterExpression)
SCENE_LIGHTINGS: tuple[str, ...] = get_args(SceneLighting)
SCENE_WEATHERS: tuple[str, ...] = get_args(SceneWeather)
SCENE_STATES: tuple[str, ...] = get_args(SceneState)
SCENE_PERIODS: tuple[str, ...] = get_args(ScenePeriod)
AGE_STAGES: tuple[str, ...] = get_args(AgeStage)
PROP_STATES: tuple[str, ...] = get_args(PropState)

# One composite expression image holds at most this many faces.
MAX_CHARACTER_EXPRESSIONS = 9
# A scene variant group asks one provider call for 2..N separate images.
MIN_SCENE_VARIANTS = 2
MAX_SCENE_VARIANTS = 4
# Outfit names ride into reference-asset labels (≤60) next to other text.
MAX_OUTFIT_LABEL_LEN = 20
MAX_PRESET_LABEL_LEN = 20


@dataclass(frozen=True, slots=True)
class Preset:
    label: str
    prompt: str
    negative: str


@dataclass(frozen=True, slots=True)
class PeriodPreset(Preset):
    # Era tells the rewrite must draw props/materials from — same role as
    # `app.agents.scene_skills.SceneSpaceSkill.cues`.
    cues: tuple[str, ...]
    # Anachronisms image models actually slip in for this era.
    pitfalls: tuple[str, ...]


EXPRESSION_PRESETS: dict[str, Preset] = {
    "neutral": Preset(
        "平静",
        "平静：面部肌肉放松，嘴唇自然闭合，眼神平视前方，眉毛舒展",
        "夸张表情",
    ),
    "smile": Preset(
        "微笑",
        "微笑：嘴角上扬并露出少许上齿，苹果肌隆起，眼角出现细纹形成笑眼",
        "假笑，僵硬的嘴角",
    ),
    "laugh": Preset(
        "大笑",
        "大笑：嘴巴张开露出上下齿，眼睛眯成弯月，头部微微后仰，脸颊明显鼓起",
        "面部扭曲变形",
    ),
    "smirk": Preset(
        "冷笑",
        "冷笑：单侧嘴角上挑，另一侧保持不动，上眼睑微压，眼神斜睨带轻蔑",
        "对称的微笑，友善的笑容",
    ),
    "restrained": Preset(
        "隐忍",
        "隐忍：下颌收紧咬肌微鼓，嘴唇抿成一条线，眼眶泛红含泪但泪水未落",
        "泪流满面，放声大哭",
    ),
    "breakdown": Preset(
        "崩溃大哭",
        "崩溃大哭：眉头上抬并向中间聚拢，嘴巴张开向下拉，泪痕布满脸颊，鼻翼泛红",
        "干净无泪的脸，微笑",
    ),
    "anger": Preset(
        "愤怒",
        "愤怒：眉头下压聚拢形成竖纹，鼻翼张开，紧咬牙关，目光凶狠直视",
        "微笑，放松的眉眼",
    ),
    "shock": Preset(
        "震惊",
        "震惊：眉毛高高抬起，眼睛睁大露出上眼白，嘴巴微张，面部僵住",
        "眯眼，平静的表情",
    ),
    "fear": Preset(
        "恐惧",
        "恐惧：眉毛上抬聚拢，瞳孔收缩眼睛睁大，嘴角向两侧拉紧，脸色发白",
        "微笑，放松",
    ),
    "sad": Preset(
        "悲伤",
        "悲伤：眉头内侧上扬呈八字，嘴角下垂，眼神低垂失焦，眼眶微湿",
        "微笑，兴奋",
    ),
    "shy": Preset(
        "羞涩",
        "羞涩：视线向下侧移避开镜头，脸颊与耳尖泛红，嘴角轻抿含笑",
        "直视镜头，夸张大笑",
    ),
    "cold_gaze": Preset(
        "霸总凝视",
        "霸总凝视：下巴微收，眼神冷静锐利直视镜头，面无表情，嘴唇紧闭，侧光勾勒轮廓",
        "微笑，柔和的眼神",
    ),
}

LIGHTING_PRESETS: dict[str, Preset] = {
    "dawn": Preset(
        "清晨",
        "清晨：太阳刚升起，低角度暖橙光约 3500K 从一侧斜射，暗部偏冷蓝，空气中有薄雾，长而柔的投影",
        "正午顶光，夜景",
    ),
    "day": Preset(
        "白天",
        "白天：约 5600K 日光，主光来自窗户或天空，光线明亮通透，阴影方向一致",
        "夜景，昏暗",
    ),
    "dusk": Preset(
        "黄昏",
        "黄昏：太阳贴近地平线，约 3000K 金橙色逆光，长投影，空气中可见光束，暗部偏冷形成冷暖对比",
        "正午顶光，阴天的平光",
    ),
    "night_interior": Preset(
        "夜·室内",
        "夜晚室内：动机光源为台灯、吊灯或屏幕，暖光约 2800K 形成有限光池，"
        "窗外是深蓝夜色或对楼灯火，整体低调",
        "窗外是白天天空，均匀明亮的室内",
    ),
    "night_exterior": Preset(
        "夜·外景",
        "夜晚外景：天空深蓝近黑，路灯或招牌等人工光源形成局部光池与反射，环境大面积处于阴影",
        "白天天空，太阳",
    ),
    "candle": Preset(
        "烛光",
        "烛光：唯一光源是烛火或油灯，约 1900K 的暖黄光，衰减快，远处沉入黑暗，光影轻微摇曳",
        "电灯，日光，均匀照明",
    ),
    "neon": Preset(
        "霓虹",
        "霓虹：品红、青蓝等饱和霓虹灯作为主光，在潮湿表面形成彩色反射，高对比，暗部浓重",
        "自然日光，柔和低饱和",
    ),
    "overcast": Preset(
        "阴天",
        "阴天：天空被云层完全覆盖，柔和漫射的冷灰光约 6500K，几乎没有硬阴影，饱和度偏低",
        "强烈阳光，硬阴影，晴朗蓝天",
    ),
}

WEATHER_PRESETS: dict[str, Preset] = {
    "clear": Preset("晴", "晴天：天空通透无云或少云，空气清晰", "雨水，积雪，浓雾"),
    "rain": Preset(
        "雨",
        "下雨：可见雨丝，地面湿润反光并有积水，玻璃上挂着水痕，空气中有水汽",
        "干燥的地面，晴朗无云",
    ),
    "snow": Preset(
        "雪",
        "下雪：雪花飘落，地面、屋檐和物体顶部覆盖积雪，环境偏冷色调",
        "绿叶繁茂的夏季，干燥地面",
    ),
    "fog": Preset(
        "雾",
        "大雾：浓雾弥漫，远景逐渐消失在灰白雾气中，层次靠空气透视区分，光线柔和",
        "清晰锐利的远景",
    ),
    "sandstorm": Preset(
        "沙尘",
        "沙尘：空气中弥漫黄褐色沙尘，能见度低，光线浑浊发黄，物体表面落满沙土",
        "清澈蓝天，干净的表面",
    ),
}

STATE_PRESETS: dict[str, Preset] = {
    "intact": Preset("完好", "状态完好：陈设整齐，结构无损，保持日常使用痕迹", "破损，废墟"),
    "messy": Preset(
        "凌乱",
        "凌乱：物品随意堆放，衣物杂物散落，桌面杂乱，但结构完好无破坏",
        "整洁有序，破损坍塌",
    ),
    "searched": Preset(
        "被搜查",
        "被翻找过：抽屉全部拉出，柜门敞开，物品散落一地，床垫被掀起，纸张四散",
        "整洁有序，火烧痕迹",
    ),
    "damage_light": Preset(
        "战损·轻",
        "轻度战损：墙面零星弹孔与细裂纹，玻璃个别破碎，少量碎屑落地，整体结构完好",
        "墙体坍塌，大面积焦黑，废墟",
    ),
    "damage_medium": Preset(
        "战损·中",
        "中度战损：墙面密集弹孔与放射状裂纹，局部焦黑熏痕，家具翻倒，玻璃大面积碎裂散落，"
        "空气中有粉尘，但墙体和屋顶未坍塌",
        "完好整洁，屋顶坍塌",
    ),
    "damage_heavy": Preset(
        "战损·重",
        "重度战损：部分墙体与屋顶坍塌露出钢筋或木梁，瓦砾堆积，残留火光与烟雾，焦黑遍布",
        "完好整洁，轻微划痕",
    ),
    "ruins": Preset(
        "废墟",
        "废墟：建筑大面积坍塌，只剩残垣断壁，杂草或积尘覆盖，长期无人",
        "完好的家具，新近的生活痕迹",
    ),
    "festive": Preset(
        "节庆装饰",
        "节庆装饰：悬挂灯笼、彩带或灯串，张贴节日装饰，整体喜庆但符合场景的年代与地域",
        "破损，阴森",
    ),
}

PERIOD_PRESETS: dict[str, PeriodPreset] = {
    "ancient": PeriodPreset(
        "古代",
        "古代：木构建筑、榫卯梁柱、纸糊窗棂或格栅，照明为烛火与油灯，器物为陶瓷、铜器、竹木",
        "电灯，玻璃窗，塑料制品，现代家具",
        cues=("木构梁柱与斗拱", "纸窗或格栅窗", "青砖或夯土地面", "烛台、油灯", "陶瓷与铜器"),
        pitfalls=("出现电线插座", "出现透明大玻璃窗", "出现现代沙发或金属家具"),
    ),
    "republic": PeriodPreset(
        "民国",
        "民国时期：中西合璧的建筑与陈设，木质家具搭配西式吊灯，老式拉线开关，旗袍月份牌，"
        "留声机与搪瓷器皿",
        "液晶电视，手机，塑料制品，现代装修",
        cues=("拉线开关与外露电线", "月份牌与老报纸", "留声机、老式座钟", "花砖地面", "木质百叶窗"),
        pitfalls=("出现平板电视或手机", "出现石膏板吊顶", "出现塑料椅"),
    ),
    "1980s": PeriodPreset(
        "八十年代",
        "1980 年代：水泥或水磨石地面，日光灯管，搪瓷杯与暖水瓶，挂历，"
        "凤凰牌自行车，小尺寸显像管电视",
        "智能手机，液晶屏，现代装修",
        cues=("日光灯管", "搪瓷脸盆与暖水瓶", "挂历与奖状", "绿色墙裙", "显像管电视与收音机"),
        pitfalls=("出现液晶电视或手机", "出现木地板与现代吊顶", "出现空调外机林立"),
    ),
    "1990s": PeriodPreset(
        "九十年代",
        "1990 年代：瓷砖地面，组合家具，大屁股彩电，VCD 机，BP 机或大哥大，港风海报",
        "智能手机，平板电脑，极简现代装修",
        cues=("组合柜与玻璃茶几", "显像管彩电与 VCD", "港风海报与挂钟", "瓷砖与墙纸"),
        pitfalls=("出现智能手机", "出现超薄电视", "出现网约车或共享单车"),
    ),
    "contemporary": PeriodPreset(
        "当代",
        "当代：现代装修与家具，液晶电视或智能设备，LED 照明，符合当下城市生活的真实细节",
        "古装元素，复古过时的器物",
        cues=("LED 灯与筒灯", "智能手机与平板", "现代家电", "简约家具"),
        pitfalls=("混入明显的年代旧物", "科幻化的全息界面"),
    ),
    "near_future": PeriodPreset(
        "近未来",
        "近未来：在当代城市基础上加入克制的科技元素，如透明显示屏、智能家居面板、无人配送设备，"
        "整体可信不夸张",
        "古装元素，赛博朋克夸张霓虹，太空舰船",
        cues=("透明或柔性显示屏", "极简白色家电", "智能家居面板", "无人机或机器人"),
        pitfalls=("夸张的全息投影铺满画面", "出现外星或太空元素"),
    ),
}

# How many cells (rows x cols) a composite expression image is laid out in,
# keyed by expression count. One expression is a single close-up.
EXPRESSION_GRID: dict[int, tuple[int, int]] = {
    1: (1, 1),
    2: (1, 2),
    3: (1, 3),
    4: (2, 2),
    5: (2, 3),
    6: (2, 3),
    7: (3, 3),
    8: (3, 3),
    9: (3, 3),
}

# A look's age stage. The prompt states renderable changes (face fat,
# bone structure, skin, hair) and always keeps reference 1's identity —
# the negative keeps the model from swapping in a different person.
AGE_STAGE_PRESETS: dict[str, Preset] = {
    "child": Preset(
        "童年",
        "年龄阶段：童年（约 6–12 岁），脸型更圆、五官比例更小、额头相对更宽，"
        "身高明显更矮、四肢纤细",
        "成年人身材，胡须，化妆，皱纹",
    ),
    "teen": Preset(
        "少年",
        "年龄阶段：少年（约 13–17 岁），面部仍带婴儿肥、下颌线柔和，皮肤光滑，"
        "身形单薄、尚未完全长开",
        "胡须，皱纹，成熟妆容，中年发福",
    ),
    "youth": Preset(
        "青年",
        "年龄阶段：青年（约 18–29 岁），面部紧致、轮廓清晰，皮肤饱满有光泽，体态挺拔",
        "皱纹，白发，眼袋，稚气的孩童脸",
    ),
    "adult": Preset(
        "壮年",
        "年龄阶段：壮年（约 30–44 岁），轮廓更硬朗、眼神更沉稳，眼角可见细纹，体格结实",
        "孩童脸，明显白发，老年斑",
    ),
    "middle_aged": Preset(
        "中年",
        "年龄阶段：中年（约 45–59 岁），法令纹与眼角纹明显、两鬓略见斑白，面部略松弛，体态稍有发福",
        "孩童脸，光滑无纹的少年皮肤，满头白发",
    ),
    "elderly": Preset(
        "老年",
        "年龄阶段：老年（60 岁以上），皮肤松弛有皱纹与老年斑，头发花白或稀疏，背部略弯",
        "光滑年轻的皮肤，乌黑浓密的头发，孩童体型",
    ),
}
AGE_IDENTITY_SENTENCE = (
    "保持参考图1人物的五官比例、骨相与辨识特征，只按该年龄自然变化，不要变成另一个人。"
)
AGE_IDENTITY_NEGATIVE = "不同的人，换脸，五官比例改变"


def age_stage_fragments(age_stage: object) -> tuple[str, str]:
    """`(prompt sentence, negative)` for a look's age stage; empty when unset
    or unknown."""
    preset = AGE_STAGE_PRESETS.get(str(age_stage or ""))
    if preset is None:
        return "", ""
    return (
        f"{preset.prompt}。{AGE_IDENTITY_SENTENCE}",
        f"{preset.negative}，{AGE_IDENTITY_NEGATIVE}",
    )


# A look's period (P3): the same `ScenePeriod` keys, written for a person —
# wardrobe, hair and props of that time — rather than for a set.
CHARACTER_PERIOD_PRESETS: dict[str, Preset] = {
    "ancient": Preset(
        "古代",
        "时代背景：中国古代，服饰为交领右衽的传统衣裳，发型为束发、发髻或发冠，配饰为玉佩、簪钗",
        "西装，牛仔裤，运动鞋，手表，眼镜",
    ),
    "republic": Preset(
        "民国",
        "时代背景：民国时期，服饰为长衫、旗袍、中山装或早期西式三件套，发型为油头、手推波纹或短发",
        "现代潮牌，运动鞋，耳机，手机",
    ),
    "1980s": Preset(
        "八十年代",
        "时代背景：二十世纪八十年代的中国，服饰为的确良衬衫、中山装、喇叭裤或军绿外套，"
        "发型为烫卷或齐耳短发",
        "智能手机，现代潮牌，无线耳机",
    ),
    "1990s": Preset(
        "九十年代",
        "时代背景：二十世纪九十年代，服饰为宽松西装、牛仔夹克、高腰裤，发型为中分或大波浪",
        "智能手机，无线耳机，当代潮牌",
    ),
    "contemporary": Preset(
        "当代",
        "时代背景：当代，服饰与发型符合当下日常审美",
        "古装，戏服",
    ),
    "near_future": Preset(
        "近未来",
        "时代背景：近未来，服饰带有功能面料、简洁的科技细节与发光饰条",
        "古装，复古年代服饰",
    ),
}


def character_period_fragments(period: object) -> tuple[str, str]:
    """`(prompt sentence, negative)` for a look's period; empty when unset."""
    preset = CHARACTER_PERIOD_PRESETS.get(str(period or ""))
    if preset is None:
        return "", ""
    return f"{preset.prompt}。", preset.negative


PROP_STATE_PRESETS: dict[str, Preset] = {
    "new": Preset(
        "全新", "物品全新完好，表面洁净，边角锐利，材质光泽自然", "划痕，锈迹，污渍，破损"
    ),
    "worn": Preset(
        "旧化",
        "物品明显使用过：边角磨圆、表面细小划痕与手摸包浆、局部褪色，但结构完整",
        "崭新反光，破碎，断裂",
    ),
    "damaged": Preset(
        "破损",
        "物品有明显损伤：裂纹、凹痕、缺口或撕裂，仍能辨认原貌",
        "崭新无瑕，完全粉碎",
    ),
    "broken": Preset(
        "损毁",
        "物品已损毁：断成数截或碎裂变形，碎片就近散落，材质断面清晰",
        "完好无损，崭新",
    ),
}


def prop_state_fragments(state: object) -> tuple[str, str]:
    """`(prompt sentence, negative)` for a prop variant's condition."""
    preset = PROP_STATE_PRESETS.get(str(state or ""))
    if preset is None:
        return "", ""
    return f"{preset.prompt}。", preset.negative


SCENE_PRESET_TABLES: dict[str, Mapping[str, Preset]] = {
    "lighting": LIGHTING_PRESETS,
    "weather": WEATHER_PRESETS,
    "state": STATE_PRESETS,
    "period": PERIOD_PRESETS,
}
# The order scene preset fragments are written in, and the `scene_<axis>`
# request field each one comes from.
SCENE_PRESET_AXES: tuple[str, ...] = ("period", "state", "lighting", "weather")


def expression_grid(count: int) -> tuple[int, int]:
    """Rows/cols for `count` expressions (clamped to the supported range)."""
    clamped = max(1, min(count, MAX_CHARACTER_EXPRESSIONS))
    return EXPRESSION_GRID[clamped]


def scene_presets_from(source: dict[str, object]) -> dict[str, str]:
    """`{axis: value}` for every known, set scene preset in `source`.

    `source` is either request params (`scene_lighting`, …) or one
    `scene_variants` entry (`lighting`, …); both spellings are accepted so
    callers don't have to translate first. Unknown values are dropped — the
    request schema already rejected them, this is only a defensive read of
    a JSON column.
    """
    presets: dict[str, str] = {}
    for axis in SCENE_PRESET_AXES:
        value = source.get(f"scene_{axis}", source.get(axis))
        if isinstance(value, str) and value in SCENE_PRESET_TABLES[axis]:
            presets[axis] = value
    return presets


def scene_preset_label(presets: dict[str, str]) -> str:
    """`夜·室内 / 雨 / 战损·中 / 民国`-style label for a preset combination,
    in `SCENE_PRESET_AXES`' reading order (lighting/weather first reads more
    naturally to a human, so labels use their own order)."""
    order = ("lighting", "weather", "state", "period")
    return " / ".join(
        SCENE_PRESET_TABLES[axis][presets[axis]].label for axis in order if axis in presets
    )
