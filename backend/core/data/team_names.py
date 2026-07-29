"""球队名称映射 — 中文竞彩缩写 → 英文标准名。

覆盖英超/西甲/德甲/意甲/法甲/荷甲/葡超/苏超主要球队。
"""
from __future__ import annotations

import difflib

# 中文竞彩缩写（含常见别名）→ 英文标准名
_MAPPING: dict[str, str] = {
    # 英超
    "曼城": "Man City",
    "曼联": "Man United",
    "利物浦": "Liverpool",
    "阿森纳": "Arsenal",
    "切尔西": "Chelsea",
    "热刺": "Spurs",
    "托特纳姆热刺": "Spurs",
    "纽卡": "Newcastle",
    "纽卡斯尔": "Newcastle",
    "阿斯顿维拉": "Aston Villa",
    "维拉": "Aston Villa",
    "西汉姆": "West Ham",
    "布莱顿": "Brighton",
    "伯恩利": "Burnley",
    "埃弗顿": "Everton",
    "富勒姆": "Fulham",
    "布伦特福德": "Brentford",
    "谢菲联": "Sheffield Utd",
    "卢顿": "Luton",
    "狼队": "Wolves",
    "水晶宫": "Crystal Palace",
    "森林": "Nottm Forest",
    "诺丁汉森林": "Nottm Forest",
    "伯恩茅斯": "Bournemouth",
    "莱斯特": "Leicester",
    "南安普顿": "Southampton",
    "伊普斯维奇": "Ipswich",
    "曼斯菲尔德": "Mansfield",
    "曼城女足": "Man City Women",
    # 西甲
    "皇马": "Real Madrid",
    "巴萨": "Barcelona",
    "马竞": "Ath Madrid",
    "马德里竞技": "Ath Madrid",
    "塞维利亚": "Sevilla",
    "毕尔巴鄂竞技": "Ath Bilbao",
    "毕巴": "Ath Bilbao",
    "皇家社会": "Real Sociedad",
    "贝蒂斯": "Betis",
    "瓦伦西亚": "Valencia",
    "维拉雷亚尔": "Villarreal",
    "黄潜": "Villarreal",
    "奥萨苏纳": "Osasuna",
    "赫罗纳": "Girona",
    "赫塔费": "Getafe",
    "阿拉维斯": "Alaves",
    "拉斯帕尔马斯": "Las Palmas",
    "西班牙人": "Espanol",
    "马洛卡": "Mallorca",
    "莱加内斯": "Leganes",
    "巴利亚多利德": "Valladolid",
    "赫雷斯": "Jerez",
    "塞尔塔": "Celta",
    "拉科鲁尼亚": "La Coruna",
    "努曼西亚": "Numancia",
    # 德甲
    "拜仁": "Bayern Munich",
    "拜仁慕尼黑": "Bayern Munich",
    "多特": "Dortmund",
    "多特蒙德": "Dortmund",
    "莱比锡": "RB Leipzig",
    "柏林联": "Union Berlin",
    "法兰克福": "Ein Frankfurt",
    "勒沃库森": "Bayer Leverkusen",
    "弗赖堡": "Freiburg",
    "狼堡": "Wolfsburg",
    "门兴格拉德巴赫": "M'gladbach",
    "门兴": "M'gladbach",
    "美因茨": "Mainz",
    "奥格斯堡": "Augsburg",
    "霍芬海姆": "Hoffenheim",
    "科隆": "Cologne",
    "波鸿": "Bochum",
    "柏林赫塔": "Hertha",
    "斯图加特": "Stuttgart",
    "不来梅": "Werder Bremen",
    "汉堡": "Hamburg",
    "汉诺威": "Hannover",
    "达姆施塔特": "Darmstadt",
    "海登海姆": "Heidenheim",
    "基尔": "Holstein Kiel",
    "圣保利": "St Pauli",
    # 意甲
    "尤文": "Juventus",
    "尤文图斯": "Juventus",
    "国际米兰": "Inter",
    "国米": "Inter",
    "ac米兰": "AC Milan",
    "米兰": "AC Milan",
    "罗马": "Roma",
    "拉齐奥": "Lazio",
    "那不勒斯": "Napoli",
    "弗洛伦蒂纳": "Fiorentina",
    "紫百合": "Fiorentina",
    "博洛尼亚": "Bologna",
    "亚特兰大": "Atalanta",
    "萨索罗": "Sassuolo",
    "托里诺": "Torino",
    "恩波利": "Empoli",
    "维罗纳": "Verona",
    "萨勒尼塔纳": "Salernitana",
    "热那亚": "Genoa",
    "卡利亚里": "Cagliari",
    "弗罗西诺内": "Frosinone",
    "乌迪内斯": "Udinese",
    "莫扎": "Monza",
    "勒切": "Lecce",
    "帕尔马": "Parma",
    "科莫": "Como",
    "威尼斯": "Venezia",
    # 法甲
    "巴黎圣日耳曼": "Paris SG",
    "巴黎": "Paris SG",
    "马赛": "Marseille",
    "里昂": "Lyon",
    "摩纳哥": "Monaco",
    "雷恩": "Rennes",
    "里尔": "Lille",
    "斯特拉斯堡": "Strasbourg",
    "蒙彼利埃": "Montpellier",
    "尼斯": "Nice",
    "圣埃蒂安": "St Etienne",
    "图卢兹": "Toulouse",
    "南特": "Nantes",
    "兰斯": "Reims",
    "布雷斯特": "Brest",
    "昂热": "Angers",
    "勒阿弗尔": "Le Havre",
    "格勒诺布尔": "Grenoble",
    # 荷甲
    "阿贾克斯": "Ajax",
    "费耶诺德": "Feyenoord",
    "埃因霍温": "Eindhoven",
    "格罗宁根": "Groningen",
    "特温特": "Twente",
    "阿尔克马尔": "AZ Alkmaar",
    "马斯特里赫特": "Maastricht",
    "乌得勒支": "Utrecht",
    # 葡超
    "本菲卡": "Benfica",
    "波尔图": "Porto",
    "体育里斯本": "Sporting CP",
    "体育": "Sporting CP",
    "布拉加": "Braga",
    "葡萄牙维多利亚": "Vit Guimaraes",
    # 欧洲杯/世界杯国家队
    "法国": "France",
    "德国": "Germany",
    "西班牙": "Spain",
    "意大利": "Italy",
    "英格兰": "England",
    "荷兰": "Netherlands",
    "葡萄牙": "Portugal",
    "比利时": "Belgium",
    "阿根廷": "Argentina",
    "巴西": "Brazil",
    "克罗地亚": "Croatia",
    "丹麦": "Denmark",
    "瑞士": "Switzerland",
    "波兰": "Poland",
    "乌克兰": "Ukraine",
    "捷克": "Czech Republic",
    "奥地利": "Austria",
    "瑞典": "Sweden",
    "匈牙利": "Hungary",
    "土耳其": "Turkey",
    "塞尔维亚": "Serbia",
    "罗马尼亚": "Romania",
    "斯洛伐克": "Slovakia",
    "苏格兰": "Scotland",
    "美国": "USA",
    "墨西哥": "Mexico",
    "日本": "Japan",
    "韩国": "South Korea",
    "澳大利亚": "Australia",
    "摩洛哥": "Morocco",
    "塞内加尔": "Senegal",
}

