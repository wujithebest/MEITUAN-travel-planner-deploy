"""
意图处理流水线 - 闭环机制
确保"识别→执行→反馈"全链路闭环

核心功能：
1. 强制响应契约：意图识别成功后2秒内产生用户可见反馈
2. 防断链机制：3秒超时熔断 + 兜底回复
3. 响应组装校验：确保response.content非空
4. 端到端追踪：trace_id贯穿全流程

修复：
- 置信度阈值从0.7降低到0.5
- 返回具体缺失字段信息
- 有目的地+必去景点直接通过
"""
import asyncio
import uuid
import time
import logging
from datetime import datetime
from typing import Optional, Any
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class IntentType(Enum):
    """意图类型枚举"""
    TRAVEL_PLANNING = "travel_planning"
    ROUTE_GENERATION = "route_generation"
    POI_QUERY = "poi_query"
    WEATHER_QUERY = "weather_query"
    CHAT_MESSAGE = "chat_message"
    CLARIFICATION = "clarification"
    UNKNOWN = "unknown"


class ResponseStatus(Enum):
    """响应状态枚举"""
    SUCCESS = "success"
    PROCESSING = "processing"
    FAILED = "failed"
    TIMEOUT = "timeout"
    NEEDS_CLARIFICATION = "needs_clarification"


@dataclass
class IntentResult:
    """意图识别结果"""
    intent_type: IntentType
    confidence: float
    entities: dict = field(default_factory=dict)
    raw_input: str = ""
    trace_id: str = ""
    timestamp: float = field(default_factory=time.time)
    
    @property
    def is_confident(self) -> bool:
        """是否达到置信度阈值 - 修复：降低阈值到0.5"""
        return self.confidence >= 0.5


@dataclass
class PipelineResponse:
    """流水线响应"""
    trace_id: str
    status: ResponseStatus
    content: str
    data: Any = None
    intent_type: IntentType = IntentType.UNKNOWN
    confidence: float = 0.0
    suggestions: list = field(default_factory=list)
    error_message: str = ""
    processing_time_ms: float = 0.0
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "trace_id": self.trace_id,
            "status": self.status.value,
            "content": self.content,
            "data": self.data,
            "intent_type": self.intent_type.value if self.intent_type else None,
            "confidence": self.confidence,
            "suggestions": self.suggestions,
            "error_message": self.error_message,
            "processing_time_ms": self.processing_time_ms,
            "timestamp": self.timestamp
        }


# ==================== 兜底模板 ====================

FALLBACK_TEMPLATES = {
    IntentType.TRAVEL_PLANNING: {
        "success": "已为您规划好{destination}{days}日游路线，包含{highlights}等精彩行程！",
        "processing": "正在为您规划{destination}的旅行路线，请稍候...",
        "failed": "抱歉，路线规划遇到了问题。请重试或换个方式描述您的需求。",
        "clarify": "正在为您规划，这是初步方案：{destination}{days}日游，还需要了解您的预算和偏好。",
        "timeout": "路线规划超时，请稍后重试。"
    },
    IntentType.ROUTE_GENERATION: {
        "success": "路线生成成功！包含{poi_count}个精选地点。",
        "processing": "正在生成路线，请稍候...",
        "failed": "路线生成失败，请检查输入信息后重试。",
        "clarify": "正在为您生成路线，这是初步方案：{summary}",
        "timeout": "路线生成超时，请稍后重试。"
    },
    IntentType.POI_QUERY: {
        "success": "已为您查到相关信息：{summary}",
        "processing": "正在查询地点信息，请稍候...",
        "failed": "查询失败，请换个关键词重试。",
        "clarify": "已为您查到相关信息：{summary}",
        "timeout": "查询超时，请稍后重试。"
    },
    IntentType.WEATHER_QUERY: {
        "success": "已为您查到天气信息：{summary}",
        "processing": "正在查询天气，请稍候...",
        "failed": "天气查询失败，请稍后重试。",
        "clarify": "已为您查到天气信息：{summary}",
        "timeout": "天气查询超时，请稍后重试。"
    },
    IntentType.CHAT_MESSAGE: {
        "success": "已完成{action}，您可以继续下一步",
        "processing": "正在处理您的消息，请稍候...",
        "failed": "消息处理失败，请重试。",
        "clarify": "收到您的消息，正在为您处理...",
        "timeout": "消息处理超时，请稍后重试。"
    },
    IntentType.CLARIFICATION: {
        "success": "信息已收到，正在为您处理",
        "processing": "正在处理您的补充信息，请稍候...",
        "failed": "处理失败，请重试。",
        "clarify": "请提供更多信息，以便更好地帮助您。",
        "timeout": "处理超时，请稍后重试。"
    },
    IntentType.UNKNOWN: {
        "success": "已为您处理完成",
        "processing": "正在处理，请稍候...",
        "failed": "抱歉，处理您的请求时遇到了延迟。请重试或换个方式描述。",
        "clarify": "我需要更多信息来帮助您，请详细描述您的需求。",
        "timeout": "处理超时，请稍后重试。"
    }
}


