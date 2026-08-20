"""统一 LLM 调用层 — 基于 langchain-openai。

替代散落在各处的内联 httpx 调用，支持多 Provider（DeepSeek / OpenAI / Ollama / 自定义）。
所有 AI 调用通过此模块进行，统一错误处理和流式输出。
"""
import json
import logging
from typing import Generator

import httpx
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

logger = logging.getLogger(__name__)


class LLMError(Exception):
    """LLM 调用失败异常 — 调用方应捕获此异常，向用户显示错误但不持久化到内容中。"""
    pass

# ---------------------------------------------------------------------------
# Provider 默认配置
# ---------------------------------------------------------------------------
PROVIDER_DEFAULTS = {
    "deepseek": {
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-v4-pro",
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o",
    },
    "ollama": {
        "base_url": "http://localhost:11434/v1",
        "model": "llama3",
    },
    "custom": {
        "base_url": "",
        "model": "",
    },
}


def fetch_models_from_provider(base_url: str, api_key: str, provider_type: str = "custom") -> list[dict]:
    """调用 GET /v1/models 拉取厂商可用模型列表。

    对间歇性网络/SSL 错误（TLS 记录损坏 BAD_RECORD_MAC、连接抖动、超时）
    自动重试最多 3 次（间隔 1 秒）；HTTP 状态错误（401 无效 key 等）
    重试无意义，直接抛出。

    Returns:
        [{"id": "model-id", "owned_by": "provider"}, ...] 或抛出异常
    """
    import time

    url = base_url.rstrip("/") + "/models"
    # Ollama 不需要 Bearer token
    headers = {}
    if api_key and provider_type != "ollama":
        headers["Authorization"] = f"Bearer {api_key}"

    data = None
    last_err = None
    for attempt in range(3):
        try:
            resp = httpx.get(url, headers=headers, timeout=30.0, verify=False)
            resp.raise_for_status()
            data = resp.json()
            break
        except httpx.HTTPStatusError:
            raise  # 响应类错误（401/403/404...）不重试
        except Exception as e:
            # 网络层异常（TransportError/SSL/超时/JSON截断）：短暂等待后重试
            last_err = e
            if attempt < 2:
                time.sleep(1.0)
    if data is None:
        raise last_err

    # OpenAI 格式: {"data": [{"id": "...", "owned_by": "..."}]}
    if isinstance(data, dict) and "data" in data:
        return [{"id": m["id"], "owned_by": m.get("owned_by", "")} for m in data["data"]]
    # 某些 API 直接返回列表
    if isinstance(data, list):
        return [{"id": m.get("id", str(m)), "owned_by": m.get("owned_by", "")} for m in data]
    return []


def test_provider_connection(base_url: str, api_key: str, provider_type: str = "custom") -> dict:
    """测试厂商连接是否可用。

    Returns:
        {"ok": True, "models_count": N} 或 {"ok": False, "error": "..."}
    """
    try:
        models = fetch_models_from_provider(base_url, api_key, provider_type)
        return {"ok": True, "models_count": len(models)}
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 401:
            return {"ok": False, "error": "API Key 无效（401 Unauthorized）"}
        return {"ok": False, "error": f"HTTP {e.response.status_code}: {e.response.text[:200]}"}
    except httpx.ConnectError:
        return {"ok": False, "error": f"无法连接到 {base_url}"}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def _build_http_client() -> httpx.Client:
    """构建 SSL 容错的 httpx 客户端（共享配置）。"""
    return httpx.Client(verify=False, timeout=httpx.Timeout(300.0, connect=10.0))


