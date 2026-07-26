"""配置加载模块 - 使用 dynaconf 加载 settings.yaml，并加载 persona.yaml"""

from dynaconf import Dynaconf

# 加载主配置
settings = Dynaconf(
    settings_files=['basic_config/settings.yaml', 'basic_config/password.yaml'],
    load_dotenv=True,
    environments=False,
)

# 加载人设配置
persona_settings = Dynaconf(
    settings_files=['basic_config/persona.yaml'],
    environments=False,
)