class IntentPipeline:
    """
    意图处理流水线
    
    修复：
    1. 意图识别后设置3秒执行超时熔断
    2. 无论执行成败必须返回非空响应到前端
    3. 空响应用兜底模板自动填充，禁止静默失败
    4. 置信度阈值从0.7降低到0.5
    5. 返回具体缺失字段信息
    """
    
    # 超时配置（秒）- 修复：3秒超时熔断
    TIMEOUT_THRESHOLD = 3.0
    RESPONSE_DELAY_THRESHOLD = 2.0
    
    def __init__(self):
        self._intent_handlers: dict[IntentType, callable] = {}
        self._break_chain_logs: list[dict] = []
        self._trace_store: dict[str, dict] = {}
    
    def register_handler(self, intent_type: IntentType, handler: callable):
        """注册意图处理器"""
        self._intent_handlers[intent_type] = handler
        logger.info(f"注册意图处理器: {intent_type.value}")
    
    async def process(
        self, 
        user_input: str, 
        intent_result: IntentResult,
        context: dict = None
    ) -> PipelineResponse:
        """
        处理用户意图（核心方法）
        
        Args:
            user_input: 用户原始输入
            intent_result: 意图识别结果
            context: 上下文信息
            
        Returns:
            PipelineResponse: 处理响应
        """
        start_time = time.time()
        trace_id = intent_result.trace_id or str(uuid.uuid4())
        
        # 初始化追踪
        self._init_trace(trace_id, user_input, intent_result)
        
        logger.info(
            f"[Pipeline] 开始处理: trace_id={trace_id}, "
            f"intent={intent_result.intent_type.value}, "
            f"confidence={intent_result.confidence}"
        )
        
        try:
            # ========== 1. 检查缺失字段 ==========
            missing = self._check_missing(intent_result)
            
            # ========== 2. 有目的地+必去景点直接通过 ==========
            if intent_result.entities.get("destination") and intent_result.entities.get("must_visit"):
                logger.info(f"[Pipeline] 有目的地+必去景点，直接通过: {trace_id}")
                # 继续执行，不返回澄清
            
            # ========== 3. 置信度>=0.5 且无关键缺失 ==========
            elif intent_result.confidence >= 0.5 and not missing:
                logger.info(f"[Pipeline] 置信度足够且无缺失，直接通过: {trace_id}")
                # 继续执行，不返回澄清
            
            # ========== 4. 需要澄清 ==========
            else:
                logger.info(f"[Pipeline] 需要澄清: trace_id={trace_id}, confidence={intent_result.confidence}, missing={missing}")
                return await self._handle_low_confidence(
                    trace_id, intent_result, user_input, missing
                )
            
            # ========== 5. 发送即时反馈（2秒内） ==========
            await self._send_immediate_feedback(trace_id, intent_result)
            
            # ========== 6. 执行意图处理（带超时保护） ==========
            response = await self._execute_with_timeout(
                trace_id, intent_result, user_input, context
            )
            
            # ========== 7. 响应校验和兜底 ==========
            response = self._validate_and_fallback(response, intent_result)
            
            # 计算处理时间
            response.processing_time_ms = (time.time() - start_time) * 1000
            
            # 更新追踪
            self._update_trace(trace_id, "completed", response)
            
            logger.info(
                f"[Pipeline] 处理完成: trace_id={trace_id}, "
                f"status={response.status.value}, "
                f"time={response.processing_time_ms:.0f}ms"
            )
            
            return response
            
        except asyncio.TimeoutError:
            logger.warning(f"[Pipeline] 处理超时: trace_id={trace_id}")
            return await self._handle_timeout(trace_id, intent_result, user_input)
            
        except Exception as e:
            logger.error(f"[Pipeline] 处理异常: trace_id={trace_id}, error={e}", exc_info=True)
            return await self._handle_error(trace_id, intent_result, e)
    
    def _check_missing(self, intent_result: IntentResult) -> list[str]:
        """
        检查缺失的关键字段
        返回缺失字段列表，如 ["游玩天数", "兴趣偏好"]
        """
        missing = []
        entities = intent_result.entities
        
        # 检查游玩天数
        if not entities.get("days"):
            missing.append("游玩天数")
        
        # 检查兴趣偏好（themes 或 must_visit）
        if not entities.get("themes") and not entities.get("must_visit"):
            missing.append("兴趣偏好")
        
        return missing
    
    async def _handle_low_confidence(
        self, 
        trace_id: str, 
        intent_result: IntentResult,
        user_input: str,
        missing: list[str] = None
    ) -> PipelineResponse:
        """处理低置信度情况 - 修复：返回具体缺失信息"""
        logger.info(f"[Pipeline] 需要澄清: trace_id={trace_id}, missing={missing}")
        
        entities = intent_result.entities
        destination = entities.get("destination", "")
        
        # 构建已收到的信息摘要
        received_parts = []
        if destination:
            received_parts.append(destination)
        if entities.get("days"):
            received_parts.append(f"{entities['days']}天")
        if entities.get("themes"):
            received_parts.append(f"主题：{', '.join(entities['themes'])}")
        if entities.get("must_visit"):
            received_parts.append(f"必去：{', '.join(entities['must_visit'])}")
        
        received_text = "、".join(received_parts) if received_parts else "您的需求"
        
        # 构建缺失信息提示
        if missing:
            missing_text = "、".join(missing)
            content = f"已收到：{received_text}。\n\n为了给您更好的推荐，还需要了解：{missing_text}\n\n请告诉我这些信息～"
        else:
            content = f"已收到：{received_text}。\n\n请再详细描述一下您的需求，比如游玩天数或想去的景点～"
        
        return PipelineResponse(
            trace_id=trace_id,
            status=ResponseStatus.NEEDS_CLARIFICATION,
            content=content,
            intent_type=intent_result.intent_type,
            confidence=intent_result.confidence,
            data={
                "missing": missing or [],
                "received": received_parts,
                "destination": destination
            },
            suggestions=missing or []
        )
    
    async def _send_immediate_feedback(
        self, 
        trace_id: str, 
        intent_result: IntentResult
    ):
        """发送即时反馈（2秒内）"""
        templates = FALLBACK_TEMPLATES.get(
            intent_result.intent_type, 
            FALLBACK_TEMPLATES[IntentType.UNKNOWN]
        )
        
        # 构建处理中消息（安全格式化，忽略缺失的键）
        try:
            processing_msg = templates["processing"].format(**intent_result.entities)
        except (KeyError, IndexError):
            # 如果模板格式化失败，使用简单消息
            processing_msg = "正在处理您的请求，请稍候..."
        
        # 存储即时反馈（前端可以轮询或WebSocket获取）
        self._trace_store[trace_id]["immediate_feedback"] = {
            "status": "processing",
            "message": processing_msg,
            "timestamp": datetime.now().isoformat()
        }
        
        logger.debug(f"[Pipeline] 即时反馈已发送: trace_id={trace_id}")
    
    async def _execute_with_timeout(
        self,
        trace_id: str,
        intent_result: IntentResult,
        user_input: str,
        context: dict = None
    ) -> PipelineResponse:
        """带超时保护的执行"""
        handler = self._intent_handlers.get(intent_result.intent_type)
        
        if not handler:
            logger.warning(f"[Pipeline] 未找到处理器: {intent_result.intent_type}")
            return await self._handle_no_handler(trace_id, intent_result)
        
        try:
            # 使用wait_for实现超时保护
            response = await asyncio.wait_for(
                handler(
                    trace_id=trace_id,
                    user_input=user_input,
                    intent_result=intent_result,
                    context=context or {}
                ),
                timeout=self.TIMEOUT_THRESHOLD
            )
            return response
            
        except asyncio.TimeoutError:
            # 记录断链日志
            self._log_break_chain(
                intent_type=intent_result.intent_type.value,
                user_input=user_input,
                break_point="handler_execution",
                trace_id=trace_id
            )
            raise
    
    def _validate_and_fallback(
        self, 
        response: PipelineResponse, 
        intent_result: IntentResult
    ) -> PipelineResponse:
        """
        响应校验和兜底
        修复：无论执行成败必须返回非空响应到前端，禁止静默失败
        """
        # 检查响应是否为空或仅包含空白字符
        if not response.content or len(response.content.strip()) == 0:
            logger.warning(
                f"[Pipeline] 响应为空，使用兜底模板: "
                f"trace_id={response.trace_id}, "
                f"status={response.status.value}"
            )
            
            templates = FALLBACK_TEMPLATES.get(
                intent_result.intent_type,
                FALLBACK_TEMPLATES[IntentType.UNKNOWN]
            )
            
            # 根据状态选择模板
            status_key = response.status.value
            fallback_content = templates.get(status_key, templates["failed"])
            
            # 尝试填充模板（安全格式化）
            try:
                # 构建安全的格式化参数
                safe_entities = {
                    "destination": intent_result.entities.get("destination", "目的地"),
                    "days": intent_result.entities.get("days", "几天"),
                    "highlights": intent_result.entities.get("highlights", "精彩行程"),
                    "poi_count": intent_result.entities.get("poi_count", "多个"),
                    "summary": intent_result.entities.get("summary", "相关信息"),
                    "action": intent_result.entities.get("action", "操作"),
                    **intent_result.entities  # 合并原始实体
                }
                response.content = fallback_content.format(**safe_entities)
            except (KeyError, IndexError, ValueError) as e:
                logger.warning(f"[Pipeline] 模板格式化失败: {e}")
                # 使用最简单的兜底消息
                response.content = fallback_content
            
            # 标记为兜底响应
            response.error_message = response.error_message or "使用兜底模板自动填充"
            
            logger.info(f"[Pipeline] 兜底响应已生成: trace_id={response.trace_id}, content长度={len(response.content)}")
        
        # 最终安全检查：确保content不为空
        if not response.content or len(response.content.strip()) == 0:
            response.content = "收到您的消息，正在为您处理..."
            logger.error(f"[Pipeline] 兜底模板也为空，使用最终安全响应: trace_id={response.trace_id}")
        
        return response
    
    async def _handle_timeout(
        self, 
        trace_id: str, 
        intent_result: IntentResult,
        user_input: str
    ) -> PipelineResponse:
        """处理超时情况"""
        logger.warning(f"[Pipeline] 超时兜底: trace_id={trace_id}")
        
        templates = FALLBACK_TEMPLATES.get(
            intent_result.intent_type,
            FALLBACK_TEMPLATES[IntentType.UNKNOWN]
        )
        
        return PipelineResponse(
            trace_id=trace_id,
            status=ResponseStatus.TIMEOUT,
            content=templates["failed"],
            intent_type=intent_result.intent_type,
            confidence=intent_result.confidence,
            error_message="处理超时"
        )
    
    async def _handle_error(
        self, 
        trace_id: str, 
        intent_result: IntentResult,
        error: Exception
    ) -> PipelineResponse:
        """处理错误情况"""
        logger.error(f"[Pipeline] 错误兜底: trace_id={trace_id}, error={error}")
        
        templates = FALLBACK_TEMPLATES.get(
            intent_result.intent_type,
            FALLBACK_TEMPLATES[IntentType.UNKNOWN]
        )
        
        return PipelineResponse(
            trace_id=trace_id,
            status=ResponseStatus.FAILED,
            content=templates["failed"],
            intent_type=intent_result.intent_type,
            confidence=intent_result.confidence,
            error_message=str(error)
        )
    
    async def _handle_no_handler(
        self, 
        trace_id: str, 
        intent_result: IntentResult
    ) -> PipelineResponse:
        """处理无处理器情况"""
        return PipelineResponse(
            trace_id=trace_id,
            status=ResponseStatus.FAILED,
            content="抱歉，暂不支持该类型的请求。请换个方式描述。",
            intent_type=intent_result.intent_type,
            confidence=intent_result.confidence,
            error_message="无对应处理器"
        )
    
    def _init_trace(self, trace_id: str, user_input: str, intent_result: IntentResult):
        """初始化追踪"""
        self._trace_store[trace_id] = {
            "trace_id": trace_id,
            "user_input": user_input,
            "intent_type": intent_result.intent_type.value,
            "confidence": intent_result.confidence,
            "status": "started",
            "started_at": datetime.now().isoformat(),
            "steps": []
        }
    
    def _update_trace(self, trace_id: str, status: str, response: PipelineResponse):
        """更新追踪"""
        if trace_id in self._trace_store:
            self._trace_store[trace_id]["status"] = status
            self._trace_store[trace_id]["completed_at"] = datetime.now().isoformat()
            self._trace_store[trace_id]["response_status"] = response.status.value
    
    def _log_break_chain(
        self, 
        intent_type: str, 
        user_input: str, 
        break_point: str,
        trace_id: str
    ):
        """记录断链日志"""
        log_entry = {
            "intent_type": intent_type,
            "user_input": user_input[:100],  # 截断
            "break_point": break_point,
            "trace_id": trace_id,
            "timestamp": datetime.now().isoformat()
        }
        self._break_chain_logs.append(log_entry)
        logger.error(f"[Pipeline] 断链记录: {log_entry}")
    
    def _guess_possible_intents(self, user_input: str) -> list[IntentType]:
        """猜测可能的意图"""
        possible = []
        input_lower = user_input.lower()
        
        # 关键词匹配
        if any(kw in input_lower for kw in ["游", "玩", "去", "旅行", "旅游"]):
            possible.append(IntentType.TRAVEL_PLANNING)
        if any(kw in input_lower for kw in ["路线", "行程", "规划"]):
            possible.append(IntentType.ROUTE_GENERATION)
        if any(kw in input_lower for kw in ["景点", "地方", "在哪"]):
            possible.append(IntentType.POI_QUERY)
        if any(kw in input_lower for kw in ["天气", "温度"]):
            possible.append(IntentType.WEATHER_QUERY)
        
        # 默认添加聊天
        if not possible:
            possible.append(IntentType.CHAT_MESSAGE)
        
        return possible
    
    def _get_intent_description(self, intent_type: IntentType) -> str:
        """获取意图描述"""
        descriptions = {
            IntentType.TRAVEL_PLANNING: "规划旅行路线",
            IntentType.ROUTE_GENERATION: "生成具体行程",
            IntentType.POI_QUERY: "查询地点信息",
            IntentType.WEATHER_QUERY: "查询天气情况",
            IntentType.CHAT_MESSAGE: "随便聊聊",
            IntentType.UNKNOWN: "其他需求"
        }
        return descriptions.get(intent_type, "未知")
    
    def get_trace(self, trace_id: str) -> Optional[dict]:
        """获取追踪信息"""
        return self._trace_store.get(trace_id)
    
    def get_break_chain_logs(self) -> list[dict]:
        """获取断链日志"""
        return self._break_chain_logs.copy()


