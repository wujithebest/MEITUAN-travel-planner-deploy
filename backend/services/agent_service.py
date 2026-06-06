"""
AI助手核心服务
旅行助手Agent，类似Kimi的AI助手
"""
import asyncio
import random
from datetime import datetime
from typing import Optional
from models.chat import (
    ChatMessage, ChatRoom, TravelIntent, AgentAction, 
    MessageSender, MessageContent, ItineraryDraft
)
from services.intent_extractor import IntentExtractor
from services.llm_parser import LLMParser
from services.route_planner import RoutePlanner
import logging

logger = logging.getLogger(__name__)


class TravelAgent:
    """旅行助手Agent"""
    
    SYSTEM_PROMPT = """你是"旅行助手小游"，一个专业的上海旅游规划AI。

你在一个群聊中工作，群成员正在讨论旅行计划。你的职责：
1. 实时分析群聊内容，提取旅行意图（地点、时间、偏好）
2. 自然参与对话，回答问题，给出建议
3. 当信息足够时，主动生成路线预览
4. 信息不足时，礼貌询问关键信息（如天数、预算、偏好）

回复风格：
- 友好、专业、简洁
- 使用emoji让对话生动 😊
- 提到具体地点时，自动附上实用信息（开放时间、人均消费）
- 不要一次性问太多问题，每次最多1-2个
- 像朋友聊天一样自然，不要像机器人

当前系统仅支持上海市内旅游规划。

重要：你的回复会直接发送到群聊，所有成员都能看到。请确保回复有价值、不重复。"""

    def __init__(self):
        self.llm = LLMParser()
        self.intent_extractor = IntentExtractor()
        self.route_planner = RoutePlanner()
        self._last_agent_message_time: dict[str, datetime] = {}  # room_id -> last_time
    
    async def process_message(
        self, 
        room_id: str, 
        new_message: ChatMessage, 
        history: list[ChatMessage],
        current_intent: TravelIntent | None = None
    ) -> AgentAction | None:
        """
        处理新消息，决定AI如何回应
        返回AgentAction或None（静默观察）
        """
        try:
            # 1. 提取/更新群聊意图
            new_intent = await self.intent_extractor.extract_from_history(
                history + [new_message]
            )
            
            # 合并旧意图
            if current_intent:
                new_intent = self.intent_extractor.merge_intents(current_intent, new_intent)
            
            # 2. 判断是否需要AI介入
            should_respond, reason = self._should_respond(new_message, new_intent, history)
            
            if not should_respond:
                logger.debug(f"AI选择静默观察: room={room_id}, reason={reason}")
                return None
            
            logger.info(f"AI决定回应: room={room_id}, reason={reason}, confidence={new_intent.confidence}")
            
            # 3. 根据意图完整度决定回应策略
            if new_intent.confidence < 0.3:
                # 信息太少，引导提问
                return await self._handle_clarify(new_intent, history)
            
            elif new_intent.confidence < 0.7:
                # 信息部分足够，给出建议并询问补充
                return await self._handle_suggest(new_intent, history)
            
            else:
                # 信息充足，生成完整路线
                return await self._handle_generate_route(new_intent, history)
                
        except Exception as e:
            logger.error(f"AI处理消息失败: {e}", exc_info=True)
            return None
    
    def _should_respond(
        self, 
        msg: ChatMessage, 
        intent: TravelIntent,
        history: list[ChatMessage]
    ) -> tuple[bool, str]:
        """判断AI是否需要回应，返回(是否回应, 原因)"""
        text = msg.content.text or ""
        
        # 不回应AI自己的消息
        if msg.sender.is_agent:
            return False, "自己的消息"
        
        # 直接@助手
        if "@旅行助手" in text or "@小游" in text or "@AI" in text:
            return True, "被@提及"
        
        # 询问旅行相关问题
        question_patterns = [
            "怎么玩", "去哪", "推荐", "攻略", "路线", "规划", 
            "好吃", "好玩", "景点", "美食", "住哪", "交通",
            "多少钱", "门票", "开放", "时间"
        ]
        if any(p in text for p in question_patterns):
            return True, "旅行相关问题"
        
        # 信息足够且一段时间未发言，主动生成
        if intent.confidence > 0.8:
            time_since_last = self._time_since_last_agent_msg(msg.room_id)
            if time_since_last > 300:  # 5分钟
                return True, "信息充足且长时间未发言"
        
        # 用户明确请求生成路线
        if "生成路线" in text or "帮我规划" in text or "出个方案" in text:
            return True, "用户请求生成路线"
        
        # 新成员加入
        if msg.content.type == "system_notice" and "加入" in text:
            return True, "新成员加入"
        
        return False, "无需回应"
    
    def _time_since_last_agent_msg(self, room_id: str) -> float:
        """距离上次AI发言的秒数"""
        last_time = self._last_agent_message_time.get(room_id)
        if not last_time:
            return float('inf')
        return (datetime.now() - last_time).total_seconds()
    
    async def _handle_clarify(
        self, 
        intent: TravelIntent, 
        history: list[ChatMessage]
    ) -> AgentAction:
        """处理信息不足的情况 - 引导提问"""
        missing = self.intent_extractor.get_missing_info(intent)
        
        # 构建友好的引导消息
        greetings = [
            "大家好！👋 我是旅行助手小游",
            "嗨～我是小游，来帮大家规划旅行",
            "大家好！看到大家在讨论旅行，我来帮忙啦 ✨"
        ]
        
        # 根据已有信息给出反馈
        feedback_parts = []
        if intent.destination:
            feedback_parts.append(f"看到大家想去{intent.destination}啦")
        if intent.themes:
            feedback_parts.append(f"对{'、'.join(intent.themes[:2])}感兴趣呢")
        if intent.must_visit:
            feedback_parts.append(f"还提到了{intent.must_visit[0]}等地点")
        
        feedback = "，".join(feedback_parts) if feedback_parts else ""
        
        # 构建问题
        questions = []
        if not intent.days:
            questions.append("打算玩几天呀？🗓️")
        if not intent.destination:
            questions.append("主要想在上海哪个区域活动？📍")
        if not intent.themes:
            questions.append("偏好什么类型？美食🍜、历史🏛️、文艺🎨还是自然风光🌳？")
        if not intent.budget_level:
            questions.append("预算范围大概是多少？💰")
        if not intent.travelers:
            questions.append("是亲子游👨‍👩‍👧、情侣约会💑还是朋友聚会👫？")
        
        # 最多问2个问题
        selected_questions = questions[:2]
        
        # 组装消息
        content = f"{random.choice(greetings)}！\n\n"
        if feedback:
            content += f"{feedback}～\n\n"
        content += "想给大家规划一条合适的路线，还需要了解：\n\n"
        content += "\n".join(f"• {q}" for q in selected_questions)
        content += "\n\n随时告诉我，我会根据大家的想法来规划路线 😊"
        
        return AgentAction(
            action="clarify",
            content=content,
            questions=selected_questions,
            metadata={"intent": intent.dict()}
        )
    
    async def _handle_suggest(
        self, 
        intent: TravelIntent, 
        history: list[ChatMessage]
    ) -> AgentAction:
        """处理信息部分足够的情况 - 给出建议"""
        # 构建建议prompt
        prompt = f"""
根据以下旅行信息，给出简洁的建议和推荐：

目的地：{intent.destination or '上海'}
天数：{intent.days or '未定'}
主题：{', '.join(intent.themes) if intent.themes else '未定'}
必去地点：{', '.join(intent.must_visit) if intent.must_visit else '无'}
偏好：{', '.join(intent.preferences) if intent.preferences else '无'}
预算：{intent.budget_level or '未定'}
同行人：{', '.join(intent.travelers) if intent.travelers else '未定'}

请给出：
1. 简短的信息确认（1句话）
2. 2-3个具体建议（如推荐地点、注意事项）
3. 还需要补充的信息（1-2个问题）

格式要求：
- 使用emoji让内容生动
- 简洁明了，不超过200字
- 像朋友聊天一样自然
"""
        
        suggestion_text = await self.llm.generate(prompt)
        
        # 尝试生成路线预览
        route_draft = None
        if intent.destination and intent.days:
            try:
                route_draft = await self._generate_route_preview(intent)
            except Exception as e:
                logger.warning(f"生成路线预览失败: {e}")
        
        content = suggestion_text
        if route_draft:
            content += "\n\n💡 我已经根据目前的信息准备了一个路线预览，点击「生成正式路线」可查看详细安排～"
        
        return AgentAction(
            action="suggest_route",
            content=content,
            route_draft=route_draft,
            metadata={"intent": intent.dict()}
        )
    
    async def _handle_generate_route(
        self, 
        intent: TravelIntent, 
        history: list[ChatMessage]
    ) -> AgentAction:
        """处理信息充足的情况 - 生成完整路线"""
        # 生成路线
        route = await self._generate_full_route(intent)
        
        # 构建消息
        content = f"🎉 根据大家的讨论，我生成了一条路线预览：\n\n"
        content += f"📍 {intent.destination} {intent.days}日游\n"
        
        if intent.themes:
            content += f"🏷️ 主题：{'、'.join(intent.themes[:3])}\n"
        
        content += f"\n{route['summary']}\n\n"
        
        if route.get('highlights'):
            content += "✨ 行程亮点：\n"
            for i, highlight in enumerate(route['highlights'][:3], 1):
                content += f"  {i}. {highlight}\n"
        
        content += "\n点击右侧「生成正式路线」可查看详细安排，或继续讨论调整 😊"
        
        return AgentAction(
            action="generate_route",
            content=content,
            route_draft=route,
            metadata={"intent": intent.dict(), "route_id": route.get("route_id")}
        )
    
    async def _generate_route_preview(self, intent: TravelIntent) -> dict:
        """生成路线预览（轻量级）"""
        # 简化版路线生成
        return {
            "name": f"{intent.destination}{intent.days}日游",
            "destination": intent.destination,
            "days": intent.days or 2,
            "pois": [],  # 预览版不填充详细POI
            "summary": f"包含{intent.days}天的精选行程",
            "status": "preview"
        }
    
    async def _generate_full_route(self, intent: TravelIntent) -> dict:
        """调用现有路线生成服务生成完整路线"""
        try:
            # 将提取的意图转换为路线生成请求
            route_request = {
                "plan_mode": "intent",
                "area": intent.destination or "上海",
                "days": intent.days or 2,
                "theme": "、".join(intent.themes) if intent.themes else None,
                "preferences": {
                    "must_visit": intent.must_visit,
                    "avoid": intent.preferences,
                    "budget": intent.budget_level,
                    "travelers": intent.travelers
                }
            }
            
            # 调用现有路线规划服务
            result = await self.route_planner.generate_route(route_request)
            
            return {
                "route_id": result.get("id", ""),
                "name": result.get("name", f"{intent.destination}{intent.days}日游"),
                "destination": intent.destination,
                "days": intent.days,
                "summary": result.get("summary", f"{intent.days}天{intent.destination}之旅"),
                "highlights": result.get("highlights", []),
                "pois": result.get("pois", []),
                "status": "draft"
            }
            
        except Exception as e:
            logger.error(f"生成完整路线失败: {e}", exc_info=True)
            # 返回基础信息
            return {
                "name": f"{intent.destination}{intent.days}日游",
                "destination": intent.destination,
                "days": intent.days or 2,
                "summary": f"{intent.days}天{intent.destination}之旅，包含精选地点",
                "highlights": intent.must_visit[:3] if intent.must_visit else [],
                "pois": [],
                "status": "draft"
            }
    
    def record_agent_message(self, room_id: str):
        """记录AI发言时间"""
        self._last_agent_message_time[room_id] = datetime.now()
    
    async def generate_direct_response(
        self, 
        room_id: str,
        message: ChatMessage,
        history: list[ChatMessage]
    ) -> AgentAction:
        """
        生成直接回应（当被@或明确提问时）
        """
        text = message.content.text or ""
        
        # 移除@提及
        clean_text = text.replace("@旅行助手", "").replace("@小游", "").replace("@AI", "").strip()
        
        # 构建对话上下文
        recent_history = history[-10:]  # 最近10条
        context = "\n".join([
            f"{'用户' if not m.sender.is_agent else '助手'}: {m.content.text or ''}"
            for m in recent_history
        ])
        
        prompt = f"""
{self.SYSTEM_PROMPT}

对话历史：
{context}

用户问：{clean_text}

请直接回答用户的问题，要求：
- 简洁明了，不超过150字
- 使用emoji让回答生动
- 如果问题需要更多信息才能回答，礼貌询问
- 只输出回答内容，不要有其他说明
"""
        
        response = await self.llm.generate(prompt)
        
        return AgentAction(
            action="answer",
            content=response,
            metadata={"question": clean_text}
        )


# 单例
_agent_instance: TravelAgent | None = None


def get_travel_agent() -> TravelAgent:
    """获取TravelAgent单例"""
    global _agent_instance
    if _agent_instance is None:
        _agent_instance = TravelAgent()
    return _agent_instance
