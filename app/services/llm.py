"""统一 LLM 调用层 — 基于 langchain-openai。

替代散落在各处的内联 httpx 调用，支持多 Provider（DeepSeek / OpenAI / Ollama / 自定义）。
所有 AI 调用通过此模块进行，统一错误处理和流式输出。
"""
import json
import logging
import os
from typing import Generator
from urllib.parse import urlsplit

import httpx
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

logger = logging.getLogger(__name__)


def _ssl_verify_for(base_url: str) -> bool:
    """SSL 证书校验策略。

    默认开启校验（防公网 API 的 key 与内容被中间人窃取）；
    仅两种情况降级为不校验：
    1. 显式设置环境变量 LINGYAN_INSECURE_SSL=1
    2. 目标是本机/局域网自建服务（localhost / 127.x / 10.x / 192.168.x / 172.16-31.x）
    """
    if os.getenv("LINGYAN_INSECURE_SSL", "").strip() == "1":
        return False
    try:
        host = (urlsplit(base_url or "").hostname or "").lower()
    except ValueError:
        return True
    if not host:
        return True
    if host in ("localhost", "::1") or host.endswith(".local"):
        return False
    if host.startswith("127.") or host.startswith("10.") or host.startswith("192.168."):
        return False
    parts = host.split(".")
    if len(parts) == 4 and parts[0] == "172" and parts[1].isdigit() and 16 <= int(parts[1]) <= 31:
        return False
    return True


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
            resp = httpx.get(url, headers=headers, timeout=30.0, verify=_ssl_verify_for(base_url))
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


def _build_http_client(base_url: str = "") -> httpx.Client:
    """构建 httpx 客户端（共享配置）。证书校验策略见 _ssl_verify_for。"""
    return httpx.Client(verify=_ssl_verify_for(base_url), timeout=httpx.Timeout(300.0, connect=10.0))


def get_llm(
    model: str,
    api_key: str = "",
    base_url: str = "",
    provider_type: str = "custom",
    temperature: float = 0.8,
    max_tokens: int = 4096,
    streaming: bool = True,
    frequency_penalty: float | None = None,
    presence_penalty: float | None = None,
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
        frequency_penalty: 频率惩罚（-2~2，惩罚已出现 token，抑制重复措辞/构式指纹）
        presence_penalty: 存在惩罚（-2~2，鼓励引入新内容）
    """
    kwargs = {
        "model": model,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "streaming": streaming,
    }
    # 采样惩罚仅在显式配置时传递（None 不下发，兼容不支持该参数的厂商）
    if frequency_penalty is not None:
        kwargs["frequency_penalty"] = frequency_penalty
    if presence_penalty is not None:
        kwargs["presence_penalty"] = presence_penalty

    if base_url:
        kwargs["base_url"] = base_url.rstrip("/")
    if api_key:
        kwargs["api_key"] = api_key

    # DeepSeek 特殊处理：禁用 thinking（通过 extra_body 传递，不走 model_kwargs 校验）
    if provider_type == "deepseek":
        kwargs["extra_body"] = {"thinking": {"type": "disabled"}}

    # SSL 策略：通过自定义 httpx client（默认校验证书，本机/私网自动放行）
    kwargs["http_client"] = _build_http_client(base_url)

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
    frequency_penalty: float | None = None,
    presence_penalty: float | None = None,
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
            frequency_penalty=frequency_penalty,
            presence_penalty=presence_penalty,
        )
        lc_messages = _messages_to_langchain(messages)
        for chunk in llm.stream(lc_messages):
            text = chunk.content
            # 部分兼容网关会返回分片列表形式的 content，统一拼接为字符串
            if isinstance(text, list):
                text = "".join(
                    p.get("text", "") for p in text if isinstance(p, dict)
                )
            if isinstance(text, str) and text:
                yield text
            # DeepSeek reasoning_content fallback —— 思维链绝不并入正文流，
            # 否则会被前端展示并随保存入库污染正文
            reasoning = None
            if hasattr(chunk, "additional_kwargs"):
                reasoning = chunk.additional_kwargs.get("reasoning_content")
            if isinstance(reasoning, str) and reasoning:
                logger.debug("reasoning token suppressed from stream (%d chars)", len(reasoning))
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
    frequency_penalty: float | None = None,
    presence_penalty: float | None = None,
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
            frequency_penalty=frequency_penalty,
            presence_penalty=presence_penalty,
        )
        lc_messages = _messages_to_langchain(messages)
        result = llm.invoke(lc_messages)
        content = result.content
        if isinstance(content, list):
            content = "".join(
                p.get("text", "") for p in content if isinstance(p, dict)
            )
        return content if isinstance(content, str) else str(content)
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
