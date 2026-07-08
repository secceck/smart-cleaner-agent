"""
天气查询工具
使用中国天气网接口获取实时天气、预报和预警信息。
策略：静态映射表优先（快），搜索API兜底（全覆盖），无需 API Key。
"""
import json
import re
import time
from datetime import datetime
from typing import Optional

import requests
import urllib3
from langchain_core.tools import tool

from ..common.logger import get_logger

logger = get_logger(__name__)

# 禁用 SSL 验证警告（中国天气网 CDN 证书有时不匹配）
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ============================================================
# 静态城市代码映射表（常用城市，免网络查询）
# ============================================================
CITY_CODE_MAP: dict[str, str] = {
    # 直辖市
    "北京": "101010100", "北京市": "101010100", "beijing": "101010100",
    "上海": "101020100", "上海市": "101020100", "shanghai": "101020100",
    "天津": "101030100", "天津市": "101030100", "tianjin": "101030100",
    "重庆": "101040100", "重庆市": "101040100", "chongqing": "101040100",
    # 省会城市
    "广州": "101280101", "广州市": "101280101", "guangzhou": "101280101",
    "深圳": "101280601", "深圳市": "101280601", "shenzhen": "101280601",
    "杭州": "101210101", "杭州市": "101210101", "hangzhou": "101210101",
    "南京": "101190101", "南京市": "101190101", "nanjing": "101190101",
    "武汉": "101200101", "武汉市": "101200101", "wuhan": "101200101",
    "成都": "101270101", "成都市": "101270101", "chengdu": "101270101",
    "西安": "101110101", "西安市": "101110101", "xian": "101110101",
    "郑州": "101180101", "郑州市": "101180101", "zhengzhou": "101180101",
    "长沙": "101250101", "长沙市": "101250101", "changsha": "101250101",
    "济南": "101120101", "济南市": "101120101", "jinan": "101120101",
    "合肥": "101220101", "合肥市": "101220101", "hefei": "101220101",
    "福州": "101230101", "福州市": "101230101", "fuzhou": "101230101",
    "南昌": "101240101", "南昌市": "101240101", "nanchang": "101240101",
    "昆明": "101290101", "昆明市": "101290101", "kunming": "101290101",
    "贵阳": "101260101", "贵阳市": "101260101", "guiyang": "101260101",
    "南宁": "101300101", "南宁市": "101300101", "nanning": "101300101",
    "海口": "101310101", "海口市": "101310101", "haikou": "101310101",
    "石家庄": "101090101", "石家庄市": "101090101", "shijiazhuang": "101090101",
    "太原": "101100101", "太原市": "101100101", "taiyuan": "101100101",
    "沈阳": "101070101", "沈阳市": "101070101", "shenyang": "101070101",
    "长春": "101060101", "长春市": "101060101", "changchun": "101060101",
    "哈尔滨": "101050101", "哈尔滨市": "101050101", "haerbin": "101050101",
    "兰州": "101160101", "兰州市": "101160101", "lanzhou": "101160101",
    "西宁": "101150101", "西宁市": "101150101", "xining": "101150101",
    "乌鲁木齐": "101130101", "乌鲁木齐市": "101130101", "wulumuqi": "101130101",
    "呼和浩特": "101080101", "呼和浩特市": "101080101", "huhehaote": "101080101",
    "拉萨": "101140101", "拉萨市": "101140101", "lasa": "101140101",
    "银川": "101170101", "银川市": "101170101", "yinchuan": "101170101",
    # 常见地级市
    "苏州": "101190401", "苏州市": "101190401", "suzhou": "101190401",
    "无锡": "101190201", "无锡市": "101190201", "wuxi": "101190201",
    "宁波": "101210401", "宁波市": "101210401", "ningbo": "101210401",
    "青岛": "101120201", "青岛市": "101120201", "qingdao": "101120201",
    "大连": "101070201", "大连市": "101070201", "dalian": "101070201",
    "厦门": "101230201", "厦门市": "101230201", "xiamen": "101230201",
    "珠海": "101280701", "珠海市": "101280701", "zhuhai": "101280701",
    "东莞": "101281601", "东莞市": "101281601", "dongguan": "101281601",
    "佛山": "101280801", "佛山市": "101280801", "foshan": "101280801",
    "温州": "101210701", "温州市": "101210701", "wenzhou": "101210701",
    "三亚": "101310201", "三亚市": "101310201", "sanya": "101310201",
    "桂林": "101300501", "桂林市": "101300501", "guilin": "101300501",
    "洛阳": "101180901", "洛阳市": "101180901", "luoyang": "101180901",
    "烟台": "101120501", "烟台市": "101120501", "yantai": "101120501",
    "威海": "101121301", "威海市": "101121301", "weihai": "101121301",
}

