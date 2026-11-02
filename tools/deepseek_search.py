import os
import requests
from dotenv import load_dotenv

# 加载 .env 文件中的环境变量
load_dotenv()

apiKey = os.getenv("LLM_API_KEY")


def search(query: str, max_results: int = 5) -> str:
    """
    一个基于 DeepSeek API 的实战网页搜索引擎工具。
    它会智能地解析搜索结果，优先返回最直接的答案或摘要信息。
    
    :param query: 搜索查询
    :param max_results: 最大结果数量，默认5
    :return: 格式化的搜索结果字符串
    """
    print(f" 正在执行 [DeepSeek] 网页搜索: {query}")
    try:
        if not apiKey:
            return "错误: LLM_API_KEY 未在 .env 文件中配置。"

        # 调用 DeepSeek 搜索 API
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
        results = response.json().get("results", [])
        
        if not results:
            return f"对不起，没有找到关于 '{query}' 的信息。"
        
        # 智能解析：优先寻找最直接的答案
        # 检查是否有高相关性分数（rerank_score > 3.0）的结果作为直接答案
        high_score_results = [r for r in results if r.get("rerank_score", 0) > 3.0]
        
        if high_score_results:
            # 返回最高分结果的摘要
            best = high_score_results[0]
            return best.get("summary") or best.get("snippet") or best.get("content", "")
        
        # 检查第一个结果是否有有效的 summary
        first_result = results[0]
        if first_result.get("summary") and len(first_result.get("summary", "")) > 50:
            return first_result["summary"]
        
        # 如果没有直接答案，则返回前三个结果的摘要
        snippets = []
        for i, res in enumerate(results[:3]):
            title = res.get("title", "")
            summary = res.get("summary", "")
            snippet = res.get("snippet", "")
            # 优先使用 summary，如果为空则使用 snippet
            content = summary if summary else snippet
            if content:
                snippets.append(f"[{i+1}] {title}\n{content}")
        
        if snippets:
            return "\n\n".join(snippets)
        
        return f"对不起，没有找到关于 '{query}' 的有效信息。"

    except requests.exceptions.RequestException as e:
        return f"搜索时发生网络错误: {e}"
    except Exception as e:
        return f"搜索时发生错误: {e}"


if __name__ == "__main__":
    # 测试搜索功能
    test_query = "怎么登录deepseek"
    result = search(test_query)
    print(f"\n搜索查询: {test_query}")
    print(f"\n搜索结果:\n{result}")



