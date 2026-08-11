"""人设长期记忆测试 - 测试 persona.yaml 的读写和系统提示词构建"""

import os
import tempfile
import shutil
import pytest
import yaml

from agent.persona import Persona


@pytest.fixture
def temp_persona(monkeypatch):
    """创建临时 persona.yaml 文件用于测试"""
    # 备份原始文件
    from agent import persona as persona_mod
    original_file = persona_mod.PERSONA_FILE

    # 创建临时文件
    tmp_dir = tempfile.mkdtemp()
    tmp_file = os.path.join(tmp_dir, "persona.yaml")
    with open(tmp_file, "w", encoding="utf-8") as f:
        yaml.dump({"长期记忆": ["测试记忆1: 生日是0101"]}, f, allow_unicode=True)

    # 替换 PERSONA_FILE 路径
    monkeypatch.setattr(persona_mod, "PERSONA_FILE", tmp_file)
    yield tmp_file
    shutil.rmtree(tmp_dir, ignore_errors=True)


class TestPersonaLongTermMemory:
    """Persona 长期记忆读写测试"""

    def test_get_long_term_memories(self, temp_persona):
        """测试读取长期记忆"""
        memories = Persona.get_long_term_memories()
        assert len(memories) == 1
        assert "测试记忆1" in memories[0]

    def test_add_long_term_memory(self, temp_persona):
        """测试添加长期记忆"""
        ok = Persona.add_long_term_memory("三月喜欢喝咖啡")
        assert ok is True

        memories = Persona.get_long_term_memories()
        assert len(memories) == 2
        assert any("咖啡" in m for m in memories)

    def test_add_duplicate_memory(self, temp_persona):
        """测试添加重复记忆（应跳过）"""
        Persona.add_long_term_memory("重复记忆")
        ok = Persona.add_long_term_memory("重复记忆")
        assert ok is True  # 已存在返回 True

        memories = Persona.get_long_term_memories()
        count = sum(1 for m in memories if m == "重复记忆")
        assert count == 1

    def test_add_empty_memory(self, temp_persona):
        """测试添加空记忆"""
        assert Persona.add_long_term_memory("") is False
        assert Persona.add_long_term_memory("   ") is False

    def test_memory_persists_to_file(self, temp_persona):
        """测试记忆确实写入了文件"""
        Persona.add_long_term_memory("文件持久化测试")
        with open(temp_persona, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        assert "长期记忆" in data
        assert any("文件持久化测试" in m for m in data["长期记忆"])

    def test_build_long_term_memory_text(self, temp_persona):
        """测试长期记忆提示文本构建"""
        Persona.add_long_term_memory("angel喜欢花")
        p = Persona()
        text = p.build_long_term_memory_text()
        assert "长期记忆" in text
        assert "angel喜欢花" in text

    def test_build_system_prompt_includes_memory(self, temp_persona):
        """测试系统提示词包含长期记忆"""
        Persona.add_long_term_memory("家庭重要信息")
        p = Persona()
        prompt = p.build_system_prompt()
        assert "长期记忆" in prompt
        assert "家庭重要信息" in prompt
