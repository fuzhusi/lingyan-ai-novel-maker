"""统一 LLM 调用层 — 基于 langchain-openai。

替代散落在各处的内联 httpx 调用，支持多 Provider（DeepSeek / OpenAI / Ollama / 自定义）。
所有 AI 调用通过此模块进行，统一错误处理和流式输出。
"""
import logging
import os
import re
import time
import ssl
import threading
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


def _ssl_context_for(base_url: str) -> ssl.SSLContext:
    """构建 httpx 用的 SSL 上下文：校验策略同 _ssl_verify_for。

    LINGYAN_TLS_MAX=1.2 时强制 TLS<=1.2 —— 绕过本机安全软件/加速器破坏
    Python TLS1.3 记录导致的 SSLV3_ALERT_BAD_RECORD_MAC（症状：GET 可过、
    带请求体的 POST 必挂且秒失败；curl 不受影响）。
    """
    ctx = ssl.create_default_context()
    if not _ssl_verify_for(base_url):
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    if os.getenv("LINGYAN_TLS_MAX", "").strip() == "1.2":
        ctx.maximum_version = ssl.TLSVersion.TLSv1_2
    return ctx


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
    "anthropic": {
        "base_url": "https://api.anthropic.com/v1",
        "model": "claude-sonnet-4-5",
    },
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "model": "gemini-2.5-pro",
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
    """调用 GET {base_url}/models 拉取厂商可用模型列表。

    对间歇性网络/SSL 错误（TLS 记录损坏 BAD_RECORD_MAC、连接抖动、超时）
    自动重试最多 3 次（间隔 1 秒）；HTTP 状态错误（401 无效 key 等）
    重试无意义，直接抛出。

    Anthropic 走原生协议：x-api-key + anthropic-version 头认证（非 Bearer），
    响应同为 {"data": [...]} 结构，与下方解析兼容。

    Returns:
        [{"id": "model-id", "owned_by": "provider"}, ...] 或抛出异常
    """

    url = base_url.rstrip("/") + "/models"
    headers = {}
    if provider_type == "anthropic":
        # Anthropic 原生 /v1/models：x-api-key 认证 + 版本头；limit 上限调大一次拉全
        url += "?limit=1000"
        if api_key:
            headers["x-api-key"] = api_key
        headers["anthropic-version"] = "2023-06-01"
    else:
        # Ollama 不需要 Bearer token
        if api_key and provider_type != "ollama":
            headers["Authorization"] = f"Bearer {api_key}"

    data = None
    last_err = None
    for attempt in range(3):
        try:
            resp = httpx.get(url, headers=headers, timeout=30.0, verify=_ssl_context_for(base_url))
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


# 共享 HTTP 连接池：按 (SSL 校验策略, TLS 上限) 缓存 httpx.Client。
# 串行多轮生成（大纲→正文→续写补足）复用同一连接，省去每轮 TCP+TLS
# 握手（海外厂商经代理可达 1-3s/次）。httpx.Client 线程安全；
# 进程生命周期内持有，调用结束不再逐次关闭。
_HTTP_CLIENT_CACHE: dict = {}
_HTTP_CLIENT_LOCK = threading.Lock()