# ============================================================
# 天气代码 → 中文描述
# ============================================================
WEATHER_CODE_MAP: dict[str, str] = {
    "d0": "☀️ 晴", "n0": "🌙 晴",
    "d1": "⛅ 多云", "n1": "☁️ 多云",
    "d2": "☁️ 阴", "n2": "☁️ 阴",
    "d3": "🌦️ 阵雨", "n3": "🌧️ 阵雨",
    "d4": "⛈️ 雷阵雨", "n4": "⛈️ 雷阵雨",
    "d5": "⛈️ 雷阵雨伴冰雹", "n5": "⛈️ 雷阵雨伴冰雹",
    "d6": "🌨️ 雨夹雪", "n6": "🌨️ 雨夹雪",
    "d7": "🌧️ 小雨", "n7": "🌧️ 小雨",
    "d8": "🌧️ 中雨", "n8": "🌧️ 中雨",
    "d9": "🌧️ 大雨", "n9": "🌧️ 大雨",
    "d10": "🌧️ 暴雨", "n10": "🌧️ 暴雨",
    "d11": "🌧️ 大暴雨", "n11": "🌧️ 大暴雨",
    "d12": "🌧️ 特大暴雨", "n12": "🌧️ 特大暴雨",
    "d13": "❄️ 阵雪", "n13": "❄️ 阵雪",
    "d14": "❄️ 小雪", "n14": "❄️ 小雪",
    "d15": "❄️ 中雪", "n15": "❄️ 中雪",
    "d16": "❄️ 大雪", "n16": "❄️ 大雪",
    "d17": "❄️ 暴雪", "n17": "❄️ 暴雪",
    "d18": "🌫️ 雾", "n18": "🌫️ 雾",
    "d19": "🌧️ 冻雨", "n19": "🌧️ 冻雨",
    "d20": "💨 沙尘暴", "n20": "💨 沙尘暴",
    "d21": "🌧️ 小到中雨", "n21": "🌧️ 小到中雨",
    "d22": "🌧️ 中到大雨", "n22": "🌧️ 中到大雨",
    "d23": "🌧️ 大到暴雨", "n23": "🌧️ 大到暴雨",
    "d24": "🌧️ 暴雨到大暴雨", "n24": "🌧️ 暴雨到大暴雨",
    "d25": "🌧️ 大暴雨到特大暴雨", "n25": "🌧️ 大暴雨到特大暴雨",
    "d26": "❄️ 小到中雪", "n26": "❄️ 小到中雪",
    "d27": "❄️ 中到大雪", "n27": "❄️ 中到大雪",
    "d28": "❄️ 大到暴雪", "n28": "❄️ 大到暴雪",
    "d29": "🌫️ 浮尘", "n29": "🌫️ 浮尘",
    "d30": "💨 扬沙", "n30": "💨 扬沙",
    "d31": "💨 强沙尘暴", "n31": "💨 强沙尘暴",
}

ALERT_LEVEL_COLORS: dict[str, str] = {
    "蓝色": "🔵", "黄色": "🟡", "橙色": "🟠", "红色": "🔴",
}


# ============================================================
# 城市代码解析（静态 + 动态）
# ============================================================

