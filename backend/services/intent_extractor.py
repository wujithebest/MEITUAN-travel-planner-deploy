"""
意图提取器
从群聊历史中提取旅行意图
"""
from datetime import datetime
from typing import Optional
from models.chat import ChatMessage, TravelIntent
from services.llm_parser import LLMParser
import logging

logger = logging.getLogger(__name__)


class IntentExtractor:
    """从群聊历史中提取旅行意图"""
    
    def __init__(self):
        self.llm = LLMParser()
    
    async def extract_from_history(self, messages: list[ChatMessage]) -> TravelIntent:
        """
        累计提取，每次基于全部历史
        返回更新后的TravelIntent
        """
        try:
            # 只取用户消息（排除AI和系统）
            user_messages = [m for m in messages if not m.sender.is_agent]
            
            if not user_messages:
                return TravelIntent(confidence=0.0)
            
            # 构建对话文本（最近30条）
            recent_messages = user_messages[-30:]
            chat_text = "\n".join([
                f"{m.sender.name}: {m.content.text or ''}" 
                for m in recent_messages
            ])
            
            # 提取消息ID
            extracted_from = [m.id for m in recent_messages]
            
            # 构建prompt
            prompt = self._build_extraction_prompt(chat_text)
            
            # 调用LLM提取
            result = await self.llm.extract_json(prompt)
            
            # 构建TravelIntent
            intent = TravelIntent(
                destination=result.get("destination"),
                days=result.get("days"),
                themes=result.get("themes", []),
                must_visit=result.get("must_visit", []),
                preferences=result.get("preferences", []),
                budget_level=result.get("budget_level"),
                travelers=result.get("travelers", []),
                extracted_from=extracted_from,
                confidence=result.get("confidence", 0.0),
                last_updated=datetime.now()
            )
            
            # 处理日期
            if result.get("dates"):
                try:
                    date_str = result["dates"]
                    if "到" in date_str:
                        start_str, end_str = date_str.split("到")
                        intent.dates = (
                            datetime.strptime(start_str.strip(), "%Y-%m-%d"),
                            datetime.strptime(end_str.strip(), "%Y-%m-%d")
                        )
                except Exception as e:
                    logger.warning(f"日期解析失败: {e}")
            
            logger.info(
                f"意图提取完成: destination={intent.destination}, "
                f"days={intent.days}, confidence={intent.confidence}"
            )
            
            return intent
            
        except Exception as e:
            logger.error(f"意图提取失败: {e}", exc_info=True)
            return TravelIntent(confidence=0.0)
    
    def _build_extraction_prompt(self, chat_text: str) -> str:
        """构建提取prompt"""
        return f"""
你是一个旅行规划助手，需要从群聊内容中提取旅行规划所需信息。

群聊内容：
{chat_text}

请仔细分析对话，提取以下信息并以JSON格式输出：

{{
    "destination": "目的地（如'上海徐汇区'、'上海'），如果未明确提及则为null",
    "days": "计划游玩天数（数字），如果未提及则为null",
    "dates: "日期范围（如'2024-05-01到2024-05-03'），如果未提及则为null",
    "themes": ["主题列表，从以下选项中选择：美食、历史、文艺、自然、购物、亲子、夜景、网红打卡"],
    "must_visit": ["明确提到的地点名称列表"],
    "preferences": ["偏好和限制，如'不爬山'、'少走路'、'预算低'、'带孩子'等"],
    "budget_level": "预算等级：'经济'（人均<100/天）、'中等'（100-300/天）、'高端'（>300/天），不确定则为null",
    "travelers": ["同行人类型，从以下选项中选择：亲子、情侣、朋友、老人、独行"],
    "confidence": "信息完整度评分（0-1之间的小数，0表示完全无信息，1表示信息非常完整）"
}}

注意事项：
1. 只提取明确提到的信息，不要臆测
2. 如果多人提到不同信息，都要包含
3. confidence根据信息完整度评分：有目的地+0.2，有天数+0.2，有主题+0.1，有偏好+0.1，有预算+0.1，有日期+0.1，有同行人+0.1，有必去地点+0.1
4. 只输出JSON，不要有其他文字

输出：
"""
    
    def calculate_confidence(self, intent: TravelIntent) -> float:
        """计算信息完整度"""
        score = 0.0
        
        if intent.destination:
            score += 0.2
        if intent.days:
            score += 0.2
        if intent.themes:
            score += 0.1
        if intent.preferences:
            score += 0.1
        if intent.budget_level:
            score += 0.1
        if intent.dates:
            score += 0.1
        if intent.travelers:
            score += 0.1
        if intent.must_visit:
            score += 0.1
        
        return min(score, 1.0)
    
    def get_missing_info(self, intent: TravelIntent) -> list[str]:
        """获取缺失的关键信息"""
        missing = []
        
        if not intent.destination:
            missing.append("目的地")
        if not intent.days:
            missing.append("游玩天数")
        if not intent.themes:
            missing.append("旅行主题偏好")
        if not intent.budget_level:
            missing.append("预算范围")
        if not intent.travelers:
            missing.append("同行人类型")
        
        return missing
    
    def merge_intents(self, old_intent: TravelIntent, new_intent: TravelIntent) -> TravelIntent:
        """合并两个意图（保留更完整的信息）"""
        # 使用新的意图作为基础
        merged = new_intent.copy()
        
        # 如果旧意图有而新意图没有的字段，保留旧的
        if not merged.destination and old_intent.destination:
            merged.destination = old_intent.destination
        if not merged.days and old_intent.days:
            merged.days = old_intent.days
        if not merged.dates and old_intent.dates:
            merged.dates = old_intent.dates
        if not merged.budget_level and old_intent.budget_level:
            merged.budget_level = old_intent.budget_level
        
        # 合并列表字段（去重）
        merged.themes = list(set((old_intent.themes or []) + (new_intent.themes or [])))
        merged.must_visit = list(set((old_intent.must_visit or []) + (new_intent.must_visit or [])))
        merged.preferences = list(set((old_intent.preferences or []) + (new_intent.preferences or [])))
        merged.travelers = list(set((old_intent.travelers or []) + (new_intent.travelers or [])))
        merged.extracted_from = list(set((old_intent.extracted_from or []) + (new_intent.extracted_from or [])))
        
        # 重新计算完整度
        merged.confidence = self.calculate_confidence(merged)
        merged.last_updated = datetime.now()
        
        return merged
