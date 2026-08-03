"""天气查询工具 - 基于 wttr.in 免费 API，支持中文地名，无需 API Key

功能:
    - 查询实时天气 + 未来3天预报
    - 支持中文地名（如「重庆渝北」「巴厘岛」）
    - 返回格式化的中文天气描述

API:
    wttr.in: https://wttr.in/{location}?format=j1&lang=zh
    备选 Open-Meteo: https://api.open-meteo.com/v1/forecast
"""

import json
import time
import urllib.parse
import urllib.request
from typing import Optional, Dict, Any, List

from utils.set_logger import get_logger

logger = get_logger()

# 常见中文地名 -> 英文别名（wttr.in 对部分中文名支持不佳）
_LOCATION_ALIASES: Dict[str, str] = {
    "巴厘岛": "Bali",
    "巴厘": "Bali",
    "北京": "Beijing",
    "上海": "Shanghai",
    "广州": "Guangzhou",
    "深圳": "Shenzhen",
    "成都": "Chengdu",
    "杭州": "Hangzhou",
    "西安": "Xian",
    "武汉": "Wuhan",
    "南京": "Nanjing",
    "天津": "Tianjin",
    "重庆": "Chongqing",
    "青岛": "Qingdao",
    "大连": "Dalian",
    "厦门": "Xiamen",
    "昆明": "Kunming",
    "三亚": "Sanya",
    "海口": "Haikou",
    "拉萨": "Lhasa",
    "香港": "Hong Kong",
    "澳门": "Macau",
    "台北": "Taipei",
    "东京": "Tokyo",
    "首尔": "Seoul",
    "新加坡": "Singapore",
    "曼谷": "Bangkok",
    "巴黎": "Paris",
    "伦敦": "London",
    "纽约": "New York",
    "洛杉矶": "Los Angeles",
}

# wttr.in 天气代码 -> 中文描述（备用，wttr.in 自带中文翻译）
_WTTR_CODE_MAP: Dict[str, str] = {
    "113": "晴", "116": "多云", "119": "阴", "122": "阴天",
    "143": "薄雾", "176": "小阵雨", "179": "小阵雪",
    "182": "雨夹雪", "185": "冻毛毛雨",
    "200": "雷阵雨", "227": "吹雪", "230": "暴风雪",
    "248": "雾", "260": "冻雾",
    "263": "小毛毛雨", "266": "毛毛雨",
    "281": "冻毛毛雨", "284": "强冻毛毛雨",
    "293": "小阵雨", "296": "小雨", "299": "中阵雨",
    "302": "中雨", "305": "大雨", "308": "暴雨",
    "311": "冻雨", "314": "强冻雨",
    "317": "雨夹雪", "320": "强雨夹雪",
    "323": "小阵雪", "326": "中雪", "329": "大雪",
    "332": "暴雪", "335": "大暴雪", "338": "特大暴雪",
    "350": "冰粒", "353": "小雨", "356": "中雨", "359": "暴雨",
    "362": "雨夹雪", "365": "强雨夹雪",
    "368": "小雪", "371": "大雪",
    "374": "冰粒", "377": "强冰粒",
    "386": "雷阵雨", "389": "强雷雨",
    "392": "雷阵雪", "395": "强雷雪",
}


def _wttr_desc(code: str) -> str:
    """将 wttr.in 天气代码转为中文描述"""
    return _WTTR_CODE_MAP.get(code, code)