def _build_http_client(base_url: str = "") -> httpx.Client:
    """构建/复用 httpx 客户端。证书校验策略见 _ssl_verify_for。"""
    key = (_ssl_verify_for(base_url), os.getenv("LINGYAN_TLS_MAX", "").strip() == "1.2")
    with _HTTP_CLIENT_LOCK:
        client = _HTTP_CLIENT_CACHE.get(key)
        if client is None or client.is_closed:
            client = httpx.Client(
                verify=_ssl_context_for(base_url),
                timeout=httpx.Timeout(300.0, connect=10.0),
            )
            _HTTP_CLIENT_CACHE[key] = client
        return client


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
    logprobs: bool = False,
) -> ChatOpenAI:
    """构建 ChatOpenAI 实例。

    Args:
        model: 模型标识
        api_key: API 密钥
        base_url: API 地址
        provider_type: 厂商类型（deepseek/openai/anthropic/gemini/ollama/custom）
        temperature: 温度
        max_tokens: 最大 tokens
        streaming: 是否流式
        frequency_penalty: 频率惩罚（-2~2，惩罚已出现 token，抑制重复措辞/构式指纹）
        presence_penalty: 存在惩罚（-2~2，鼓励引入新内容）
        logprobs: 请求逐 token 对数概率（诊断用，需厂商支持，不支持会报错）
    """
    # Anthropic 原生协议（/v1/messages，非 OpenAI 兼容）：走 langchain-anthropic。
    # 与 ChatOpenAI 同为 BaseChatModel，调用方的 .stream()/.invoke() 无需感知差异；
    # 采样惩罚与 logprobs 原生 API 不支持——惩罚静默忽略，logprobs 显式报错
    # 让困惑度雷达按既有约定自动隐身。
    if provider_type == "anthropic":
        try:
            from langchain_anthropic import ChatAnthropic
        except ImportError as e:
            raise LLMError("langchain-anthropic 未安装，请执行 uv sync 后重试") from e
        if logprobs:
            raise LLMError("Anthropic 原生 API 不支持 logprobs，困惑度雷达不可用")
        anth_kwargs = {
            "model": model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "streaming": streaming,
            # ChatAnthropic 1.7.x 没有 http_client 字段：传入会被转进
            # model_kwargs 并混入 /v1/messages 请求体（每次调用必失败）。
            # SDK 自管 httpx 客户端，超时经 default_request_timeout 下发。
            "default_request_timeout": 300.0,
        }
        if base_url:
            # SDK 会在 base_url 后自行拼接 v1/messages（要求以 / 结尾）——预置表里的
            # https://api.anthropic.com/v1 必须剥掉 /v1 再补尾斜杠，否则拼出
            # /v1/v1/messages（404）或 ...comv1/messages。fetch_models_from_provider
            # 反而需要带 /v1（GET /v1/models），两处各自归一。
            anth_kwargs["base_url"] = re.sub(r"/v1/?$", "", base_url.rstrip("/")) + "/"
        if api_key:
            anth_kwargs["api_key"] = api_key
        return ChatAnthropic(**anth_kwargs)

    kwargs = {
        "model": model,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "streaming": streaming,
    }
    # 采样惩罚仅在显式配置时传递（None 不下发，兼容不支持该参数的厂商）
    # Gemini 的 OpenAI 兼容端点不接受 frequency/presence_penalty，静默丢弃
    if provider_type != "gemini":
        if frequency_penalty is not None:
            kwargs["frequency_penalty"] = frequency_penalty
        if presence_penalty is not None:
            kwargs["presence_penalty"] = presence_penalty
    if logprobs:
        kwargs["logprobs"] = True

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


# ---------------------------------------------------------------------------
# 瞬态错误重试(指数退避;429 尽量尊重 Retry-After)——P0-2
# ---------------------------------------------------------------------------

_LLM_RETRY_ATTEMPTS = max(1, int(os.getenv("LINGYAN_LLM_RETRIES", "3")))
_TRANSIENT_MARKERS = ("429", "rate limit", "timeout", "timed out", "connect",
                      "connection", "temporarily", "502", "503", "504", "overloaded", "eof")


def _is_transient_error(exc):
    s = str(exc).lower()
    return any(m in s for m in _TRANSIENT_MARKERS)


def _retry_delay(attempt, exc=None):
    m = re.search(r"retry[- ]after[:\s]*(\d+)", str(exc).lower())
    if m:
        return min(float(m.group(1)), 30.0)
    import random
    return min(2 ** attempt, 8) + random.uniform(0, 0.5)


