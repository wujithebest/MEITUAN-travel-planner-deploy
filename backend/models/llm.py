"""
LLM解析相关模型
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any, Literal


class ParsedLocation(BaseModel):
    """LLM解析出的地点信息"""
    name: str = Field(..., description="地点名称")
    city_hint: str = Field(default="", description="城市提示")
    is_origin: bool = Field(default=False, description="是否为出发地")
    is_destination: bool = Field(default=False, description="是否为目的地")
    is_waypoint: bool = Field(default=False, description="是否为途经点")


class IntentModel(BaseModel):
    """意图模型"""
    area: str = Field(..., description="区域，如'杨浦区'、'崇明岛'")
    days: int = Field(default=1, ge=1, le=30, description="旅行天数")
    theme: Optional[str] = Field(None, description="主题，如'工业风'、'生态'、'美食'")
    preferences: Optional[str] = Field(None, description="偏好，如'带老人'、'不爬山'、'拍照好看'")


class LLMParseResult(BaseModel):
    """LLM解析结果"""
    plan_mode: Literal["precise", "intent"] = Field(..., description="计划模式：精确模式或意图模式")
    origin: Optional[ParsedLocation] = Field(default=None, description="出发地")
    destination: Optional[ParsedLocation] = Field(default=None, description="目的地")
    waypoints: List[ParsedLocation] = Field(default_factory=list, description="途经点")
    intent: Optional[IntentModel] = Field(default=None, description="意图信息（意图模式时必填）")
    preferences: Dict[str, Any] = Field(default_factory=dict, description="偏好信息")
    raw_text: str = Field(default="", description="原始输入文本")
    is_ambiguous: bool = Field(default=False, description="是否存在歧义")
    ambiguity_details: List[Dict[str, Any]] = Field(default_factory=list, description="歧义详情")
    error_message: str = Field(default="", description="错误信息（如检测到外地地点时的提示）")
    
    model_config = {"extra": "allow"}
