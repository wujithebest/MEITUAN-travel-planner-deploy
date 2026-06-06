"""
Step4输出适配器
将 run_step4 的 push_output 内容捕获并格式化为 AI助手聊天消息
"""
from __future__ import annotations
import re
from datetime import datetime
from typing import Any
from models.chat import ChatMessage, MessageSender, MessageContent
from services.data_schema import CompletePlan, MicroPOI, ParsedIntent, RouteSegment
from services.utils import PipelineLogger
import logging

logger = logging.getLogger(__name__)


class Step4OutputAdapter:
    """
    捕获 run_step4 的 push_output 内容，聚合为完整的 AI助手消息
    """
    
    def __init__(self):
        self._outputs: list[str] = []
        self._capture_enabled = False
    
    def start_capture(self):
        """开始捕获输出"""
        self._outputs = []
        self._capture_enabled = True
        logger.info("[Step4Adapter] 开始捕获输出")
    
    def stop_capture(self):
        """停止捕获输出"""
        self._capture_enabled = False
        logger.info(f"[Step4Adapter] 停止捕获，共捕获 {len(self._outputs)} 条输出")
    
    async def capture_push_output(self, message: str):
        """
        替代原始的 push_output，捕获输出内容
        这个方法应该在 run_step4 中被调用
        """
        if self._capture_enabled:
            self._outputs.append(message)
            logger.debug(f"[Step4Adapter] 捕获输出: {message[:50]}...")
    
    def get_captured_outputs(self) -> list[str]:
        """获取捕获的输出列表"""
        return list(self._outputs)
    
    def format_as_chat_message(
        self,
        room_id: str,
        summary: str,
        days_data: list[dict],
        anchors: list[dict],
        total_distance: str = "",
        map_url: str = "",
    ) -> ChatMessage:
        """
        将捕获的输出格式化为 ChatMessage (itinerary_preview 类型)
        
        Args:
            room_id: 聊天室ID
            summary: 行程摘要
            days_data: 每日行程数据列表
            anchors: 锚点列表（含推荐理由）
            total_distance: 总距离
            map_url: 地图URL
            
        Returns:
            ChatMessage 对象
        """
        # 构建 route_data
        route_data = {
            "summary": summary,
            "days": days_data,
            "anchors": anchors,
            "total_distance": total_distance,
            "map_url": map_url,
        }
        
        # 构建完整文本（用于显示）
        text_parts = [summary, ""]
        for day in days_data:
            text_parts.append(f"【Day{day['day_index']}】")
            text_parts.append(day["detail"])
            text_parts.append("")
        
        if anchors:
            text_parts.append("✨ 推荐理由：")
            for anchor in anchors:
                text_parts.append(f"· {anchor['name']}：{anchor['reason']}")
        
        full_text = "\n".join(text_parts)
        
        return ChatMessage(
            id=f"agent_itinerary_{datetime.now().timestamp()}",
            room_id=room_id,
            sender=MessageSender(
                id="agent_travel",
                name="AI旅行助手",
                avatar="/agent-avatar.png",
                is_agent=True,
                agent_type="travel_assistant"
            ),
            content=MessageContent(
                type="itinerary_preview",
                text=full_text,
                route_data=route_data
            ),
            timestamp=datetime.now().isoformat()
        )
    
    def parse_outputs_to_structured_data(self) -> dict[str, Any]:
        """
        将捕获的输出解析为结构化数据
        
        Returns:
            dict with keys: summary, days, anchors, map_url, total_distance
        """
        summary = ""
        days = []
        anchors = []
        map_url = ""
        total_distance = ""
        
        current_day = None
        
        for output in self._outputs:
            # 解析摘要行
            if output.startswith("为您规划了"):
                summary = output
                continue
            
            # 解析 Day 标题
            day_match = re.match(r"【Day(\d+)】", output)
            if day_match:
                if current_day:
                    days.append(current_day)
                current_day = {
                    "day_index": int(day_match.group(1)),
                    "title": f"Day{day_match.group(1)}",
                    "detail": output,
                    "anchors": [],
                    "polyline": ""
                }
                continue
            
            # 解析推荐理由行
            reason_match = re.match(r"· (.+?)：(.+)", output)
            if reason_match:
                anchors.append({
                    "name": reason_match.group(1),
                    "reason": reason_match.group(2)
                })
                continue
            
            # 解析地图URL
            if "[ROUTE_PLANNER]:" in output and "地图" in output:
                url_match = re.search(r"点击查看：(.+)", output)
                if url_match:
                    map_url = url_match.group(1).strip()
                continue
            
            # 天气警告
            if "天气" in output and "建议" in output:
                if current_day:
                    current_day["detail"] += "\n" + output
                continue
            
            # 其他内容（追加到当前天的详情）
            if current_day and not output.startswith("[ROUTE_PLANNER]"):
                current_day["detail"] += "\n" + output
        
        # 添加最后一天
        if current_day:
            days.append(current_day)
        
        return {
            "summary": summary,
            "days": days,
            "anchors": anchors,
            "map_url": map_url,
            "total_distance": total_distance
        }


