"""
日记相关模型
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any, Literal
from datetime import datetime


class DiaryStats(BaseModel):
    """日记统计数据"""
    total_distance: float = Field(0.0, description="总距离(米)")
    total_duration: int = Field(0, description="总时长(秒)")
    poi_count: int = Field(0, description="游览POI数量")
    city_count: int = Field(0, description="经过城市数量")
    transport_stats: Dict[str, int] = Field(default_factory=dict, description="交通方式统计")
    photo_count: int = Field(0, description="照片数量")
    
    # 上海特色统计字段
    cross_river: bool = Field(False, description="是否跨黄浦江")
    fachengjie: bool = Field(False, description="是否打卡法租界")
    the_bund: bool = Field(False, description="是否游览外滩")
    lujiazui: bool = Field(False, description="是否游览陆家嘴")
    yuyuan: bool = Field(False, description="是否游览豫园")
    xintiandi: bool = Field(False, description="是否游览新天地")
    museum_count: int = Field(0, description="博物馆数量")
    disney: bool = Field(False, description="是否游览迪士尼")
    nanjing_road: bool = Field(False, description="是否游览南京路")
    shikumen: bool = Field(False, description="是否游览石库门")
    avg_smoothness: float = Field(0.0, description="平均流畅度评分")
    note_count: int = Field(0, description="备注数量")
    days: int = Field(0, description="行程天数")


class DiaryEntry(BaseModel):
    """日记条目"""
    entry_id: str = Field("", description="条目ID")
    day: int = Field(0, description="第几天")
    title: str = Field("", description="标题")
    content: str = Field("", description="内容")
    poi_name: str = Field("", description="关联POI")
    photos: List[str] = Field(default_factory=list, description="照片URL列表")
    voice_memo: str = Field("", description="语音备忘URL")
    is_highlight: bool = Field(False, description="是否标记为高光时刻")
    map_snapshot: Optional[str] = Field(None, description="地图截图(base64或URL)")
    created_at: datetime = Field(default_factory=datetime.now)


class Achievement(BaseModel):
    """成就徽章"""
    id: str = Field("", description="成就ID")
    name: str = Field("", description="成就名称")
    description: str = Field("", description="成就描述")
    icon: str = Field("", description="图标")
    unlocked_at: datetime = Field(default_factory=datetime.now)


class Diary(BaseModel):
    """旅行日记"""
    diary_id: str = Field("", description="日记ID")
    route_id: str = Field("", description="关联路线ID")
    title: str = Field("", description="日记标题")
    subtitle: str = Field("", description="副标题")
    cover_image: str = Field("", description="封面图片URL")
    entries: List[DiaryEntry] = Field(default_factory=list, description="日记条目")
    achievements: List[Achievement] = Field(default_factory=list, description="成就徽章")
    stats: DiaryStats = Field(default_factory=DiaryStats, description="统计数据")
    polished_text: str = Field("", description="LLM润色后的完整文字")
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


class DiaryEntryRequest(BaseModel):
    """添加日记条目请求"""
    diary_id: str = Field(..., description="日记ID")
    day: int = Field(..., description="第几天")
    title: str = Field("", description="标题")
    content: str = Field("", description="内容")
    poi_name: str = Field("", description="关联POI")
    is_highlight: bool = Field(False, description="是否高光")


class DiaryEntryUpdateRequest(BaseModel):
    """更新日记条目请求"""
    title: Optional[str] = Field(None, description="标题")
    content: Optional[str] = Field(None, description="内容")
    poi_name: Optional[str] = Field(None, description="关联POI")
    is_highlight: Optional[bool] = Field(None, description="是否高光")


class DiaryPhotoRequest(BaseModel):
    """添加日记照片请求"""
    diary_id: str = Field(..., description="日记ID")
    entry_id: str = Field(..., description="条目ID")
    photo_url: str = Field(..., description="照片URL或data URL")


class DiaryExportRequest(BaseModel):
    """日记导出请求"""
    diary_id: str = Field(..., description="日记ID")
    format: Literal["image", "pdf", "h5"] = Field("image", description="导出格式")