def get_llm(
    model: str,
    api_key: str = "",
    base_url: str = "",
    provider_type: str = "custom",
    temperature: float = 0.8,
    max_tokens: int = 4096,
    streaming: bool = True,
) -> ChatOpenAI:
    """构建 ChatOpenAI 实例。

    Args:
        model: 模型标识
        api_key: API 密钥
        base_url: API 地址
        provider_type: 厂商类型（deepseek/openai/ollama/custom）
        temperature: 温度
        max_tokens: 最大 tokens
        streaming: 是否流式
    """
    kwargs = {
        "model": model,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "streaming": streaming,
    }

    if base_url:
        kwargs["base_url"] = base_url.rstrip("/")
    if api_key:
        kwargs["api_key"] = api_key

    # DeepSeek 特殊处理：禁用 thinking（通过 extra_body 传递，不走 model_kwargs 校验）
    if provider_type == "deepseek":
        kwargs["extra_body"] = {"thinking": {"type": "disabled"}}

    # SSL 容错：通过自定义 httpx client
    kwargs["http_client"] = _build_http_client()

    return ChatOpenAI(**kwargs)


def _messages_to_langchain(messages: list[dict]) -> list:
    """将 OpenAI 格式 messages 转为 LangChain 消息对象。"""
    lc_messages = []
    for m in messages:
        role = m.get("role", "user")
        content = m.get("content", "")
        if role == "system":
            lc_messages.append(SystemMessage(content=content))
        elif role == "assistant":
            lc_messages.append(AIMessage(content=content))
        else:
            lc_messages.append(HumanMessage(content=content))
    return lc_messages


def _friendly_error(e: Exception) -> str:
    """将异常转为用户友好的错误消息。"""
    err_str = str(e)
    if "401" in err_str or "Unauthorized" in err_str:
        return "API Key 无效或已过期，请在厂商配置中更新"
    if "429" in err_str or "rate" in err_str.lower():
        return "API 请求频率超限，请稍后再试"
    if "connect" in err_str.lower() or "timeout" in err_str.lower():
        return f"无法连接到 API 服务: {err_str[:100]}"
    return f"LLM 调用失败: {err_str[:200]}"


def stream_llm_tokens(
    model: str,
    messages: list[dict],
    api_key: str = "",
    base_url: str = "",
    provider_type: str = "custom",
    temperature: float = 0.8,
    max_tokens: int = 4096,
) -> Generator[str, None, None]:
    """流式调用 LLM，逐段 yield 文本片段。

    替代所有内联 httpx 流式调用。统一错误处理。
    错误时抛出 LLMError 异常（调用方应捕获，不持久化错误文本到内容中）。
    """
    llm = None
    try:
        llm = get_llm(
            model=model, api_key=api_key, base_url=base_url,
            provider_type=provider_type, temperature=temperature,
            max_tokens=max_tokens, streaming=True,
        )
        lc_messages = _messages_to_langchain(messages)
        for chunk in llm.stream(lc_messages):
            text = chunk.content
            if text:
                yield text
            # DeepSeek reasoning_content fallback
            if hasattr(chunk, "additional_kwargs") and chunk.additional_kwargs.get("reasoning_content"):
                yield chunk.additional_kwargs["reasoning_content"]
    except LLMError:
        raise
    except Exception as e:
        logger.error("stream_llm_tokens failed: %s", e)
        raise LLMError(_friendly_error(e)) from e
    finally:
        if llm and hasattr(llm, "http_client") and llm.http_client:
            try:
                llm.http_client.close()
            except Exception:
                pass


def call_llm_sync(
    model: str,
    messages: list[dict],
    api_key: str = "",
    base_url: str = "",
    provider_type: str = "custom",
    temperature: float = 0.8,
    max_tokens: int = 4096,
) -> str:
    """非流式调用 LLM，返回完整文本。

    替代 _call_ai_sync。错误时抛出 LLMError 异常。
    """
    llm = None
    try:
        llm = get_llm(
            model=model, api_key=api_key, base_url=base_url,
            provider_type=provider_type, temperature=temperature,
            max_tokens=max_tokens, streaming=False,
        )
        lc_messages = _messages_to_langchain(messages)
        result = llm.invoke(lc_messages)
        return result.content
    except LLMError:
        raise
    except Exception as e:
        logger.error("call_llm_sync failed: %s", e)
        raise LLMError(_friendly_error(e)) from e
    finally:
        if llm and hasattr(llm, "http_client") and llm.http_client:
            try:
                llm.http_client.close()
            except Exception:
                pass