async def run_step4_with_capture(
    room_id: str,
    parsed_intent: ParsedIntent,
    complete_plan: CompletePlan,
    micro_pois: list[MicroPOI],
    route_segments: list[RouteSegment],
    map_file_path: str,
    logger: PipelineLogger,
    anchor_hints: dict[str, str] | None = None,
    waypoint_annotations: dict[str, dict[str, Any]] | None = None,
) -> ChatMessage:
    """
    运行 run_step4 并捕获输出，返回格式化的 ChatMessage
    
    这个函数替代原始的 run_step4 调用，用于聊天场景
    
    Args:
        room_id: 聊天室ID
        其他参数同 run_step4
        
    Returns:
        ChatMessage 对象，可直接发送到聊天室
    """
    from services.step4_output import run_step4, _all_anchors, _day_detail, _origin_label, _duration_desc
    
    adapter = Step4OutputAdapter()
    adapter.start_capture()
    
    try:
        # 手动执行 run_step4 的逻辑，但捕获输出
        logger.start_step("step_4_output")
        
        anchors = _all_anchors(complete_plan)
        first_anchor = anchors[0].name if anchors else "出发点"
        last_anchor = anchors[-1].name if anchors else first_anchor
        origin = _origin_label(parsed_intent)
        meal_suffix = "，含餐饮推荐" if any(item.is_meal for item in micro_pois) else ""
        
        if first_anchor == last_anchor:
            summary = f"为您规划了{_duration_desc(parsed_intent)}的{complete_plan.city}之旅，从{origin}出发，以{first_anchor}为核心{meal_suffix}。"
        else:
            summary = f"为您规划了{_duration_desc(parsed_intent)}的{complete_plan.city}之旅，从{origin}出发，串联{first_anchor}到{last_anchor}{meal_suffix}。"
        
        await adapter.capture_push_output(summary)
        
        # 收集每日数据
        days_data = []
        for day in complete_plan.day_plans:
            day_detail = _day_detail(day, parsed_intent, micro_pois, route_segments, anchor_hints, waypoint_annotations)
            await adapter.capture_push_output(day_detail)
            
            # 解析当天的锚点
            day_anchors = [anchor.name for anchor in day.anchors]
            days_data.append({
                "day_index": day.day_index,
                "title": f"Day{day.day_index}",
                "detail": day_detail,
                "anchors": day_anchors,
                "polyline": ""  # 可从 route_segments 提取
            })
        
        # 收集推荐理由
        anchors_data = []
        for anchor in anchors:
            reason_line = f"· {anchor.name}：{anchor.recommend_reason}"
            await adapter.capture_push_output(reason_line)
            anchors_data.append({
                "name": anchor.name,
                "reason": anchor.recommend_reason
            })
        
        await adapter.capture_push_output(f"[ROUTE_PLANNER]: 完整路线地图已按天生成，点击查看：{map_file_path}")
        
        # 计算总距离
        total_distance = f"{sum(seg.distance_km for seg in route_segments):.1f}km"
        
        # 格式化消息
        chat_message = adapter.format_as_chat_message(
            room_id=room_id,
            summary=summary,
            days_data=days_data,
            anchors=anchors_data,
            total_distance=total_distance,
            map_url=map_file_path
        )
        
        await logger.log_step("step_4_output", output_count=len(anchors) + len(complete_plan.day_plans) + 1)
        
        return chat_message
        
    finally:
        adapter.stop_capture()


# 全局适配器实例
_step4_adapter: Step4OutputAdapter | None = None


def get_step4_adapter() -> Step4OutputAdapter:
    """获取 Step4OutputAdapter 单例"""
    global _step4_adapter
    if _step4_adapter is None:
        _step4_adapter = Step4OutputAdapter()
    return _step4_adapter