# ==================== 便捷函数 ====================

async def process_intent(
    user_input: str,
    intent_type: IntentType,
    confidence: float,
    entities: dict = None,
    context: dict = None,
    pipeline: IntentPipeline = None
) -> PipelineResponse:
    """
    便捷函数：处理用户意图
    
    Args:
        user_input: 用户输入
        intent_type: 意图类型
        confidence: 置信度
        entities: 提取的实体
        context: 上下文
        pipeline: 流水线实例（可选）
        
    Returns:
        PipelineResponse: 处理响应
    """
    if pipeline is None:
        pipeline = get_default_pipeline()
    
    trace_id = str(uuid.uuid4())
    
    intent_result = IntentResult(
        intent_type=intent_type,
        confidence=confidence,
        entities=entities or {},
        raw_input=user_input,
        trace_id=trace_id
    )
    
    return await pipeline.process(user_input, intent_result, context)


# ==================== 单例 ====================

_default_pipeline: Optional[IntentPipeline] = None


def get_default_pipeline() -> IntentPipeline:
    """获取默认流水线实例"""
    global _default_pipeline
    if _default_pipeline is None:
        _default_pipeline = IntentPipeline()
    return _default_pipeline


def init_pipeline() -> IntentPipeline:
    """初始化流水线（注册所有处理器）"""
    pipeline = get_default_pipeline()
    
    # 注册各种意图处理器
    from services.intent_handlers import (
        handle_travel_planning,
        handle_route_generation,
        handle_poi_query,
        handle_weather_query,
        handle_chat_message
    )
    
    pipeline.register_handler(IntentType.TRAVEL_PLANNING, handle_travel_planning)
    pipeline.register_handler(IntentType.ROUTE_GENERATION, handle_route_generation)
    pipeline.register_handler(IntentType.POI_QUERY, handle_poi_query)
    pipeline.register_handler(IntentType.WEATHER_QUERY, handle_weather_query)
    pipeline.register_handler(IntentType.CHAT_MESSAGE, handle_chat_message)
    
    return pipeline