class WeatherTool:
    """天气查询工具 - 供 LLM 函数调用使用"""

    # OpenAI function-calling schema
    SCHEMA = {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "查询指定地点的实时天气和未来3天预报。支持中文地名。",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": "地点名称，如「重庆渝北」「巴厘岛」「北京」",
                    }
                },
                "required": ["location"],
            },
        },
    }

    @staticmethod
    def _http_get_json(url: str, timeout: int = 15) -> Optional[Dict[str, Any]]:
        """发起 GET 请求并解析 JSON"""
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "curl/7.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            logger.error(f"HTTP 请求失败: {url[:100]} -> {e}")
            return None

    @staticmethod
    def _query_wttr(location: str) -> Optional[str]:
        """通过 wttr.in 查询天气（支持中文地名）"""
        encoded = urllib.parse.quote(location)
        url = f"https://wttr.in/{encoded}?format=j1&lang=zh"
        data = WeatherTool._http_get_json(url, timeout=15)
        if not data:
            return None

        lines: List[str] = []

        # 地点信息
        area = data.get("nearest_area", [{}])[0]
        area_name = area.get("areaName", [{}])[0].get("value", location) if area else location
        country = area.get("country", [{}])[0].get("value", "") if area else ""
        region = area.get("region", [{}])[0].get("value", "") if area else ""
        full_name = " ".join(p for p in [area_name, region, country] if p)
        lines.append(f"📍 {full_name}")

        # 实时天气
        cur_list = data.get("current_condition", [])
        if cur_list:
            cur = cur_list[0]
            temp = cur.get("temp_C", "?")
            feels = cur.get("FeelsLikeC", "?")
            humidity = cur.get("humidity", "?")
            wind = cur.get("windspeedKmph", "?")
            wcode = cur.get("weatherCode", "0")
            # 优先用 wttr.in 自带的中文描述
            zh_desc_list = cur.get("lang_zh", [])
            if zh_desc_list:
                desc = zh_desc_list[0].get("value", _wttr_desc(wcode))
            else:
                desc = _wttr_desc(wcode)
            lines.append(
                f"🌡️ 实时: {desc}，{temp}°C"
                f"（体感{feels}°C），湿度{humidity}%，风速{wind}km/h"
            )

        # 未来3天预报
        weather_list = data.get("weather", [])
        if weather_list:
            lines.append("📅 未来3天:")
            for w in weather_list[:3]:
                date = w.get("date", "?")
                tmax = w.get("maxtempC", "?")
                tmin = w.get("mintempC", "?")
                # 取中午时段的天气描述作为全天代表
                hourly = w.get("hourly", [])
                mid_desc = "?"
                if hourly and len(hourly) > 4:
                    mid = hourly[4]  # 12:00 的数据
                    mid_code = mid.get("weatherCode", "0")
                    zh_list = mid.get("lang_zh", [])
                    if zh_list:
                        mid_desc = zh_list[0].get("value", _wttr_desc(mid_code))
                    else:
                        mid_desc = _wttr_desc(mid_code)
                lines.append(f"  {date}: {mid_desc}，{tmin}~{tmax}°C")

        return "\n".join(lines) if len(lines) > 1 else None

    @staticmethod
    def _query_open_meteo(location: str) -> Optional[str]:
        """通过 Open-Meteo 查询天气（备选方案，用英文/拼音搜索）"""
        encoded = urllib.parse.quote(location)
        # 不加 language 参数，扩大搜索范围
        geo_url = (
            f"https://geocoding-api.open-meteo.com/v1/search"
            f"?name={encoded}&count=1&format=json"
        )
        geo_data = WeatherTool._http_get_json(geo_url, timeout=10)
        if not geo_data or not geo_data.get("results"):
            return None

        r = geo_data["results"][0]
        lat = r["latitude"]
        lon = r["longitude"]
        full_name = " ".join(
            p for p in [r.get("admin1", ""), r.get("name", location), r.get("country", "")]
            if p
        )

        weather_url = (
            f"https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat}&longitude={lon}"
            f"&current=temperature_2m,relative_humidity_2m,apparent_temperature,"
            f"weather_code,wind_speed_10m"
            f"&daily=weather_code,temperature_2m_max,temperature_2m_min"
            f"&timezone=auto&forecast_days=3"
        )
        data = WeatherTool._http_get_json(weather_url, timeout=10)
        if not data:
            return None

        # WMO 代码映射
        wmo_map = {
            0: "晴", 1: "大致晴朗", 2: "多云", 3: "阴天",
            45: "雾", 48: "冻雾",
            51: "小毛毛雨", 53: "毛毛雨", 55: "大毛毛雨",
            61: "小雨", 63: "中雨", 65: "大雨",
            71: "小雪", 73: "中雪", 75: "大雪",
            80: "小阵雨", 81: "阵雨", 82: "强阵雨",
            95: "雷暴", 96: "雷暴伴冰雹", 99: "强雷暴伴冰雹",
        }

        lines = [f"📍 {full_name}"]
        cur = data.get("current", {})
        if cur:
            temp = cur.get("temperature_2m", "?")
            feels = cur.get("apparent_temperature", "?")
            humidity = cur.get("relative_humidity_2m", "?")
            wind = cur.get("wind_speed_10m", "?")
            wcode = cur.get("weather_code", 0)
            desc = wmo_map.get(wcode, f"天气代码{wcode}")
            lines.append(
                f"🌡️ 实时: {desc}，{temp}°C"
                f"（体感{feels}°C），湿度{humidity}%，风速{wind}km/h"
            )

        daily = data.get("daily", {})
        if daily and daily.get("time"):
            lines.append("📅 未来3天:")
            dates = daily["time"]
            codes = daily.get("weather_code", [])
            tmax = daily.get("temperature_2m_max", [])
            tmin = daily.get("temperature_2m_min", [])
            for i, d in enumerate(dates):
                desc = wmo_map.get(codes[i], "?") if i < len(codes) else "?"
                hi = tmax[i] if i < len(tmax) else "?"
                lo = tmin[i] if i < len(tmin) else "?"
                lines.append(f"  {d}: {desc}，{lo}~{hi}°C")

        return "\n".join(lines) if len(lines) > 1 else None

    @staticmethod
    def get_weather(location: str) -> str:
        """查询指定地点的天气

        优先使用 wttr.in（支持中文地名），失败后尝试英文别名，
        最后回退 Open-Meteo geocoding。

        Args:
            location: 地点名称（中文或英文）

        Returns:
            格式化的天气描述字符串，查询失败返回错误提示
        """
        logger.info(f"天气查询: location={location}")

        # 构建候选搜索名列表：原名 + 英文别名
        candidates = [location]
        alias = _LOCATION_ALIASES.get(location.strip())
        if alias and alias != location:
            candidates.append(alias)

        for name in candidates:
            # 方案1: wttr.in（支持中文地名）
            result = WeatherTool._query_wttr(name)
            if result:
                logger.info(f"天气查询成功(wttr.in, name={name}): {result[:100]}")
                return result
            # wttr.in 失败后等1秒重试一次
            time.sleep(1)
            result = WeatherTool._query_wttr(name)
            if result:
                logger.info(f"天气查询成功(wttr.in重试, name={name}): {result[:100]}")
                return result

        # 方案2: Open-Meteo（备选，用所有候选名尝试）
        for name in candidates:
            result = WeatherTool._query_open_meteo(name)
            if result:
                logger.info(f"天气查询成功(open-meteo, name={name}): {result[:100]}")
                return result

        logger.warning(f"天气查询失败: {location}")
        return f"未找到地点「{location}」的天气信息，请确认地名是否正确。"