def _search_city_code(city: str) -> Optional[str]:
    """
    通过中国天气网搜索接口动态查询城市代码。
    接口: http://toy1.weather.com.cn/search?cityname=城市名
    返回格式: jsonp([{"ref":"101201501~hubei~天门~Tianmen~..."}])
    """
    try:
        url = f"http://toy1.weather.com.cn/search?cityname={city}"
        headers = _build_headers()
        resp = requests.get(url, headers=headers, timeout=8)
        resp.encoding = "utf-8"

        if resp.status_code != 200:
            logger.warning(f"城市搜索接口返回 {resp.status_code}")
            return None

        # 提取所有 ref 字段
        refs = re.findall(r'"ref":"([^"]+)"', resp.text)
        if not refs:
            logger.info(f"未搜索到城市: {city}")
            return None

        # 解析 ref: sid~province~city_cn~city_en~...
        results = []
        for ref in refs:
            parts = ref.split("~")
            if len(parts) < 3:
                continue
            sid, province, city_cn = parts[0], parts[1], parts[2]
            # 过滤景点（sid 含 'A'）和街道
            is_scenic = "A" in sid
            results.append({"sid": sid, "city": city_cn, "province": province, "scenic": is_scenic})

        if not results:
            return None

        # 优先选非景点的精确匹配
        exact = [r for r in results if not r["scenic"] and r["city"] == city]
        if exact:
            return exact[0]["sid"]

        # 其次非景点的模糊匹配
        non_scenic = [r for r in results if not r["scenic"]]
        if non_scenic:
            return non_scenic[0]["sid"]

        # 最后兜底
        return results[0]["sid"]

    except requests.RequestException as e:
        logger.error(f"搜索城市代码失败: {e}")
        return None


def _resolve_city_code(city: str) -> Optional[str]:
    """
    解析城市代码，静态映射优先（快），搜索API兜底（全覆盖）。
    """
    # 1. 静态映射精确匹配
    if city in CITY_CODE_MAP:
        return CITY_CODE_MAP[city]

    # 2. 去掉"市"后缀再匹配
    clean = city.rstrip("市")
    if clean in CITY_CODE_MAP:
        return CITY_CODE_MAP[clean]

    # 3. 静态表模糊匹配
    city_lower = city.lower()
    for name, code in CITY_CODE_MAP.items():
        if city_lower in name.lower() or name.lower() in city_lower:
            return code

    # 4. 动态搜索（网络请求，有缓存价值）
    logger.info(f"静态表未命中，动态搜索: {city}")
    return _search_city_code(city)


# ============================================================
# 请求工具
# ============================================================

def _build_headers() -> dict:
    """构建浏览器请求头"""
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/150.0.0.0 Safari/537.36"
        ),
        "Referer": "https://www.weather.com.cn/",
        "Accept": "*/*",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }


def _get_weather_emoji(code: str) -> str:
    return WEATHER_CODE_MAP.get(code, f"未知({code})")