def _record_llm_call(kind, model, ok, duration_ms, prompt_chars, output_chars, error=""):
    """调用计量(P1-4):每次 LLM 调用一行,供成本/失败率聚合。失败静默不影响主链路。

    两种写入路径：
    1. 有 Flask 应用上下文 → SQLAlchemy 独立连接（busy_timeout=250ms）
    2. 无应用上下文（流式 generator 收尾、客户端断开后清理、CLI/后台线程）
       → 直接 sqlite3 打开 DATABASE_PATH，避免 "Working outside of application context"

    始终独立连接，不走调用方 session（add+commit 会把调用方挂起的未提交变更
    一并提交；rollback 更会回滚调用方合法数据）。锁竞争时快速放弃——计量是
    尽力而为数据，主链路延迟优先。
    """
    try:
        from datetime import datetime, timezone
        created = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        row = {
            "kind": kind,
            "model": model or "",
            "ok": 1 if ok else 0,
            "duration_ms": int(duration_ms),
            "prompt_chars": int(prompt_chars),
            "output_chars": int(output_chars),
            "error": _s(error)[:300],
            "created_at": created,
        }

        has_app_ctx = False
        try:
            from flask import current_app
            # current_app 在无上下文时抛 RuntimeError
            _ = current_app.name
            has_app_ctx = True
        except Exception:
            has_app_ctx = False

        if has_app_ctx:
            from sqlalchemy import text as _sql_text
            from app.models import db
            conn = db.engine.connect()
            try:
                conn.exec_driver_sql("PRAGMA busy_timeout=250")
                conn.execute(_sql_text(
                    "INSERT INTO llm_calls (kind, model, ok, duration_ms, prompt_chars, "
                    "output_chars, error, created_at) "
                    "VALUES (:kind, :model, :ok, :duration_ms, :prompt_chars, "
                    ":output_chars, :error, :created_at)"), row)
                conn.commit()
            finally:
                conn.close()
        else:
            # 无应用上下文：裸 sqlite3（流式收尾 / 断开清理 / CLI）
            import sqlite3
            from app.config import AppConfig
            db_path = getattr(AppConfig, "DATABASE_PATH", None)
            if not db_path or not os.path.isfile(db_path):
                return
            conn = sqlite3.connect(db_path, timeout=0.25)
            try:
                conn.execute("PRAGMA busy_timeout=250")
                conn.execute(
                    "INSERT INTO llm_calls (kind, model, ok, duration_ms, prompt_chars, "
                    "output_chars, error, created_at) "
                    "VALUES (:kind, :model, :ok, :duration_ms, :prompt_chars, "
                    ":output_chars, :error, :created_at)", row)
                conn.commit()
            finally:
                conn.close()
    except Exception:
        logger.warning("LLM 计量写入失败 (kind=%s)", kind, exc_info=True)


def _s(v):
    return v if isinstance(v, str) else (str(v) if v is not None else "")


