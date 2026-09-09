"""Per-space-type skill packs the scene coach polishes against.

One empty-plate prompt cannot know that a stairwell needs a step direction
and a meter box, that a spacecraft cabin needs its gravity state stated, or
that a vacuum plate must not have god rays. Rather than grow
`ENHANCE_SYSTEM_PROMPT_SCENE` into a catalogue of every space a short drama
shoots in, the coach stays one page of method and the space-specific
checklist arrives per call as data.

The pack is injected through the *user* message, not the system prompt:
`run_agent` resolves the system prompt from the published `AgentSkill` row
(`app.domain.agent_skills.service.resolve_prompt`), so anything appended to
the constant here would be dropped the moment an operator publishes their own
wording — and a `{placeholder}` in the admin editor would be one more thing
for them to accidentally delete.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

# What has to be nailed down before the image model can keep a space
# consistent. Real places are pinned by when and where they are; invented
# ones have no era to pin, so they are pinned by the rules of their world
# instead. The scene coach asks a different follow-up question for each.
Anchor = Literal["era_region", "worldbuilding"]


@dataclass(frozen=True, slots=True)
class SceneSpaceSkill:
    """One space type's polish checklist."""

    key: str
    label: str
    anchor: Anchor
    # Matched against the author's own words, longest-hit-count wins.
    keywords: tuple[str, ...]
    # The structural facts the rewrite must state, so the room can be built.
    structure: tuple[str, ...]
    # What this space always contains — the rewrite draws props from here and
    # the author's own text, and invents nothing else.
    fixtures: tuple[str, ...]
    # Light sources, plus the physics the light has to obey.
    light: tuple[str, ...]
    # Era tells for a real place; world rules for an invented one.
    cues: tuple[str, ...]
    # The mistakes an image model actually makes on this space.
    pitfalls: tuple[str, ...]


_REAL: Anchor = "era_region"
_FICTION: Anchor = "worldbuilding"