def _parse_js_var(text: str, var_pattern: str) -> Optional[dict]:
    """
    解析 JS 赋值: var xxx ={json};
    var_pattern 形如 'dataSK', 'cityDZ', 'alarmDZ'
    """
    # 匹配 var dataSK ={...}; 或 var cityDZ101200101 ={...};
    pattern = rf'var\s+{re.escape(var_pattern)}\w*\s*=\s*(\{{.*?\}});'
    match = re.search(pattern, text, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return None


# ============================================================
# 中国天气网接口（双 API 互补）
# ============================================================
# weather_index: 实时观测(dataSK) + 预警(alarmDZ)，但 cityDZ 早8点才更新今日预报
# dingzhi:       预报(cityDZ) 更新更快（前晚18点即有今日预报）
WEATHER_INDEX_URL = "https://d1.weather.com.cn/weather_index/{city_code}.html"
WEATHER_DINGZHI_URL = "https://d1.weather.com.cn/dingzhi/{city_code}.html"


def _fetch_weather_data(city_code: str) -> dict:
    """
    从中国天气网获取完整天气数据。
    策略: weather_index 取实时观测+预警, dingzhi 取最新预报。
    """
    timestamp = int(time.time() * 1000)
    headers = _build_headers()

    # ================================================================
    # 1. 获取 weather_index（实时数据 + 预警）
    # ================================================================
    url_wi = WEATHER_INDEX_URL.format(city_code=city_code) + f"?_={timestamp}"
    sk_data = None
    alarm_data_wi = None
    dz_data_wi = None

    try:
        resp = requests.get(url_wi, headers=headers, verify=False, timeout=10)
        resp.encoding = "utf-8"
        if resp.status_code == 200 and resp.text.strip():
            sk_data = _parse_js_var(resp.text, "dataSK")
            alarm_data_wi = _parse_js_var(resp.text, "alarmDZ")
            dz_data_wi = _parse_js_var(resp.text, "cityDZ")
    except requests.RequestException as e:
        logger.warning(f"weather_index 请求失败: {e}")

    # ================================================================
    # 2. 获取 dingzhi（最新预报，更新频率更高）
    # ================================================================
    url_dz = WEATHER_DINGZHI_URL.format(city_code=city_code) + f"?_={timestamp}"
    dz_data_dz = None
    alarm_data_dz = None

    try:
        resp = requests.get(url_dz, headers=headers, verify=False, timeout=10)
        resp.encoding = "utf-8"
        if resp.status_code == 200 and resp.text.strip():
            dz_data_dz = _parse_js_var(resp.text, "cityDZ")
            alarm_data_dz = _parse_js_var(resp.text, "alarmDZ")
    except requests.RequestException as e:
        logger.warning(f"dingzhi 请求失败: {e}")

    # ================================================================
    # 3. 解析实时观测数据（来自 weather_index 的 dataSK）
    # ================================================================
    realtime: dict = {}
    if sk_data:
        realtime = {
            "temp": sk_data.get("temp", ""),
            "humidity": sk_data.get("SD", ""),
            "wind_direction": sk_data.get("WD", ""),
            "wind_speed": sk_data.get("WS", ""),
            "wind_speed_kmh": sk_data.get("wse", ""),
            "pressure": sk_data.get("qy", ""),
            "weather": sk_data.get("weather", ""),
            "rain": sk_data.get("rain", "0"),
            "rain_24h": sk_data.get("rain24h", "0"),
            "aqi": sk_data.get("aqi", ""),
            "aqi_pm25": sk_data.get("aqi_pm25", ""),
            "visibility": sk_data.get("njd", ""),
            "city_name": sk_data.get("cityname", ""),
            "time": sk_data.get("time", ""),            # 观测时间 HH:MM
            "date": sk_data.get("date", ""),            # "07月09日(星期四)"
        }

    # ================================================================
    # 4. 选择最新预报（dingzhi 优先，因为它的更新频率更高）
    #    weather_index 的 cityDZ 只在 08:00 和 20:00 左右更新
    #    dingzhi 的 cityDZ 更新更及时（前一天 18:00 即发布次日预报）
    # ================================================================
    forecast: dict = {}
    # 比较两个接口的 fctime，取较新的
    fctime_wi = ""
    fctime_dz = ""
    if dz_data_wi:
        fctime_wi = dz_data_wi.get("weatherinfo", {}).get("fctime", "")
    if dz_data_dz:
        fctime_dz = dz_data_dz.get("weatherinfo", {}).get("fctime", "")

    # 选 fctime 更大的（更新的预报）
    best_dz = dz_data_dz
    if fctime_wi > fctime_dz:
        best_dz = dz_data_wi
        logger.debug(f"预报来源: weather_index (fctime={fctime_wi})")
    else:
        logger.debug(f"预报来源: dingzhi (fctime={fctime_dz})")

    if best_dz:
        info = best_dz.get("weatherinfo", {})
        day_code = info.get("weathercode", "")
        night_code = info.get("weathercoden", "")
        forecast = {
            "city_name": info.get("cityname") or info.get("city", ""),
            "temp_high": info.get("temp", ""),
            "temp_low": info.get("tempn", ""),
            "weather": info.get("weather", ""),
            "weather_day": _get_weather_emoji(day_code),
            "weather_night": _get_weather_emoji(night_code),
            "wind_direction": info.get("wd", ""),
            "wind_speed": info.get("ws", ""),
            "fctime": info.get("fctime", ""),
        }

    # ================================================================
    # 5. 解析预警（两个接口的预警合并去重）
    # ================================================================
    alarms = []
    seen_titles = set()
    for ad in [alarm_data_wi, alarm_data_dz]:
        if not ad:
            continue
        for w in ad.get("w", []):
            level = w.get("w7", "")
            title = w.get("w13", "")
            if title in seen_titles:
                continue
            seen_titles.add(title)
            alarms.append({
                "type": w.get("w5", ""),
                "level": level,
                "level_icon": ALERT_LEVEL_COLORS.get(level, "⚠️"),
                "title": title,
                "desc": w.get("w9", ""),
                "time": w.get("w8", ""),
            })

    # ================================================================
    # 6. 返回
    # ================================================================
    if not realtime and not forecast:
        logger.warning(f"城市 {city_code} 未解析到任何天气数据")
        return {}

    return {
        "source": "中国天气网",
        "city_code": city_code,
        "realtime": realtime,
        "forecast": forecast,
        "alarms": alarms,
    }


# ============================================================
# LangChain 工具
# ============================================================

def _aqi_description(aqi: str) -> str:
    """AQI 数值 → 等级描述"""
    try:
        val = int(aqi)
    except (ValueError, TypeError):
        return ""
    if val <= 50:
        return "优"
    elif val <= 100:
        return "良"
    elif val <= 150:
        return "轻度污染"
    elif val <= 200:
        return "中度污染"
    elif val <= 300:
        return "重度污染"
    else:
        return "严重污染"


@tool
def weather_query(city: str) -> str:
    """
    查询指定城市的实时天气、预报和气象预警信息。
    返回当前温度、湿度、风力风向、AQI空气质量、降雨量、未来预报、预警等。

    使用场景：
    - 用户询问今天是否适合清扫
    - 需要结合天气给清扫建议
    - 生成清扫报告时需要环境天气数据
    - 关注气象预警（大风/雷电/暴雨等）判断是否安全

    Args:
        city: 城市名称，例如"北京"、"天门"、"恩施"。支持任意中国城市名。
    """
    if not city or not city.strip():
        return "❌ 请提供要查询的城市名称，例如：weather_query('天门')"

    city = city.strip()

    # 解析城市代码（静态表 → 动态搜索）
    city_code = _resolve_city_code(city)
    if not city_code:
        return (
            f"❌ 未找到城市「{city}」的天气代码。\n\n"
            f"请确认城市名称是否正确，或尝试使用标准城市名。\n"
            f"例如：北京、武汉、天门、恩施..."
        )

    logger.info(f"查询天气: city={city}, code={city_code}")

    # 获取天气数据
    data = _fetch_weather_data(city_code)

    if not data:
        return f"❌ 获取「{city}」的天气数据失败，请稍后重试。"

    realtime = data.get("realtime", {})
    forecast = data.get("forecast", {})
    alarms = data.get("alarms", [])

    # 城市名：优先用实时数据中的
    city_name = realtime.get("city_name") or forecast.get("city_name") or city

    # === 组装输出 ===
    # 优先使用 dataSK 返回的官方日期（与 weather.com.cn 网页一致）
    official_date = realtime.get("date", "")  # "07月09日(星期四)"
    if official_date:
        # 提取中文日期部分
        today_str = official_date.split("(")[0] if "(" in official_date else official_date
        # 补全年份
        if "年" not in today_str:
            today_str = datetime.now().strftime("%Y年") + today_str
    else:
        today_str = datetime.now().strftime("%Y年%m月%d日")

    lines = [f"## 🌤️ {city_name} 天气信息"]
    lines.append(f"> 📅 预报日期: **{today_str}**（与 weather.com.cn 同步）| 数据源: {data.get('source', '')}")
    lines.append("")

    # --- 实时天气 ---
    if realtime:
        obs_time = realtime.get("time", "")
        lines.append(f"### 📍 实时观测" + (f" ({obs_time}发布)" if obs_time else ""))
        lines.append("")
        lines.append("| 指标 | 数值 |")
        lines.append("|------|------|")
        lines.append(f"| 🌡️ 当前温度 | **{realtime.get('temp', 'N/A')}℃** |")
        humidity = realtime.get('humidity', '').rstrip('%')
        lines.append(f"| 💧 湿度 | **{humidity}%** |")

        wind = f"{realtime.get('wind_direction', '')} {realtime.get('wind_speed', '')}".strip()
        if realtime.get("wind_speed_kmh"):
            wind += f" ({realtime['wind_speed_kmh']})"
        lines.append(f"| 🌬️ 风力风向 | **{wind}** |")

        lines.append(f"| 🌍 天气现象 | **{realtime.get('weather', 'N/A')}** |")

        if realtime.get("pressure"):
            lines.append(f"| 🎈 气压 | **{realtime['pressure']} hPa** |")

        # 空气质量
        aqi = realtime.get("aqi", "")
        if aqi:
            aqi_desc = _aqi_description(aqi)
            lines.append(f"| 🍃 AQI | **{aqi}** ({aqi_desc}) |")
        pm25 = realtime.get("aqi_pm25", "")
        if pm25:
            lines.append(f"| 🍃 PM2.5 | **{pm25}** μg/m³ |")

        # 降雨
        rain = realtime.get("rain", "0")
        rain24 = realtime.get("rain_24h", "0")
        if rain != "0" or rain24 != "0":
            lines.append(f"| 🌧️ 降雨量 | 当前 {rain}mm / 24h {rain24}mm |")

        if realtime.get("visibility"):
            lines.append(f"| 👁️ 能见度 | **{realtime['visibility']}** |")

        lines.append("")

    # --- 预报 ---
    if forecast:
        fctime = forecast.get("fctime", "")
        fctime_display = ""
        if len(fctime) == 12:
            fctime_display = f"{fctime[4:6]}-{fctime[6:8]} {fctime[8:10]}:{fctime[10:12]}"

        lines.append(f"### 📅 今日预报")
        if fctime_display:
            lines.append(f"> 预报发布时间: {fctime_display}（预报内容为{today_str}）")
        lines.append("")
        lines.append("| 指标 | 详情 |")
        lines.append("|------|------|")
        temp_high = forecast.get('temp_high', '').replace('999', '--')
        temp_low = forecast.get('temp_low', '').replace('999', '--')
        lines.append(f"| 🌡️ 温度 | **{temp_high} / {temp_low}** |")
        lines.append(f"| 🌍 天气 | **{forecast.get('weather', 'N/A')}** |")
        lines.append(f"| ☀️ 白天 | {forecast.get('weather_day', 'N/A')} |")
        lines.append(f"| 🌙 夜间 | {forecast.get('weather_night', 'N/A')} |")
        lines.append(f"| 🌬️ 风向 | **{forecast.get('wind_direction', 'N/A')}** |")
        lines.append(f"| 💨 风力 | **{forecast.get('wind_speed', 'N/A')}** |")
        lines.append("")

    # --- 预警 ---
    if alarms:
        lines.append("### ⚠️ 气象预警")
        lines.append("")
        for i, alarm in enumerate(alarms, 1):
            icon = alarm.get("level_icon", "⚠️")
            lines.append(f"**{icon} 预警 {i}：{alarm.get('type', '')}{alarm.get('level', '')}预警**")
            lines.append(f"- 标题: {alarm.get('title', '')}")
            lines.append(f"- 时间: {alarm.get('time', '')}")
            if alarm.get("desc"):
                lines.append(f"- 详情: {alarm['desc']}")
            lines.append("")
    else:
        lines.append("### ✅ 气象预警")
        lines.append("")
        lines.append("> 当前无气象预警")
        lines.append("")

    # --- 清扫建议 ---
    lines.append("### 🧹 清扫建议")
    lines.append("")

    weather_text = forecast.get("weather", "") or realtime.get("weather", "")
    wind_text = forecast.get("wind_speed", "")
    aqi_val = realtime.get("aqi", "")

    bad_weather_kw = ["暴雨", "大雨", "雷阵雨", "暴雪", "大雪", "沙尘暴", "台风"]
    bad_wind_kw = ["5-6级", "6-7级", "7-8级", "8-9级", "9-10级", "10级以上"]
    caution_weather_kw = ["中雨", "小雨", "阵雨", "雨夹雪", "冻雨", "雾", "霾", "扬沙"]

    is_bad_weather = any(kw in weather_text for kw in bad_weather_kw)
    is_bad_wind = any(kw in wind_text for kw in bad_wind_kw)
    is_caution = any(kw in weather_text for kw in caution_weather_kw)

    # 空气质量警告
    try:
        aqi_int = int(aqi_val)
        is_bad_air = aqi_int > 150
    except (ValueError, TypeError):
        is_bad_air = False

    if alarms:
        alarm_types = [a.get("type", "") for a in alarms]
        lines.append(f"> ⚠️ 当前有**{', '.join(alarm_types)}**预警，建议暂停室外清扫，注意安全！")
    elif is_bad_weather:
        lines.append(f"> ❌ 今日天气恶劣（{weather_text}），**不建议**进行室外清扫。")
    elif is_bad_wind:
        lines.append(f"> ⚠️ 今日风力较大（{wind_text}），室外清扫请注意安全。")
    elif is_bad_air:
        lines.append(f"> ⚠️ 今日空气质量较差（AQI {aqi_val}），建议减少户外活动，清扫时佩戴口罩。")
    elif is_caution:
        lines.append(f"> 🌧️ 今日有降水可能（{weather_text}），建议趁间隙清扫，或改为室内清扫。")
    else:
        lines.append(f"> ✅ 今日天气适合清扫！{weather_text}，风力{wind_text}，条件良好。")

    return "\n".join(lines)
