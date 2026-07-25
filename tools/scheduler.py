"""定时任务调度器 - 基于 APScheduler 管理定时任务

功能:
    - 每日早安消息 (默认 08:00)
    - 每日晚安消息 (默认 22:30)
    - 每日生日提醒检查 (默认 09:00)
    - 支持自定义定时任务
"""

import logging
from typing import Callable, Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)


class TaskScheduler:
    """定时任务调度器"""

    def __init__(self):
        self.scheduler = BackgroundScheduler()
        self._task_count = 0

    def add_daily_task(
        self,
        task_func: Callable,
        time_str: str,
        task_id: Optional[str] = None,
        **kwargs,
    ) -> str:
        """
        添加每日定时任务

        Args:
            task_func: 任务函数
            time_str: 时间字符串，格式 "HH:MM"，如 "08:00"
            task_id: 任务 ID，可选
            **kwargs: 传给任务函数的额外参数

        Returns:
            任务 ID
        """
        hour, minute = time_str.split(":")
        if task_id is None:
            task_id = f"daily_task_{self._task_count}"
            self._task_count += 1

        self.scheduler.add_job(
            task_func,
            CronTrigger(hour=int(hour), minute=int(minute)),
            id=task_id,
            kwargs=kwargs,
            replace_existing=True,
        )
        logger.info(f"添加定时任务: id={task_id}, time={time_str}")
        return task_id

    def add_interval_task(
        self,
        task_func: Callable,
        seconds: int,
        task_id: Optional[str] = None,
        **kwargs,
    ) -> str:
        """
        添加间隔任务

        Args:
            task_func: 任务函数
            seconds: 间隔秒数
            task_id: 任务 ID，可选
            **kwargs: 传给任务函数的额外参数

        Returns:
            任务 ID
        """
        if task_id is None:
            task_id = f"interval_task_{self._task_count}"
            self._task_count += 1

        self.scheduler.add_job(
            task_func,
            "interval",
            seconds=seconds,
            id=task_id,
            kwargs=kwargs,
            replace_existing=True,
        )
        logger.info(f"添加间隔任务: id={task_id}, interval={seconds}s")
        return task_id

    def remove_task(self, task_id: str):
        """移除任务"""
        try:
            self.scheduler.remove_job(task_id)
            logger.info(f"移除任务: id={task_id}")
        except Exception as e:
            logger.error(f"移除任务失败: id={task_id}, error={e}")

    def start(self):
        """启动调度器"""
        self.scheduler.start()
        logger.info("定时任务调度器已启动")

    def shutdown(self):
        """关闭调度器"""
        self.scheduler.shutdown(wait=False)
        logger.info("定时任务调度器已关闭")

    def get_tasks(self):
        """获取所有任务"""
        jobs = self.scheduler.get_jobs()
        return [{"id": j.id, "next_run": str(j.next_run_time)} for j in jobs]