SCENE_SPACE_SKILLS: tuple[SceneSpaceSkill, ...] = (
    # ---------------------------------------------------------------- 居住室内
    SceneSpaceSkill(
        key="residential_interior",
        label="居住室内（出租屋 / 卧室 / 客厅）",
        anchor=_REAL,
        keywords=("出租屋", "卧室", "客厅", "民房", "housing", "家里", "屋内", "房间", "老房子"),
        structure=(
            "层高与开间：老式住宅层高低、开间窄，落地窗与挑高属于另一种户型",
            "承重墙与门洞的位置要能连成一个真实户型，房间之间不得凭空穿通",
            "窗的朝向与外面能看到什么（对楼、天井、巷子）必须一致",
        ),
        fixtures=(
            "床或沙发、衣柜、贴墙的插座与开关面板、吊灯或吸顶灯",
            "地面材质（水泥 / 瓷砖 / 木地板 / 地板革）与墙面处理（涂料 / 墙纸 / 瓷砖裙）",
            "生活痕迹：晾着的衣物、堆叠的杂物、墙面钉孔与霉斑",
        ),
        light=(
            "主光通常是一盏顶灯或窗外天光，夜戏则是台灯与电视屏幕的局部光",
            "光源位置要能解释墙上的影子方向",
        ),
        cues=(
            "开关插座面板样式、灯具类型、电视机形制、暖气或空调形制",
            "地面与墙裙的材质随年代变化，是判断年代最快的线索",
        ),
        pitfalls=(
            "把中国老式住宅画成美式公寓：开放式厨房、挑高客厅、落地窗",
            "家具年代混搭：老墙面配当代北欧家具",
            "房间比实际户型大一圈，走廊无限延伸",
        ),
    ),
    SceneSpaceSkill(
        key="kitchen_bath",
        label="厨房与卫浴",
        anchor=_REAL,
        keywords=("厨房", "灶台", "卫生间", "浴室", "洗手间", "水槽", "厕所", "淋浴"),
        structure=(
            "操作面的高度与进深、上下水管的走向、排烟或排风的出口",
            "瓷砖的铺贴范围与收口位置（墙裙高度）",
        ),
        fixtures=(
            "厨房：灶台、抽油烟机、水槽与滴水板、碗碟与锅具、瓶罐调料",
            "卫浴：洗手台与镜柜、马桶或蹲坑、花洒或热水器、地漏",
            "油污、水垢、发黄的填缝剂是这两个空间的真实质感",
        ),
        light=(
            "常见是一盏冷白顶灯或抽油烟机自带的灯，光硬、投影短",
            "潮气会让高光更散，但不等于全屋起雾",
        ),
        cues=("热水器与抽油烟机形制、瓷砖尺寸与花色、水龙头样式",),
        pitfalls=(
            "把出租屋厨房画成样板间：整体橱柜、大理石台面、无油污",
            "水汽画成浓雾盖住整个空间",
            "上下水管凭空消失，水槽悬在墙上",
        ),
    ),
    SceneSpaceSkill(
        key="corridor_stairwell",
        label="楼道 / 楼梯间 / 单元门",
        anchor=_REAL,
        keywords=("楼道", "楼梯间", "楼梯", "单元门", "走廊", "过道", "门口", "防盗门", "扶手"),
        structure=(
            "台阶的走向与踏步数、休息平台的位置、栏杆与扶手的连续性",
            "门洞的宽度与门的开向；写了紧闭就必须保持关闭",
            "楼层高度与相邻户门的排布，公共走廊不得画成室内走廊",
        ),
        fixtures=(
            "防盗门与门锁、门牌号、电表箱与线管、声控灯、信报箱",
            "斑驳的墙面、脱落的涂料、贴的小广告、堆在墙边的杂物",
            "铁栏杆的焊点与锈迹",
        ),
        light=(
            "声控灯或应急灯是主光，位置低、色温暖、照射范围有限",
            "户门缝隙漏出的光是唯一能暗示屋内的东西",
        ),
        cues=("防盗门与门锁样式、电表箱形制、栏杆焊法、墙裙涂料的颜色与高度",),
        pitfalls=(
            "把紧闭的户门画开，用来展示屋内的走廊、厨房与家具",
            "把中式单元楼楼道画成西式酒店走廊：地毯、壁灯、成排相同的门",
            "同时画门内与门外两套空间",
        ),
    ),
    SceneSpaceSkill(
        key="luxury_home",
        label="豪宅 / 别墅",
        anchor=_REAL,
        keywords=("豪宅", "别墅", "大平层", "庄园", "洋房", "旋转楼梯", "宴客厅"),
        structure=(
            "挑高与楼梯的关系、落地窗的开间、玄关到客厅的进深",
            "室外景观与室内的关系必须一致（花园、泳池、城市天际线）",
        ),
        fixtures=(
            "大面积石材或木饰面、成组沙发、吊灯、艺术陈设、地毯",
            "干净是这个空间的特征，磨损痕迹要克制",
        ),
        light=("大面积自然光加重点照明；夜戏靠灯带与射灯分层",),
        cues=("装修风格（现代 / 新中式 / 欧式）必须全屋统一，不得混搭",),
        pitfalls=(
            "风格混搭：欧式线板配日式障子门",
            "空间尺度失真，家具比例对不上层高",
        ),
    ),
    # ---------------------------------------------------------------- 室内公共
    SceneSpaceSkill(
        key="office_commercial",
        label="办公室 / 总裁办公室 / 会议室",
        anchor=_REAL,
        keywords=("办公室", "总裁", "会议室", "写字楼", "工位", "格子间", "大堂", "前台"),
        structure=(
            "工位阵列的方向、隔断高度、通道宽度；独立办公室与开放区的分界",
            "落地窗外的城市景观与楼层高度必须一致",
        ),
        fixtures=(
            "办公桌与显示器、办公椅、文件柜、白板或投影幕、绿植",
            "总裁办公室：大班台、会客沙发、书柜、酒柜",
        ),
        light=("格栅灯或灯盘的规则阵列 + 窗光；夜戏靠台灯与屏幕光",),
        cues=("显示器形制、办公家具风格、地毯或架空地板",),
        pitfalls=(
            "工位阵列透视失控，桌子越远越大",
            "窗外景观与楼层不符：三楼窗外画成云海",
        ),
    ),
    SceneSpaceSkill(
        key="hospitality_dining",
        label="餐厅 / 包厢 / 咖啡厅 / 宴会厅 / KTV",
        anchor=_REAL,
        keywords=("餐厅", "包厢", "咖啡", "酒吧", "宴会厅", "ktv", "KTV", "食堂", "大排档"),
        structure=("卡座与散台的排布、吧台或舞台的位置、包厢的封闭边界",),
        fixtures=("餐桌与餐具、菜单、吧台酒瓶、点缀灯饰、地毯或地砖",),
        light=("暖色重点照明为主，桌面亮、通道暗；霓虹与灯球属于酒吧 / KTV",),
        cues=("装修风格与餐具形制决定档次与年代",),
        pitfalls=("把包厢画成开放大厅", "灯具风格与餐厅档次错配"),
    ),
    SceneSpaceSkill(
        key="medical",
        label="医院（病房 / 走廊 / 手术室）",
        anchor=_REAL,
        keywords=("医院", "病房", "手术室", "急诊", "护士站", "诊室", "输液"),
        structure=("床位间距与隔帘轨道、走廊的扶手与防撞条、护士站的位置",),
        fixtures=("病床与床头设备带、输液架、监护仪、隔帘、指示牌与门牌",),
        light=("冷白顶灯为主，均匀、少投影；手术室是无影灯",),
        cues=("设备形制与标识系统决定年代与地区",),
        pitfalls=("把病房画成酒店房间", "设备摆放不符合实际流线"),
    ),
    SceneSpaceSkill(
        key="school_dorm",
        label="教室 / 宿舍 / 校园",
        anchor=_REAL,
        keywords=("教室", "宿舍", "学校", "操场", "黑板", "课桌", "校园"),
        structure=("课桌阵列与讲台的关系、宿舍上下铺的排布、窗墙比例",),
        fixtures=("黑板或白板、课桌椅、讲台、宣传栏、上下铺与晾衣绳",),
        light=("成排日光灯 + 侧窗自然光",),
        cues=("黑板形制、课桌样式、墙面标语与配色",),
        pitfalls=("把中式教室画成西式圆桌讨论室", "课桌阵列透视崩坏"),
    ),
    SceneSpaceSkill(
        key="authority",
        label="审讯室 / 法庭 / 监所",
        anchor=_REAL,
        keywords=("审讯", "法庭", "监狱", "看守所", "警局", "拘留", "牢房"),
        structure=("桌椅的固定位置与对峙关系、栏杆或隔断、单向玻璃的位置",),
        fixtures=("固定桌椅、灯具、监控摄像头、标识与徽章位、铁栅门",),
        light=("单一硬光源，强对比、少环境光是这个空间的语言",),
        cues=("制式与标识必须与所在地区一致",),
        pitfalls=("照搬美式审讯室：单向玻璃 + 吊灯 + 金属桌",),
    ),
    SceneSpaceSkill(
        key="retail_market",
        label="超市 / 便利店 / 商铺 / 菜市场",
        anchor=_REAL,
        keywords=("超市", "便利店", "商铺", "菜市场", "货架", "档口", "收银"),
        structure=("货架阵列与通道宽度、收银台位置、门头与卷帘门",),
        fixtures=("货架与商品、价签、冷柜、称重台、遮阳棚与塑料筐",),
        light=("高显色排灯，整体均匀；菜市场是混色灯（生鲜灯）",),
        cues=("包装与价签样式、门头字体决定年代与地区",),
        pitfalls=("货架商品重复贴图", "把菜市场画成精品超市"),
    ),
    # ------------------------------------------------------------ 室外与半室外
    SceneSpaceSkill(
        key="street_alley",
        label="街巷 / 城中村 / 老城区街道",
        anchor=_REAL,
        keywords=("街道", "巷子", "城中村", "小巷", "街边", "路口", "胡同", "老城"),
        structure=(
            "街道宽度与两侧建筑高度的比例、退线与台阶、电线与空调外机的走向",
            "视线的尽头必须交代（拐角、路口、封闭端）",
        ),
        fixtures=("店招与卷帘门、电线与线杆、空调外机、雨棚、垃圾桶、停放的电动车",),
        light=("路灯与店招是夜戏主光，地面反射承担氛围；白天是天光加建筑投影",),
        cues=("店招字体与材质、建筑立面材料、车辆型号",),
        pitfalls=(
            "把中国街巷画成东南亚或日式街景",
            "电线与招牌堆成装饰，不遵循真实走向",
        ),
    ),
    SceneSpaceSkill(
        key="urban_skyline",
        label="天台 / 高楼外景 / 城市夜景",
        anchor=_REAL,
        keywords=("天台", "楼顶", "露台", "天际线", "城市夜景", "高楼", "CBD"),
        structure=("女儿墙高度、设备层与水箱、楼层高度与远景城市的透视关系",),
        fixtures=("女儿墙、通风管、水箱、避雷针、晾衣绳、散落的杂物",),
        light=("城市光污染做底光，天空不会是纯黑；主光来自远处楼宇与广告牌",),
        cues=("远景建筑形制决定城市与年代",),
        pitfalls=("天台离地高度与远景城市尺度对不上", "夜空画成布满星辰的荒野天空"),
    ),
    SceneSpaceSkill(
        key="parking_transit",
        label="地下车库 / 车站 / 机场",
        anchor=_REAL,
        keywords=("车库", "停车场", "车站", "机场", "地铁", "站台", "候车"),
        structure=("柱网间距与梁高、车位划线的方向、坡道与出入口、站台与轨道的关系",),
        fixtures=("承重柱与消防管、车位线与编号、指示牌、闸机、座椅",),
        light=("成排顶灯 + 应急灯，光斑规则且方向一致",),
        cues=("标识系统与配色决定地区",),
        pitfalls=("柱网透视崩坏", "车位线方向与车头朝向矛盾"),
    ),
    SceneSpaceSkill(
        key="nature_exterior",
        label="自然外景（山野 / 海边 / 田野 / 森林）",
        anchor=_REAL,
        keywords=("山", "海", "田野", "森林", "树林", "河", "湖", "草原", "野外", "郊外"),
        structure=("地形的起伏与视线尽头、地平线的高度、前景遮挡物的位置",),
        fixtures=("植被种类必须与地区气候一致、地表材质（沙 / 石 / 土 / 草）",),
        light=("单一太阳光决定影子方向，全画面影子必须朝同一侧；大气透视随距离减弱对比",),
        cues=("植被与地貌决定气候带，不是年代",),
        pitfalls=("热带植物出现在北方冬景", "影子方向互相矛盾", "大气透视缺失导致远景过实"),
    ),
    SceneSpaceSkill(
        key="vehicle_interior",
        label="车内",
        anchor=_REAL,
        keywords=("车内", "驾驶", "副驾", "后排", "方向盘", "车厢", "出租车"),
        structure=("座椅与仪表台的相对位置、车窗框对视野的裁切、A 柱的遮挡",),
        fixtures=("方向盘与仪表、中控、安全带、后视镜、挂饰与杂物",),
        light=("窗外环境光随车移动，仪表自发光是暗部唯一细节",),
        cues=("内饰形制与车型决定年代与档次",),
        pitfalls=("车内空间画得比车大", "窗外景色与车速、时间不匹配"),
    ),
    # ------------------------------------------------------------ 时代与工业
    SceneSpaceSkill(
        key="period_chinese",
        label="古装（宫殿 / 客栈 / 庭院）",
        anchor=_REAL,
        keywords=("古装", "宫殿", "客栈", "庭院", "厢房", "雕花", "宫廷", "古代", "王府"),
        structure=("开间与进深按木构架排布、梁柱斗栱的位置、门槛与台基高度、院落轴线",),
        fixtures=("木格窗与窗纸、屏风、案几、灯笼、砖地与青瓦",),
        light=("烛火与灯笼是点光源，暖、弱、投影长；白天靠天井漫射光",),
        cues=("形制必须锁定到一个朝代，家具与服饰制式不得跨代混用",),
        pitfalls=("朝代混搭：明式家具配唐式建筑", "把中式木构画成日式和室"),
    ),
    SceneSpaceSkill(
        key="industrial_ruin",
        label="工厂 / 仓库 / 废弃厂房",
        anchor=_REAL,
        keywords=("工厂", "仓库", "厂房", "车间", "废弃", "锈", "钢架", "厂区"),
        structure=("钢架或排架的跨度、天窗位置、吊车梁、地面沟槽",),
        fixtures=("机器与传送带、货架与托盘、铁桶、破窗与积灰",),
        light=("高窗天光形成一束束方向一致的光柱；夜戏靠零星工作灯",),
        cues=("设备形制与标语决定年代",),
        pitfalls=("破坏没有成因：完好的机器配塌陷的屋顶", "光柱方向与天窗位置矛盾"),
    ),
    # ------------------------------------------------------------ 虚构与科幻
    SceneSpaceSkill(
        key="spacecraft_interior",
        label="飞船 / 空间站舱内",
        anchor=_FICTION,
        keywords=("飞船", "空间站", "舱内", "舰桥", "驾驶舱", "太空舱", "星舰", "航天器"),
        structure=(
            "舱段是有限的闭合体积：舱壁、加强肋、气密门、贯穿的管线与线束",
            "重力状态必须明说——离心人工重力时地板向上弯曲收拢；"
            "微重力时没有「地面」概念，物件全部系留、扶手贯穿全舱",
            "舷窗是唯一能看到舱外的开口，没有画舷窗就不该有外部自然光",
        ),
        fixtures=(
            "控制面板与自发光仪表、储物格与束带、扶手或脚限位器、软管与阀门",
            "材质语言二选一并全舱统一：工业管线的粗糙实用，或洁净曲面的极简",
        ),
        light=(
            "嵌入式灯带与仪表自发光是主光，方向固定、范围有限",
            "舱内空气洁净，不该有大面积体积光雾",
        ),
        cues=("技术等级、所属势力的制式与配色、使用年限（崭新 / 久经使用）",),
        pitfalls=(
            "重力状态自相矛盾：漂浮的物件配踩实地面的家具摆法",
            "舱内出现来路不明的窗外阳光或天空",
            "把舱段画成无限延伸的走廊，失去闭合体积感",
        ),
    ),
    SceneSpaceSkill(
        key="outer_space_void",
        label="外太空（真空 / 轨道 / 舱外）",
        anchor=_FICTION,
        keywords=("外太空", "太空", "真空", "轨道", "宇宙", "星空", "舱外", "行星轨道"),
        structure=(
            "真空里没有地面与地平线，构图靠天体与航天器的相对位置建立方向",
            "画面里的天体尺度与距离必须一致：近处器物、远处行星、更远的恒星",
        ),
        fixtures=("航天器或空间站结构、行星与卫星的弧线边缘、太阳能板与天线",),
        light=(
            "真空没有大气散射：阴影是硬边，明暗交界锐利，暗部只靠行星反照补光",
            "禁止雾气、光柱、丁达尔效应、大气辉光这类需要介质的效果",
            "主光是单一恒星，第二光源只能是行星反照；星点稳定不闪烁",
        ),
        cues=("所处轨道与恒星方向决定整幅画的光比与色温",),
        pitfalls=(
            "给真空加体积光、烟尘或云雾",
            "阴影柔和得像有大气，暗部被凭空提亮",
            "行星、飞船与星空三者尺度互相矛盾",
        ),
    ),
    SceneSpaceSkill(
        key="alien_surface",
        label="异星地表",
        anchor=_FICTION,
        keywords=("异星", "外星", "星球表面", "火星", "月球", "陨石坑", "地外"),
        structure=(
            "地貌成因要自洽：风蚀、水蚀、火山、撞击各有各的形状，不要混着画",
            "地平线的曲率与天体大小要对应",
        ),
        fixtures=("岩层与砂砾、结晶或矿脉、若有植被必须与光谱一致、着陆器或遗迹",),
        light=(
            "天空颜色由大气成分决定，必须与地面受光的色温一致",
            "恒星数量必须与影子数量对上：双星就有两组方向不同的影子",
            "稀薄大气 = 阴影更硬、远景更清晰；浓密大气才有强大气透视",
        ),
        cues=("重力线索（尘埃下落与岩体堆积角）、大气密度、恒星类型",),
        pitfalls=(
            "紫色天空配地面暖黄阳光这类光色不自洽",
            "一颗恒星画出两组影子",
            "地貌成因混搭：水蚀河道出现在无水星球",
        ),
    ),
    SceneSpaceSkill(
        key="cyberpunk_city",
        label="赛博都市 / 未来街区",
        anchor=_FICTION,
        keywords=("赛博", "cyberpunk", "未来都市", "霓虹", "全息", "未来城市", "机械义体"),
        structure=(
            "街道宽度、建筑层高与广告牌尺度必须互相成立，招牌不能大过它挂的那栋楼",
            "上层结构（天桥、管道、飞行器航道）与地面层的关系要交代清楚",
        ),
        fixtures=("霓虹与全息招牌、雨棚与摊档、缆线束、监控与终端、湿滑地面",),
        light=(
            "主叙事光来自招牌与屏幕，色彩分区明确；湿地面反射是第二光源",
            "体积光成立，因为空气里有雨雾——但雾要有来源，不是全屏加白",
        ),
        cues=("技术等级与阶层分区：底层拥挤潮湿，上层洁净有序",),
        pitfalls=(
            "霓虹只是滤镜：颜色铺满画面却没有具体发光体",
            "广告牌尺度与建筑脱节",
            "所有表面都在发光，失去暗部",
        ),
    ),
    SceneSpaceSkill(
        key="post_apocalypse",
        label="末世废墟",
        anchor=_FICTION,
        keywords=("末世", "废墟", "灾后", "丧尸", "核爆", "荒废", "文明崩塌"),
        structure=(
            "破坏必须有单一成因（火 / 爆炸 / 洪水 / 地震 / 植被侵入）并贯穿全画面",
            "承重结构的坍塌方向要与成因一致",
        ),
        fixtures=("倒塌的结构、锈蚀金属、侵入的植被、散落的旧文明遗物、积尘",),
        light=("穿过破口的天光是主光，破口位置决定光柱方向；尘埃让光柱可见",),
        cues=("崩塌距今多久：锈蚀深度与植被覆盖程度是唯一的时间刻度",),
        pitfalls=(
            "完好的家具配倒塌的屋顶：破坏程度前后不一致",
            "植被覆盖与锈蚀程度对应不上同一段时间",
            "光柱方向与破口位置矛盾",
        ),
    ),
    SceneSpaceSkill(
        key="fantasy_realm",
        label="奇幻 / 仙侠 / 异世界",
        anchor=_FICTION,
        keywords=("奇幻", "仙侠", "异世界", "魔法", "秘境", "神殿", "悬浮岛", "灵气"),
        structure=(
            "悬浮或超常结构必须给出可见的支撑或能量逻辑，不能只是浮着",
            "尺度要有参照物，否则宏大只会变成空洞",
        ),
        fixtures=("建筑构件与材质语言全图统一、符文或法阵、自然与人造的交接处",),
        light=("超自然光源必须画出发光体本身，并在周围表面留下对应的受光与投影",),
        cues=("世界观的材质语言（石构 / 木构 / 水晶 / 有机体）只选一种为主",),
        pitfalls=(
            "光效浮在画面上，没有照亮任何实体表面",
            "材质语言混搭：哥特石构配科幻金属",
            "悬浮物没有任何支撑或能量暗示",
        ),
    ),
    SceneSpaceSkill(
        key="underwater",
        label="水下 / 深海",
        anchor=_FICTION,
        keywords=("水下", "深海", "海底", "潜水", "沉船", "海沟"),
        structure=("深度决定一切：水面是否可见、地形起伏、沉船或结构的坐底姿态",),
        fixtures=("悬浮颗粒、海藻与珊瑚、沉积物、气泡、人造光源或潜水器",),
        light=(
            "深度决定色衰减：红色最先消失，越深越偏青蓝",
            "光柱只在近水面成立；深海只有人造光源，照射范围外迅速转黑",
            "水中散射让远处物体迅速失去对比",
        ),
        cues=("深度与光源类型是这个空间唯一要锁定的两件事",),
        pitfalls=(
            "深海画成清澈无衰减、能看到很远",
            "百米深处还有太阳光柱",
            "悬浮颗粒缺失，水看起来像空气",
        ),
    ),
    # ------------------------------------------------------------------ 兜底
    SceneSpaceSkill(
        key="generic",
        label="其他 / 说不准",
        anchor=_REAL,
        keywords=(),
        structure=(
            "先说清这是室内还是室外、空间的边界在哪、视线的尽头是什么",
            "遮挡物与被遮挡的部分必须交代清楚",
        ),
        fixtures=("只写用户已经提到的陈设，并给每一件材质与状态",),
        light=("写清主光来自哪里、什么色温、在哪些表面上留下影子",),
        cues=("至少给出年代或地域中的一项，否则模型会随机挑一个",),
        pitfalls=("空间边界不明导致模型自行发挥", "陈设堆砌盖过空间本身"),
    ),
)

