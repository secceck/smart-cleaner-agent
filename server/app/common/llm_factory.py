"""
LLM 模型工厂与故障转移管理器
- 对接 FreeLLMAPI 服务，兼容 OpenAI 接口协议
- 实现模型自动路由、故障转移（最多20次重试）
- 会话粘性机制（30分钟内固定使用同一模型）
"""
import asyncio
import time
from typing import Optional

import httpx
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from .config import get_settings
from .logger import get_logger

logger = get_logger(__name__)

# 可重试的 HTTP 状态码
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class MaxRetriesExceededError(Exception):
    """所有模型均已尝试且失败时抛出的异常"""
    pass


class ModelFailoverManager:
    """
    模型故障转移管理器

    功能：
    1. 启动时从 FreeLLMAPI 获取可用模型列表
    2. 为每个会话维护模型粘性（30分钟内固定模型）
    3. 请求失败时自动切换到下一个可用模型
    4. 最多重试20次
    """

    def __init__(self):
        self.settings = get_settings()
        self._available_models: list[str] = []
        # thread_id -> (model_name, last_success_timestamp)
        self._thread_model_map: dict[str, tuple[str, float]] = {}
        self._stickiness_seconds: int = self.settings.session_stickiness_seconds
        self._max_retries: int = self.settings.max_retries
        # 单次请求中已失败的模型集合
        self._per_request_failed: set[str] = set()

    # ================================================================
    # 初始化
    # ================================================================

    async def initialize(self) -> None:
        """从 FreeLLMAPI 获取可用模型列表，并做启动健康检查"""
        url = f"{self.settings.freellmapi_base_url}/models"
        headers = {"Authorization": self.settings.freellmapi_api_key}

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url, headers=headers)
                resp.raise_for_status()
                data = resp.json()
                # 解析模型列表（兼容 OpenAI /v1/models 响应格式）
                models_data = data.get("data", [])
                self._available_models = [
                    m.get("id", m.get("name", ""))
                    for m in models_data
                ]
                # 过滤掉路由器/特殊模型（它们不是可调用的真实模型）
                _ROUTER_MODELS = {"auto", "fusion"}
                self._available_models = [
                    m for m in self._available_models
                    if m and m not in _ROUTER_MODELS
                ]
        except Exception as e:
            logger.warning(f"无法获取模型列表: {e}，将使用 fallback 模型 'auto'")
            self._available_models = []

        # 如果获取不到模型，使用 auto 作为兜底
        if not self._available_models:
            self._available_models = ["auto"]

        # 启动健康检查：测试前几个模型，把正常工作的排到前面
        await self._startup_health_check()

        logger.info(f"可用模型列表({len(self._available_models)}): {self._available_models[:8]}...")

    async def _startup_health_check(self, probe_count: int = 8) -> None:
        """
        启动时对前 N 个模型做快速探活，把正常模型排到列表前面。
        避免每次请求都先试一个已宕机的模型（如 key 过期的 kimi-k2.6）。
        """
        if len(self._available_models) <= 1:
            return

        # 只探测前 probe_count 个
        to_probe = self._available_models[:probe_count]
        rest = self._available_models[probe_count:]

        working = []
        dead = []

        async def _probe(model: str) -> tuple[str, bool]:
            """用极轻量请求探测模型是否可用"""
            try:
                from langchain_core.messages import HumanMessage
                # 创建非流式客户端做探活
                probe_llm = ChatOpenAI(
                    base_url=self.settings.freellmapi_base_url,
                    api_key=self.settings.freellmapi_api_key,
                    model=model,
                    temperature=0,
                    streaming=False,
                    timeout=8,
                    max_retries=0,
                    max_tokens=5,
                )
                resp = await asyncio.wait_for(
                    probe_llm.ainvoke([HumanMessage(content="ping")]),
                    timeout=8,
                )
                return model, bool(resp and resp.content)
            except Exception:
                return model, False

        tasks = [_probe(m) for m in to_probe]
        results = await asyncio.gather(*tasks)

        for model, ok in results:
            if ok:
                working.append(model)
            else:
                dead.append(model)
                logger.info(f"启动探测: {model} 不可用，排到队尾")

        # 可用模型优先，不可用的放后面
        self._available_models = working + dead + rest
        if dead:
            logger.info(
                f"启动健康检查: {len(working)}/{len(to_probe)} 正常, "
                f"{len(dead)} 个排到队尾 ({dead[:3]}...)"
            )

    @property
    def available_models(self) -> list[str]:
        return list(self._available_models)

    # ================================================================
    # 会话粘性管理
    # ================================================================

    def record_success(self, thread_id: str, model_name: str) -> None:
        """记录模型调用成功，更新会话粘性"""
        self._thread_model_map[thread_id] = (model_name, time.time())
        logger.debug(f"会话 {thread_id} 模型 {model_name} 调用成功，记录粘性")

    def mark_failed(self, model_name: str) -> None:
        """标记模型调用失败"""
        self._per_request_failed.add(model_name)
        logger.warning(f"模型 {model_name} 标记为失败，本次请求不再使用")

    def clear_per_request_failures(self) -> None:
        """清除单次请求的失败记录"""
        self._per_request_failed.clear()

    # ================================================================
    # LLM 客户端工厂
    # ================================================================

    def create_chat_llm(self, model_name: Optional[str] = None) -> ChatOpenAI:
        """
        创建 ChatOpenAI 实例（对话模型）
        max_retries=0 是因为我们在外层自行实现重试逻辑
        """
        return ChatOpenAI(
            base_url=self.settings.freellmapi_base_url,
            api_key=self.settings.freellmapi_api_key,
            model=model_name or self.settings.freellmapi_chat_model,
            temperature=0.7,
            streaming=True,
            timeout=self.settings.api_timeout,
            max_retries=0,
        )

    def create_embeddings(self) -> OpenAIEmbeddings:
        """创建 OpenAIEmbeddings 实例（嵌入模型）"""
        return OpenAIEmbeddings(
            base_url=self.settings.freellmapi_base_url,
            api_key=self.settings.freellmapi_api_key,
            model=self.settings.freellmapi_embedding_model,
            timeout=self.settings.api_timeout,
            max_retries=2,
        )

    # ================================================================
    # 带重试的模型调用
    # ================================================================

    async def invoke_with_retry(
        self,
        thread_id: str,
        llm_with_tools,
        messages: list,
    ):
        """
        带故障转移的模型调用。
        - 永久失败（5xx/连接）：标记 mark_failed，换模型
        - 临时限流（429）：记入 rate_limited 集合，换模型；全部轮完后清除限流标记重试
        - 最多重试 max_retries 次
        """
        self.clear_per_request_failures()
        rate_limited: set[str] = set()
        last_error: Optional[Exception] = None

        for attempt in range(self._max_retries):
            model_name = self._pick_model(thread_id, rate_limited)
            bound_tools = []
            if hasattr(llm_with_tools, 'kwargs') and 'tools' in llm_with_tools.kwargs:
                bound_tools = llm_with_tools.kwargs['tools']
            elif hasattr(llm_with_tools, 'tools'):
                bound_tools = llm_with_tools.tools
            llm = self.create_chat_llm(model_name).bind_tools(bound_tools)

            try:
                response = await llm.ainvoke(messages)
                self.record_success(thread_id, model_name)
                return response

            except httpx.HTTPStatusError as e:
                last_error = e
                status_code = e.response.status_code
                if status_code in RETRYABLE_STATUS_CODES:
                    if status_code == 429:
                        rate_limited.add(model_name)
                        logger.info(
                            f"模型 {model_name} 限流(429)，跳过 "
                            f"(第 {attempt + 1}/{self._max_retries} 次)"
                        )
                    else:
                        self.mark_failed(model_name)
                        logger.warning(
                            f"模型 {model_name} 返回 {status_code}，"
                            f"第 {attempt + 1}/{self._max_retries} 次重试"
                        )
                    await asyncio.sleep(1.0)
                else:
                    logger.error(f"模型 {model_name} 返回不可重试错误 {status_code}: {e}")
                    raise

            except (httpx.TimeoutException, httpx.ConnectError, httpx.RemoteProtocolError) as e:
                self.mark_failed(model_name)
                last_error = e
                logger.warning(
                    f"模型 {model_name} 连接/超时异常: {e}，"
                    f"第 {attempt + 1}/{self._max_retries} 次重试"
                )
                await asyncio.sleep(1.0)

            except Exception as e:
                error_cls = type(e).__name__

                # OpenAI SDK 的超时/连接错误（非 httpx 异常）
                if error_cls in ("APITimeoutError", "APIConnectionError",
                                 "InternalServerError", "ServiceUnavailableError"):
                    self.mark_failed(model_name)
                    last_error = e
                    logger.warning(
                        f"模型 {model_name} {error_cls}，"
                        f"第 {attempt + 1}/{self._max_retries} 次重试"
                    )
                    await asyncio.sleep(1.0)
                    continue

                status_code = getattr(e, 'status_code', None)
                if status_code is None:
                    response = getattr(e, 'response', None)
                    if response is not None:
                        status_code = getattr(response, 'status_code', None)

                if status_code is not None and (
                    int(status_code) >= 500 or int(status_code) == 429
                    or int(status_code) == 400
                ):
                    last_error = e
                    if int(status_code) == 429:
                        rate_limited.add(model_name)
                        logger.info(
                            f"模型 {model_name} 限流(429)，跳过 "
                            f"(第 {attempt + 1}/{self._max_retries} 次)"
                        )
                    else:
                        # 400/5xx：模型不兼容或服务端故障，标记失败换模型
                        self.mark_failed(model_name)
                        logger.warning(
                            f"模型 {model_name} 返回 {status_code} ({error_cls})，"
                            f"第 {attempt + 1}/{self._max_retries} 次重试"
                        )
                    await asyncio.sleep(1.0)
                elif status_code is not None and 401 <= int(status_code) < 500:
                    logger.error(f"模型 {model_name} 返回客户端错误 {status_code}: {e}")
                    raise
                else:
                    logger.error(f"模型调用未知错误: {error_cls}: {e}")
                    raise

        logger.error(f"所有 {self._max_retries} 次重试均已失败。最后错误: {last_error}")
        raise MaxRetriesExceededError(
            "抱歉，当前大模型服务暂时不可用，所有模型均无法响应。请稍后再试。"
        )

    def _pick_model(self, thread_id: str, rate_limited: set[str]) -> str:
        """
        选择模型：跳过永久失败和本次临时限流的模型。
        全部被跳过时清除限流标记重新开始。
        """
        # 合并排除集合
        excluded = self._per_request_failed | rate_limited

        # 如果有粘性模型且未被排除，优先使用
        if thread_id in self._thread_model_map:
            model, timestamp = self._thread_model_map[thread_id]
            if time.time() - timestamp < self._stickiness_seconds:
                if model not in excluded:
                    return model

        # 选择第一个未被排除的模型
        for model in self._available_models:
            if model not in excluded:
                return model

        # 所有模型都被排除：清除限流标记，从第一个非永久失败的开始
        rate_limited.clear()
        for model in self._available_models:
            if model not in self._per_request_failed:
                return model

        # 全部永久失败：重置重试
        self._per_request_failed.clear()
        return self._available_models[0] if self._available_models else "auto"


# ================================================================
# 全局单例
# ================================================================

_model_manager: Optional[ModelFailoverManager] = None


def get_model_manager() -> ModelFailoverManager:
    """获取全局 ModelFailoverManager 单例（未初始化时有默认兜底）"""
    global _model_manager
    if _model_manager is None:
        _model_manager = ModelFailoverManager()
        # 未初始化时给一个安全的默认列表
        _model_manager._available_models = [get_settings().freellmapi_chat_model]
    return _model_manager


async def init_model_manager() -> ModelFailoverManager:
    """初始化全局 ModelFailoverManager"""
    global _model_manager
    _model_manager = ModelFailoverManager()
    await _model_manager.initialize()
    return _model_manager