# 反向映射：英文 → 中文（用于显示）
_REVERSE: dict[str, str] = {v.lower(): k for k, v in _MAPPING.items()}


def resolve_to_english(chinese_name: str) -> str | None:
    """将中文球队名映射为英文标准名，找不到返回 None。"""
    name = chinese_name.strip()
    if name in _MAPPING:
        return _MAPPING[name]
    # 尝试不区分大小写
    for k, v in _MAPPING.items():
        if k.lower() == name.lower():
            return v
    return None


def fuzzy_match_english(chinese_name: str, candidates: list[str]) -> str | None:
    """先尝试精确映射，找不到用 difflib 做模糊匹配（截止分数 0.6）。"""
    exact = resolve_to_english(chinese_name)
    if exact:
        # 在候选列表中找最接近的
        lower_candidates = [c.lower() for c in candidates]
        if exact.lower() in lower_candidates:
            return candidates[lower_candidates.index(exact.lower())]
        # 模糊匹配 exact 结果
        matches = difflib.get_close_matches(exact.lower(), lower_candidates, n=1, cutoff=0.6)
        if matches:
            return candidates[lower_candidates.index(matches[0])]

    # 直接对中文名做模糊匹配（适用于部分英文名直接对应的情况）
    lower_candidates = [c.lower() for c in candidates]
    matches = difflib.get_close_matches(chinese_name.lower(), lower_candidates, n=1, cutoff=0.5)
    if matches:
        return candidates[lower_candidates.index(matches[0])]
    return None