def _stream_llm_tokens_once(
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
    # http_client 已是共享连接池（_HTTP_CLIENT_CACHE），不再逐调用关闭


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
    """流式调用(带瞬态重试):仅在尚未吐出任何 token 前才重试——
    已开始输出的流不可安全重放,中途失败直接抛 LLMError 由调用方处置。"""
    import time as _time
    started = _time.time()
    for attempt in range(_LLM_RETRY_ATTEMPTS):
        yielded = False
        collected = 0
        try:
            for text in _stream_llm_tokens_once(
                model=model, messages=messages, api_key=api_key, base_url=base_url,
                provider_type=provider_type, temperature=temperature,
                max_tokens=max_tokens, frequency_penalty=frequency_penalty,
                presence_penalty=presence_penalty,
            ):
                yielded = True
                collected += len(text)
                yield text
            _record_llm_call("stream", model, True, (_time.time() - started) * 1000,
                             sum(len(m.get("content") or "") for m in messages), collected)
            return
        except LLMError as e:
            _record_llm_call("stream", model, False, (_time.time() - started) * 1000,
                             sum(len(m.get("content") or "") for m in messages), collected, str(e))
            if yielded or attempt == _LLM_RETRY_ATTEMPTS - 1 or not _is_transient_error(e):
                raise
            delay = _retry_delay(attempt, e)
            logger.warning("stream transient failure (attempt %d/%d), retry in %.1fs: %s",
                           attempt + 1, _LLM_RETRY_ATTEMPTS, delay, e)
            _time.sleep(delay)
            started = _time.time()


def call_llm_with_logprobs(
    model: str,
    messages: list[dict],
    api_key: str = "",
    base_url: str = "",
    provider_type: str = "custom",
    temperature: float = 0.0,
    max_tokens: int = 4096,
) -> tuple[str, list[tuple[str, float]]]:
    """非流式调用并返回 (回复文本, [(token, logprob), ...])。

    供困惑度雷达等需要逐 token 对数概率的诊断场景。要求厂商支持
    OpenAI 兼容的 logprobs 参数；厂商不支持/未返回时抛 LLMError，
    由调用方降级（雷达功能自动隐身，不影响主链路）。
    """
    llm = None
    try:
        llm = get_llm(
            model=model, api_key=api_key, base_url=base_url,
            provider_type=provider_type, temperature=temperature,
            max_tokens=max_tokens, streaming=False, logprobs=True,
        )
        lc_messages = _messages_to_langchain(messages)
        result = llm.invoke(lc_messages)
        content = result.content
        if isinstance(content, list):
            content = "".join(
                p.get("text", "") for p in content if isinstance(p, dict)
            )
        content = content if isinstance(content, str) else str(content)

        lp_data = (result.additional_kwargs or {}).get("logprobs") or {}
        items = lp_data.get("content") or []
        tokens = [(it.get("token", ""), float(it.get("logprob", 0.0)))
                  for it in items if isinstance(it, dict)]
        if not tokens:
            raise LLMError("厂商未返回 logprobs（可能不支持该参数）")
        return content, tokens
    except LLMError:
        raise
    except Exception as e:
        logger.error("call_llm_with_logprobs failed: %s", e)
        raise LLMError(_friendly_error(e)) from e
    # http_client 已是共享连接池（_HTTP_CLIENT_CACHE），不再逐调用关闭


def _call_llm_sync_once(
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
    # http_client 已是共享连接池（_HTTP_CLIENT_CACHE），不再逐调用关闭

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
    """非流式调用(带瞬态重试:429/超时/连接类失败指数退避,非瞬态立即抛)。"""
    import time as _time
    started = _time.time()
    prompt_chars = sum(len(m.get("content") or "") for m in messages)
    last_exc = None
    for attempt in range(_LLM_RETRY_ATTEMPTS):
        try:
            out = _call_llm_sync_once(
                model=model, messages=messages, api_key=api_key, base_url=base_url,
                provider_type=provider_type, temperature=temperature,
                max_tokens=max_tokens, frequency_penalty=frequency_penalty,
                presence_penalty=presence_penalty,
            )
            _record_llm_call("sync", model, True, (_time.time() - started) * 1000,
                             prompt_chars, len(out or ""))
            return out
        except LLMError as e:
            last_exc = e
            _record_llm_call("sync", model, False, (_time.time() - started) * 1000,
                             prompt_chars, 0, str(e))
            if attempt == _LLM_RETRY_ATTEMPTS - 1 or not _is_transient_error(e):
                raise
            delay = _retry_delay(attempt, e)
            logger.warning("call_llm_sync transient failure (attempt %d/%d), retry in %.1fs: %s",
                           attempt + 1, _LLM_RETRY_ATTEMPTS, delay, e)
            _time.sleep(delay)
    raise last_exc  # 理论不可达


def _call_embedding(text, cfg):
    """调厂商 embedding API,返回 list[float]。cfg 需含 model_name/api_key/base_url。

    OpenAI 兼容 POST /v1/embeddings;DeepSeek 等均兼容。
    """
    base = (cfg.get("base_url") or "https://api.deepseek.com").rstrip("/")
    url = f"{base}/embeddings"
    headers = {
        "Authorization": f"Bearer {cfg.get('api_key', '')}",
        "Content-Type": "application/json",
    }
    body = {"model": cfg.get("model_name", "text-embedding-3-small"), "input": text[:8000]}
    resp = httpx.post(url, json=body, headers=headers, timeout=30.0,
                      verify=not (cfg.get("base_url") or "").find("127.0.0.1") >= 0)
    resp.raise_for_status()
    data = resp.json()
    if "data" in data and isinstance(data["data"], list) and data["data"]:
        return data["data"][0].get("embedding", [])
    raise ValueError("embedding API 返回格式异常")
