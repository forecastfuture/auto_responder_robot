from dynaconf import Dynaconf
from pydantic import BaseModel, Field, validator, field_validator, ConfigDict
from enum import Enum

settings = Dynaconf(
    settings_files=['./basic_config/settings.yaml'],
)