_BY_KEY: dict[str, SceneSpaceSkill] = {skill.key: skill for skill in SCENE_SPACE_SKILLS}
GENERIC_SKILL = _BY_KEY["generic"]


def all_skills() -> tuple[SceneSpaceSkill, ...]:
    return SCENE_SPACE_SKILLS


def get_skill(key: str) -> SceneSpaceSkill | None:
    return _BY_KEY.get(key.strip()) if key else None


def resolve_scene_skill(prompt: str, answer: str | None = None) -> SceneSpaceSkill:
    """The pack this plate polishes against.

    An explicit answer to the coach's own "which space is this" question wins
    over keyword matching — the author looking at the option list knows which
    of two plausible packs they meant, and re-deriving it from the text would
    silently override them on the next round.
    """
    chosen = get_skill(answer or "")
    if chosen is not None:
        return chosen

    text = prompt or ""
    best: SceneSpaceSkill | None = None
    best_hits = 0
    for skill in SCENE_SPACE_SKILLS:
        hits = sum(1 for keyword in skill.keywords if keyword in text)
        if hits > best_hits:
            best, best_hits = skill, hits
    return best or GENERIC_SKILL


def as_payload(skill: SceneSpaceSkill) -> dict[str, Any]:
    """The pack as the scene coach reads it, inside the enhance user message."""
    return {
        "key": skill.key,
        "label": skill.label,
        "anchor": skill.anchor,
        "structure": list(skill.structure),
        "fixtures": list(skill.fixtures),
        "light": list(skill.light),
        "cues": list(skill.cues),
        "pitfalls": list(skill.pitfalls),
    }


def skill_options() -> list[dict[str, str]]:
    """The "which space is this" question's options, in declaration order."""
    return [{"value": skill.key, "label": skill.label} for skill in SCENE_SPACE_SKILLS]
