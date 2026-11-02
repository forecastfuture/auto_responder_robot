import os
from openai import OpenAI
from dotenv import load_dotenv
from typing import List, Dict

# 加载 .env 文件中的环境变量
load_dotenv()

apiKey = os.getenv("LLM_API_KEY")

import os
import requests

def internet_search(query: str, max_results: int = 5):
    """
    {
      "results": [
        {
          "rerank_score": 2.4,
          "title": "DeepSeek V4 模型发布",
          "url": "https://example.com/deepseek-v4",
          "snippet": "DeepSeek V4 已上线，支持工具调用与长上下文。",
          "summary": "DeepSeek 发布了 V4 模型。此次发布改进了工具调用与长上下文能力，适合 Agent 工作流。",
          "content": "DeepSeek V4 现已正式上线……",
          "site_name": "Example News",
          "site_icon": "https://example.com/favicon.ico",
          "date": "2026-06-01T00:00:00+00:00",
          "authority": 3
        }
      ]
    }
    :param query:
    :param max_results:
    :return:
    """
    response = requests.post(
        "https://api.deepseek.com/v1/tools/search",
        headers={
            "Authorization": f"Bearer {apiKey}",
            "Content-Type": "application/json",
        },
        json={
            "query": query,
            "count": max_results,
            "need_content": True,
        },
        timeout=30,
    )
    response.raise_for_status()
    return response.json()["results"]


if __name__ == "__main__":
    results = internet_search("怎么登录deepseek")

    for item in results:
        # print(item.get("title"))
        # print(item.get("url"))
        print(item.get("summary"))
        print("-" * 60)



