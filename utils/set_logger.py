import logging
import os
from logging.handlers import RotatingFileHandler


def set_logger(
        name: str = 'chat_assistant',
        log_level: int = logging.INFO,
        max_bytes: float = 2e7,
        backup_count: int = 7,
) -> logging.Logger:
    log_folder = './data/log_file'
    os.makedirs(log_folder, exist_ok=True)

    formatter = logging.Formatter(
        '[%(asctime)s.%(msecs)03d] [%(levelname)s] [%(name)s] [line:%(lineno)d] '
        '%(filename)s: \t%(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    logger = logging.getLogger(name)
    logger.setLevel(log_level)

    # 避免重复添加 handler
    if not logger.handlers:
        # 控制台 handler
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        console_handler.setLevel(log_level)
        logger.addHandler(console_handler)

        # 文件 handler
        log_file = os.path.join(log_folder, f'{name}.log')
        file_handler = RotatingFileHandler(
            log_file, mode='a', maxBytes=int(max_bytes), backupCount=backup_count, encoding='utf-8'
        )
        file_handler.setFormatter(formatter)
        file_handler.setLevel(log_level)
        logger.addHandler(file_handler)

    # 关键：关闭日志冒泡到 root logger
    logger.propagate = False

    return logger


# 全局日志实例
VOICE_LOGGER = set_logger()


def get_logger() -> logging.Logger:
    return VOICE_LOGGER
