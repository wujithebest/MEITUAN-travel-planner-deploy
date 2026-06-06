"""
LLM解析服务 - 上海专用
直接调用OpenAI兼容API，提取自然语言中的上海地点信息
系统仅支持上海市内旅游规划
"""

import json
import logging
import asyncio
import traceback
from typing import Optional, Any
from datetime import datetime, date, time

import httpx
from pydantic import ValidationError

from config import get_settings
from models.llm import LLMParseResult, ParsedLocation
from exceptions import LLMParseError, OutOfShanghaiError

logger = logging.getLogger(__name__)


class DateTimeEncoder(json.JSONEncoder):
    """自定义JSON编码器，处理datetime/date/time类型"""
    
    def default(self, obj: Any) -> Any:
        if isinstance(obj, datetime):
            return obj.isoformat()
        elif isinstance(obj, date):
            return obj.isoformat()
        elif isinstance(obj, time):
            return obj.isoformat()
        return super().default(obj)


def _make_serializable(obj: Any) -> Any:
    """
    递归转换对象中的datetime/date/time为可序列化格式
    """
    if isinstance(obj, datetime):
        return obj.isoformat()
    elif isinstance(obj, date):
        return obj.isoformat()
    elif isinstance(obj, time):
        return obj.isoformat()
    elif isinstance(obj, dict):
        return {k: _make_serializable(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return [_make_serializable(item) for item in obj]
    return obj

# 上海专属系统提示词：强制LLM仅识别上海市内地点
SYSTEM_PROMPT = """你是一个上海市旅游路线规划助手。请分析用户的自然语言旅行需求，识别两种输入模式：

【模式A：精确模式】用户明确列出具体地点，如"先去外滩然后豫园"
【模式B：意图模式】用户只给区域+天数+主题，如"杨浦区玩两天""崇明岛两天""徐汇逛街吃美食"

输出JSON格式，包含以下字段：
- plan_mode: "precise"（精确模式）或 "intent"（意图模式）
- origin: 出发地（如果有），包含name和city_hint（固定为"上海"）
- destination: 目的地（如果有），包含name和city_hint（固定为"上海"）
- waypoints: 途经点数组（精确模式时），每项包含name和city_hint（固定为"上海"）
- intent: 意图信息（意图模式时必填），包含area（区域）、days（天数）、theme（主题）、preferences（偏好）
- preferences: 偏好信息（如预算、兴趣等）
- is_ambiguous: 是否存在歧义地点
- ambiguity_details: 歧义地点的详细信息
- error_message: 如果包含外地地点，返回提示信息

【规则】
1. 只识别上海市内地点，外地地点直接忽略并提示
2. 精确模式：按原逻辑提取waypoints，必须输出至少5个地点（origin + waypoints + destination ≥ 5）
3. 如果用户提供的地点不足5个，自动补充上海市内热门景点补足到5个
4. 意图模式：提取区域、天数、主题，waypoints为空数组
5. 所有地点的city_hint统一为"上海"
6. 温度参数temperature=0.1保证输出稳定

【补充地点策略】
- 如用户只提供1-2个地点，补充同区域或相邻区域的热门景点
- 补充的景点应与用户已提及地点类型互补（如用户提景点，则补充餐饮/购物）
- 优先补充评分高、热门度高的地点

【示例】
示例输入1（精确模式，地点充足）："我想从人民广场出发，上午去上海博物馆，下午逛豫园，晚上去新天地吃饭，再去外滩看夜景"
示例输出1：
{
  "plan_mode": "precise",
  "origin": {"name": "人民广场", "city_hint": "上海"},
  "destination": {"name": "外滩", "city_hint": "上海"},
  "waypoints": [
    {"name": "上海博物馆", "city_hint": "上海"},
    {"name": "豫园", "city_hint": "上海"},
    {"name": "新天地", "city_hint": "上海"}
  ],
  "intent": null,
  "preferences": {},
  "is_ambiguous": false,
  "ambiguity_details": [],
  "error_message": ""
}

示例输入2（精确模式，地点不足）："我想去外滩和东方明珠"
示例输出2：
{
  "plan_mode": "precise",
  "origin": {"name": "外滩", "city_hint": "上海"},
  "destination": {"name": "东方明珠", "city_hint": "上海"},
  "waypoints": [
    {"name": "南京路步行街", "city_hint": "上海"},
    {"name": "豫园", "city_hint": "上海"},
    {"name": "城隍庙", "city_hint": "上海"}
  ],
  "intent": null,
  "preferences": {},
  "is_ambiguous": false,
  "ambiguity_details": [],
  "error_message": ""
}

示例输入3（意图模式）："杨浦区玩两天"
示例输出3：
{
  "plan_mode": "intent",
  "origin": null,
  "destination": null,
  "waypoints": [],
  "intent": {
    "area": "杨浦区",
    "days": 2,
    "theme": "景点",
    "preferences": null
  },
  "preferences": {},
  "is_ambiguous": false,
  "ambiguity_details": [],
  "error_message": ""
}

示例输入4（外地地点）："我想去北京看长城，然后来上海逛外滩"
示例输出4：
{
  "plan_mode": "precise",
  "origin": null,
  "destination": null,
  "waypoints": [
    {"name": "外滩", "city_hint": "上海"},
    {"name": "东方明珠", "city_hint": "上海"},
    {"name": "南京路步行街", "city_hint": "上海"},
    {"name": "豫园", "city_hint": "上海"},
    {"name": "城隍庙", "city_hint": "上海"}
  ],
  "intent": null,
  "preferences": {},
  "is_ambiguous": false,
  "ambiguity_details": [],
  "error_message": "已过滤外地地点（北京、长城），本系统仅支持上海市内旅游规划，已自动补充上海市内热门景点"
}"""


class LLMParser:
    """LLM解析器 - 仅支持上海市内地点"""

    def __init__(self):
        self.settings = get_settings()
        self.base_url = self.settings.llm_base_url.rstrip("/")
        self.api_key = self.settings.llm_api_key
        self.model = self.settings.llm_model
        self.max_retries = 3
        self.retry_delays = [1, 2, 4]  # 指数退避：1s, 2s, 4s

    async def parse_travel_request(self, text: str) -> LLMParseResult:
        """
        解析用户的自然语言旅行请求（仅上海）
        
        Args:
            text: 用户输入的自然语言文本
            
        Returns:
            LLMParseResult: 解析结果
            
        Raises:
            LLMParseError: LLM解析失败时抛出
            OutOfShanghaiError: 检测到外地地点时抛出
        """
        logger.info(f"[LLMParser] 开始执行, 参数: text={text[:100]}...")
        last_error: Optional[Exception] = None

        for attempt in range(self.max_retries):
            try:
                logger.info(f"[LLMParser] 第{attempt + 1}次尝试调用LLM...")
                result = await self._call_llm(text)
                
                # 检查是否有外地地点错误
                if result.error_message and "外地" in result.error_message:
                    logger.warning(f"[LLMParser] 检测到外地地点: {result.error_message}")
                    # 仍然返回结果，但带有错误提示
                    return result
                
                logger.info(f"[LLMParser] 执行完成, 结果: plan_mode={result.plan_mode}, origin={result.origin}, waypoints_count={len(result.waypoints)}")
                return result
            except OutOfShanghaiError:
                logger.error(f"[LLMParser] OutOfShanghaiError, 错误: {traceback.format_exc()}")
                raise  # OutOfShanghaiError直接抛出，不重试
            except LLMParseError:
                logger.error(f"[LLMParser] LLMParseError, 错误: {traceback.format_exc()}")
                raise  # LLMParseError直接抛出，不重试
            except Exception as e:
                last_error = e
                logger.error(f"[LLMParser] 第{attempt + 1}次失败, 错误: {str(e)}, 堆栈: {traceback.format_exc()}")
                if attempt < self.max_retries - 1:
                    logger.info(f"[LLMParser] 等待{self.retry_delays[attempt]}秒后重试...")
                    await asyncio.sleep(self.retry_delays[attempt])

        logger.error(f"[LLMParser] 执行失败, 错误: 已重试{self.max_retries}次, last_error={str(last_error)}")
        raise LLMParseError(f"LM解析失败，已重试{self.max_retries}次: {str(last_error)}")

    async def _call_llm(self, text: str) -> LLMParseResult:
        """
        调用LLM API
        
        Args:
            text: 用户输入文本
            
        Returns:
            LLMParseResult: 解析结果
        """
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": text}
            ],
            "temperature": 0.1,  # 低温保证输出稳定
            "max_tokens": 2048
        }

        logger.info(f"[LLMParser] 调用LLM API: model={self.model}, text={text[:50]}...")

        async with httpx.AsyncClient(timeout=30.0) as client:
            logger.info(f"[LLMParser] 发送HTTP请求到: {url}")
            response = await client.post(url, json=payload, headers=headers)
            logger.info(f"[LLMParser] API响应状态: {response.status_code}")
            response.raise_for_status()
            data = response.json()
            logger.info(f"[LLMParser] API响应内容: {str(data)[:500]}...")

        # 提取回复内容
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        if not content:
            logger.error(f"[LLMParser] LLM返回空内容")
            raise LLMParseError("LLM返回空内容")

        logger.info(f"[LLMParser] LLM原始回复: {content[:200]}...")

        # 解析JSON
        try:
            parsed_data = json.loads(content)
            logger.info(f"[LLMParser] JSON解析成功: {str(parsed_data)[:200]}...")
        except json.JSONDecodeError as e:
            logger.error(f"[LLMParser] JSON解析失败: {str(e)}, 内容: {content[:200]}...")
            raise LLMParseError(f"LLM返回非JSON格式: {str(e)}")

        # Pydantic校验
        try:
            result = LLMParseResult(**parsed_data, raw_text=text)
            logger.info(f"[LLMParser] Pydantic校验通过: plan_mode={result.plan_mode}")
            return result
        except ValidationError as e:
            logger.error(f"[LLMParser] Pydantic校验失败: {str(e)}")
            raise LLMParseError(f"LLM输出校验失败: {str(e)}")

    async def extract_json(self, prompt: str) -> dict:
        """
        从LLM提取JSON格式的数据
        
        Args:
            prompt: 提示词
            
        Returns:
            dict: 解析后的JSON数据
        """
        system_prompt = """你是一个JSON数据提取助手。请根据用户的输入，提取关键信息并以JSON格式输出。
只输出JSON，不要有其他文字。"""

        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.1,  # 低温保证输出稳定
            "max_tokens": 2048
        }

        logger.info(f"[LLMParser] 调用extract_json: prompt={prompt[:100]}...")

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()

        # 提取回复内容
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        if not content:
            logger.error(f"[LLMParser] LLM返回空内容")
            raise LLMParseError("LLM返回空内容")

        logger.info(f"[LLMParser] LLM原始回复: {content[:200]}...")

        # 解析JSON
        try:
            # 尝试提取JSON部分（可能被markdown代码块包裹）
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
            
            result = json.loads(content)
            logger.info(f"[LLMParser] JSON解析成功: {str(result)[:200]}...")
            return result
        except json.JSONDecodeError as e:
            logger.error(f"[LLMParser] JSON解析失败: {str(e)}, 内容: {content[:200]}...")
            raise LLMParseError(f"LLM返回非JSON格式: {str(e)}")

    async def generate(self, prompt: str, system_prompt: str = None, temperature: float = 0.7) -> str:
        """
        调用LLM生成文本回复
        
        Args:
            prompt: 用户提示词
            system_prompt: 系统提示词（可选）
            temperature: 温度参数，控制输出随机性
            
        Returns:
            str: LLM生成的文本回复
            
        Raises:
            LLMParseError: LLM调用失败时抛出
        """
        if system_prompt is None:
            system_prompt = "你是一个有用的AI助手。"

        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            "temperature": temperature,
            "max_tokens": 2048
        }

        logger.info(f"[LLMParser] 调用generate: prompt={prompt[:100]}...")

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(url, json=payload, headers=headers)
                response.raise_for_status()
                data = response.json()

            # 提取回复内容
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            if not content:
                logger.error(f"[LLMParser] LLM返回空内容")
                raise LLMParseError("LLM返回空内容")

            logger.info(f"[LLMParser] generate成功: 回复长度={len(content)}")
            return content

        except httpx.HTTPStatusError as e:
            logger.error(f"[LLMParser] HTTP错误: {e.response.status_code}")
            raise LLMParseError(f"LLM API HTTP错误: {e.response.status_code}")
        except Exception as e:
            logger.error(f"[LLMParser] generate失败: {str(e)}")
            raise LLMParseError(f"LLM生成失败: {str(e)}")

    async def polish_diary(self, entries: list[dict], stats: dict) -> str:
        """
        使用LLM润色上海旅行日记
        
        Args:
            entries: 日记条目列表
            stats: 统计数据
            
        Returns:
            str: 润色后的文字
        """
        system_prompt = """你是一位旅行作家，专注于上海市旅游。请根据用户提供的上海旅行记录，创作一篇优美的旅行日记。
要求：
1. 语言生动优美，富有感染力
2. 按照时间顺序组织
3. 融入上海特色元素（如黄浦江、法租界、石库门、城隍庙等）
4. 融入统计数据和成就
5. 字数800-1500字"""

        try:
            # 使用DateTimeEncoder和_make_serializable处理datetime序列化
            serializable_entries = _make_serializable(entries)
            serializable_stats = _make_serializable(stats)
            
            entries_json = json.dumps(serializable_entries, ensure_ascii=False, cls=DateTimeEncoder)
            stats_json = json.dumps(serializable_stats, ensure_ascii=False, cls=DateTimeEncoder)
            
            user_content = f"上海旅行记录：{entries_json}\n\n统计数据：{stats_json}"
        except Exception as e:
            logger.warning(f"序列化日记数据失败: {str(e)}，使用简化格式")
            # 降级：使用简化格式
            user_content = f"上海旅行记录：{str(entries)[:2000]}\n\n统计数据：{str(stats)[:1000]}"

        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content}
            ],
            "temperature": 0.7  # 稍高温度获得更有创意的输出
        }

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(url, json=payload, headers=headers)
                response.raise_for_status()
                data = response.json()

            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            
            if not content:
                logger.warning("LLM返回空内容，使用降级文本")
                return self._generate_fallback_text(entries, stats)
            
            return content
            
        except httpx.HTTPStatusError as e:
            logger.error(f"LLM API HTTP错误: {e.response.status_code}")
            return self._generate_fallback_text(entries, stats)
        except httpx.TimeoutException:
            logger.error("LLM API 超时")
            return self._generate_fallback_text(entries, stats)
        except Exception as e:
            logger.error(f"LLM润色失败: {str(e)}")
            return self._generate_fallback_text(entries, stats)

    def _generate_fallback_text(self, entries: list[dict], stats: dict) -> str:
        """
        生成降级文本（LLM失败时使用）
        
        Args:
            entries: 日记条目列表
            stats: 统计数据
            
        Returns:
            str: 基础文本
        """
        try:
            days = stats.get("days", 1)
            poi_count = stats.get("poi_count", 0)
            total_distance = stats.get("total_distance", 0)
            
            lines = [
                "# 我的上海旅行日记",
                "",
                f"这是一场为期{days}天的旅行，",
                f"共游览了{poi_count}个目的地，",
                f"行程总计{total_distance/1000:.1f}公里。",
                "",
                "## 行程概览",
            ]

            # 按天分组
            days_dict = {}
            for entry in entries:
                day = entry.get("day", 1)
                if day not in days_dict:
                    days_dict[day] = []
                days_dict[day].append(entry)

            for day_num in sorted(days_dict.keys()):
                lines.append(f"\n### 第{day_num}天")
                for entry in days_dict[day_num]:
                    poi_name = entry.get("poi_name", entry.get("title", "未知地点"))
                    lines.append(f"- {poi_name}")

            return "\n".join(lines)
        except Exception as e:
            logger.error(f"生成降级文本失败: {str(e)}")
            return "旅行日记生成中，请稍后查看。"


# 单例
_llm_parser: Optional[LLMParser] = None


def get_llm_parser() -> LLMParser:
    """获取LLM解析器单例"""
    global _llm_parser
    if _llm_parser is None:
        _llm_parser = LLMParser()
    return _llm_parser
