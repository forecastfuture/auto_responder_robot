"""天气查询工具测试

测试项:
    1. 重庆渝北 天气查询 - 验证返回包含温度、天气描述等关键信息
    2. 巴厘岛 天气查询 - 验证国际地点也能正常查询
    3. 工具 schema 格式校验
    4. 不存在的地点返回友好提示

运行: python -m pytest tests/test_weather.py -v -s
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.weather import WeatherTool


def test_chongqing_yubei_weather():
    """测试重庆渝北天气查询"""
    result = WeatherTool.get_weather("重庆渝北")
    print(f"\n--- 重庆渝北天气 ---\n{result}\n")
    assert result, "天气查询返回空"
    assert "°C" in result, "结果中应包含温度信息"
    # 应该包含地点信息
    assert any(kw in result for kw in ["渝北", "重庆", "Chongqing"]), "结果中应包含地点名称"


def test_bali_weather():
    """测试巴厘岛天气查询"""
    result = WeatherTool.get_weather("巴厘岛")
    print(f"\n--- 巴厘岛天气 ---\n{result}\n")
    assert result, "天气查询返回空"
    assert "°C" in result, "结果中应包含温度信息"
    # 应该包含地点信息
    assert any(kw in result for kw in ["Bali", "巴厘", "Indonesia", "印度尼西亚"]), "结果中应包含地点名称"


def test_invalid_location():
    """测试不存在的地点"""
    result = WeatherTool.get_weather("不存在的地点xyz123")
    print(f"\n--- 无效地点 ---\n{result}\n")
    assert "未找到" in result or "不存在" in result, "对无效地点应返回友好提示"


def test_tool_schema():
    """测试工具 schema 格式正确"""
    schema = WeatherTool.SCHEMA
    assert schema["type"] == "function"
    fn = schema["function"]
    assert fn["name"] == "get_weather"
    assert "location" in fn["parameters"]["properties"]
    assert "location" in fn["parameters"]["required"]


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v", "-s"])
