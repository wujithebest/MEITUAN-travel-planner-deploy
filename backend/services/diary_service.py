"""
旅行日记服务 - 上海专用
自动生成文字、上海特色成就徽章、统计数据
支持照片归档、导出（Pillow长图/PDF）
集成高德地图截图功能 + 卡通风格处理
"""

import logging
import json
import uuid
from typing import Optional, List, Any
from datetime import datetime, date, time

from models.diary import (
    Diary, DiaryEntry, DiaryStats, Achievement,
)
from models.route import RouteResponse, DailyRoute
from models.base import POI
from services.llm_parser import get_llm_parser
from services.map_screenshot_service import get_map_screenshot_service
from services.map_cartoon_service import get_map_cartoon_service, MapStyle
from exceptions import DiaryError

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
    
    Args:
        obj: 任意对象
        
    Returns:
        转换后的可序列化对象
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
    elif hasattr(obj, 'model_dump'):
        # 处理Pydantic模型
        try:
            return _make_serializable(obj.model_dump())
        except Exception:
            return obj
    elif hasattr(obj, '__dict__'):
        # 处理普通对象
        try:
            return _make_serializable(obj.__dict__)
        except Exception:
            return obj
    return obj

# 内存存储（生产环境应使用数据库）
_diary_store: dict[str, Diary] = {}


# 上海特色成就定义
ACHIEVEMENTS_DEF = [
    {
        "id": "first_trip",
        "name": "初次旅行",
        "description": "完成第一次旅行计划",
        "icon": "🎒",
        "condition": lambda stats: stats["days"] >= 1
    },
    {
        "id": "explorer",
        "name": "探险家",
        "description": "游览超过10个POI",
        "icon": "🗺️",
        "condition": lambda stats: stats["poi_count"] >= 10
    },
    {
        "id": "marathon",
        "name": "旅行马拉松",
        "description": "累计行程超过100公里",
        "icon": "🏃",
        "condition": lambda stats: stats["total_distance"] >= 100000
    },
    {
        "id": "photographer",
        "name": "摄影师",
        "description": "上传20张以上照片",
        "icon": "📸",
        "condition": lambda stats: stats["photo_count"] >= 20
    },
    {
        "id": "smooth_traveler",
        "name": "从容旅者",
        "description": "流畅度评分平均8分以上",
        "icon": "✨",
        "condition": lambda stats: stats["avg_smoothness"] >= 8
    },
    # 上海特色成就
    {
        "id": "cross_huangpu",
        "name": "跨越黄浦江",
        "description": "游览了浦东和浦西的景点",
        "icon": "🌉",
        "condition": lambda stats: stats.get("cross_river", False)
    },
    {
        "id": "fachengjie",
        "name": "打卡法租界",
        "description": "游览了原法租界区域景点（徐汇/静安/长宁）",
        "icon": "🏛️",
        "condition": lambda stats: stats.get("fachengjie", False)
    },
    {
        "id": "the_bund",
        "name": "外滩打卡",
        "description": "游览了外滩",
        "icon": "🌃",
        "condition": lambda stats: stats.get("the_bund", False)
    },
    {
        "id": "lujiazui",
        "name": "陆家嘴之巅",
        "description": "游览了陆家嘴金融中心",
        "icon": "🏙️",
        "condition": lambda stats: stats.get("lujiazui", False)
    },
    {
        "id": "yuyuan",
        "name": "豫园寻梦",
        "description": "游览了豫园/城隍庙",
        "icon": "🏮",
        "condition": lambda stats: stats.get("yuyuan", False)
    },
    {
        "id": "xintiandi",
        "name": "新天地之夜",
        "description": "游览了新天地",
        "icon": "🍷",
        "condition": lambda stats: stats.get("xintiandi", False)
    },
    {
        "id": "museum_explorer",
        "name": "博物馆达人",
        "description": "游览了3个以上博物馆",
        "icon": "🏛️",
        "condition": lambda stats: stats.get("museum_count", 0) >= 3
    },
    {
        "id": "disney_dream",
        "name": "迪士尼圆梦",
        "description": "游览了上海迪士尼度假区",
        "icon": "🏰",
        "condition": lambda stats: stats.get("disney", False)
    },
    {
        "id": "nanjing_road",
        "name": "南京路漫步",
        "description": "游览了南京路",
        "icon": "🛍️",
        "condition": lambda stats: stats.get("nanjing_road", False)
    },
    {
        "id": "shikumen",
        "name": "石库门记忆",
        "description": "游览了石库门建筑群",
        "icon": "🏠",
        "condition": lambda stats: stats.get("shikumen", False)
    },
]


# 上海特色POI关键词映射
SHANGHAI_ACHIEVEMENT_KEYWORDS = {
    "the_bund": ["外滩", "万国建筑群"],
    "lujiazui": ["陆家嘴", "东方明珠", "金茂大厦", "上海中心", "环球金融中心"],
    "yuyuan": ["豫园", "城隍庙", "九曲桥"],
    "xintiandi": ["新天地", "新天地北里", "新天地南里"],
    "fachengjie": ["武康路", "衡山路", "思南路", "田子坊", "新天地"],  # 原法租界区域
    "disney": ["迪士尼", "Disney", "迪士尼乐园"],
    "nanjing_road": ["南京路", "南京东路", "南京西路"],
    "shikumen": ["石库门", "田子坊", "新天地"],
}


class DiaryService:
    """旅行日记服务"""

    def __init__(self):
        self.llm_parser = get_llm_parser()
        self.map_screenshot = get_map_screenshot_service()
        self.map_cartoon = get_map_cartoon_service()

    async def generate_diary(
        self, 
        route: RouteResponse,
        map_style: MapStyle = MapStyle.CARTOON
    ) -> Diary:
        """
        根据路线自动生成旅行日记
        
        Args:
            route: 路线响应数据
            map_style: 地图卡通风格
            
        Returns:
            Diary: 生成的旅行日记
        """
        diary_id = str(uuid.uuid4())[:12]

        # 提取统计数据
        stats = self._extract_stats(route)

        # 生成日记条目
        entries = self._generate_entries(route)

        # 为每日路线生成卡通地图截图
        await self._generate_daily_map_snapshots(route, map_style)

        # 计算成就
        achievements = self._check_achievements(stats)

        # LLM润色 - 使用_make_serializable处理datetime序列化
        polished_text = ""
        try:
            # 转换entries和stats为可序列化格式
            serializable_entries = _make_serializable([e.model_dump() for e in entries])
            serializable_stats = _make_serializable(stats.model_dump())
            
            polished_text = await self.llm_parser.polish_diary(
                serializable_entries,
                serializable_stats
            )
            
            # 如果LLM返回空文本，使用降级处理
            if not polished_text or not polished_text.strip():
                logger.warning("LLM返回空文本，使用降级处理")
                polished_text = self._generate_default_text(route, entries, stats)
        except Exception as e:
            logger.warning(f"LLM润色失败: {str(e)}，使用降级处理")
            polished_text = self._generate_default_text(route, entries, stats)

        diary = Diary(
            diary_id=diary_id,
            route_id=route.route_id,
            title=self._generate_title(route),
            subtitle=f"{stats.days}天{stats.poi_count}个目的地 · {stats.total_distance/1000:.1f}公里",
            entries=entries,
            achievements=achievements,
            stats=stats,
            polished_text=polished_text
        )

        _diary_store[diary_id] = diary
        logger.info(f"日记生成成功: {diary_id}")
        return diary
    
    async def _generate_daily_map_snapshots(
        self, 
        route: RouteResponse,
        map_style: MapStyle = MapStyle.CARTOON
    ) -> None:
        """
        为每日路线生成卡通风格地图截图
        
        Args:
            route: 路线响应数据
            map_style: 地图卡通风格
        """
        for daily in route.daily_routes:
            # 确保polyline存在
            polyline = daily.polyline
            if not polyline:
                # 尝试从points中的route获取
                for point in daily.points:
                    if point.polyline:
                        polyline = point.polyline
                        break
            
            if not polyline:
                logger.info(f"第{daily.day}天没有polyline，跳过地图截图生成")
                continue
            
            try:
                # 提取POI列表用于标记
                pois = []
                for point in daily.points:
                    if point.poi:
                        pois.append(point.poi)
                
                if not pois:
                    logger.info(f"第{daily.day}天没有POI，跳过地图截图生成")
                    continue
                
                # 生成地图截图（日记用大图）
                snapshot = await self.map_screenshot.generate_route_snapshot(
                    polyline=polyline,
                    pois=pois,
                    width=1200,
                    height=600
                )
                
                # 应用卡通风格处理
                cartoon_snapshot = self.map_cartoon.process_image(
                    image_data=snapshot,
                    style=map_style,
                    width=1200,
                    height=600
                )
                
                # 保存到daily route
                daily.map_snapshot = cartoon_snapshot
                logger.info(f"第{daily.day}天卡通地图截图生成成功 (风格: {map_style})")
                
            except Exception as e:
                logger.error(f"第{daily.day}天地图截图生成失败: {str(e)}")
                # 降级：尝试保存原始截图
                try:
                    if 'snapshot' in locals():
                        daily.map_snapshot = snapshot
                except:
                    pass
    
    async def generate_map_snapshot(
        self,
        polyline: str,
        pois: List[POI],
        width: int = 750,
        height: int = 400
    ) -> str:
        """
        生成地图截图（公开方法，供路由调用）
        
        Args:
            polyline: 坐标串
            pois: POI列表
            width: 图片宽度
            height: 图片高度
            
        Returns:
            str: 图片base64或URL
        """
        return await self.map_screenshot.generate_route_snapshot(
            polyline=polyline,
            pois=pois,
            width=width,
            height=height
        )
    
    async def generate_cartoon_map(
        self,
        polyline: str,
        pois: List[POI],
        style: MapStyle = MapStyle.CARTOON,
        width: int = 1200,
        height: int = 600
    ) -> str:
        """
        生成卡通风格地图（公开方法）
        
        Args:
            polyline: 坐标串
            pois: POI列表
            style: 卡通风格
            width: 图片宽度
            height: 图片高度
            
        Returns:
            str: 卡通地图base64字符串
        """
        # 先生成原始截图
        snapshot = await self.map_screenshot.generate_route_snapshot(
            polyline=polyline,
            pois=pois,
            width=width,
            height=height
        )
        
        # 应用卡通风格
        cartoon_snapshot = self.map_cartoon.process_image(
            image_data=snapshot,
            style=style,
            width=width,
            height=height
        )
        
        return cartoon_snapshot

    async def add_entry(self, diary_id: str, entry_data: dict) -> DiaryEntry:
        """添加日记条目"""
        diary = _diary_store.get(diary_id)
        if not diary:
            raise DiaryError(f"日记不存在: {diary_id}")

        entry = DiaryEntry(
            entry_id=str(uuid.uuid4())[:12],
            day=entry_data.get("day", 0),
            title=entry_data.get("title", ""),
            content=entry_data.get("content", ""),
            poi_name=entry_data.get("poi_name", ""),
            is_highlight=entry_data.get("is_highlight", False)
        )

        diary.entries.append(entry)
        diary.updated_at = datetime.now()

        # 更新统计
        diary.stats.photo_count = sum(len(e.photos) for e in diary.entries)

        return entry

    async def add_photo(self, diary_id: str, entry_id: str, photo_url: str) -> None:
        """添加照片"""
        diary = _diary_store.get(diary_id)
        if not diary:
            raise DiaryError(f"日记不存在: {diary_id}")

        for entry in diary.entries:
            if entry.entry_id == entry_id:
                entry.photos.append(photo_url)
                diary.stats.photo_count = sum(len(e.photos) for e in diary.entries)
                return

        raise DiaryError(f"条目不存在: {entry_id}")

    async def update_entry(self, diary_id: str, entry_id: str, entry_data: dict) -> DiaryEntry:
        """更新日记条目"""
        diary = _diary_store.get(diary_id)
        if not diary:
            raise DiaryError(f"日记不存在: {diary_id}")

        for entry in diary.entries:
            if entry.entry_id != entry_id:
                continue
            for field in ("title", "content", "poi_name", "is_highlight"):
                value = entry_data.get(field)
                if value is not None:
                    setattr(entry, field, value)
            diary.updated_at = datetime.now()
            return entry

        raise DiaryError(f"条目不存在: {entry_id}")

    async def get_diary(self, diary_id: str) -> Diary:
        """获取日记"""
        diary = _diary_store.get(diary_id)
        if not diary:
            raise DiaryError(f"日记不存在: {diary_id}")
        return diary

    async def export_diary(self, diary_id: str, format: str = "image") -> dict:
        """
        导出日记
        
        Args:
            diary_id: 日记ID
            format: 导出格式 (image/pdf/h5)
            
        Returns:
            dict: 导出结果
        """
        diary = await self.get_diary(diary_id)

        if format == "image":
            return await self._export_image(diary)
        elif format == "pdf":
            return await self._export_pdf(diary)
        elif format == "h5":
            return await self._export_h5(diary)
        else:
            raise DiaryError(f"不支持的导出格式: {format}")

    def _extract_stats(self, route: RouteResponse) -> DiaryStats:
        """从路线提取统计数据（上海专用）"""
        cities = set()
        districts = set()
        transport_stats = {}
        total_notes = 0
        smoothness_scores = []
        museum_count = 0
        
        # 上海特色标记
        poi_names = []
        for daily in route.daily_routes:
            for point in daily.points:
                if point.poi:
                    poi_names.append(point.poi.name.lower())
                    if point.poi.city:
                        cities.add(point.poi.city)
                    if point.poi.district:
                        districts.add(point.poi.district)
                    if point.transport_from_prev:
                        mode = point.transport_from_prev.value
                        transport_stats[mode] = transport_stats.get(mode, 0) + 1
                    if point.note:
                        total_notes += 1
                    # 统计博物馆
                    if "博物馆" in point.poi.name or "纪念馆" in point.poi.name:
                        museum_count += 1
            if daily.smoothness_score > 0:
                smoothness_scores.append(daily.smoothness_score)

        # 判断是否跨江（浦东浦西）
        pudong_districts = {"浦东新区"}
        puxi_districts = {"黄浦区", "徐汇区", "长宁区", "静安区", "普陀区", "杨浦区", "虹口区"}
        cross_river = bool(districts & pudong_districts) and bool(districts & puxi_districts)

        # 判断是否打卡法租界
        fachengjie_districts = {"徐汇区", "静安区", "长宁区"}
        fachengjie = bool(districts & fachengjie_districts)

        # 检查上海特色POI
        shanghai_achievements = {}
        for achievement_key, keywords in SHANGHAI_ACHIEVEMENT_KEYWORDS.items():
            for keyword in keywords:
                if any(keyword.lower() in name for name in poi_names):
                    shanghai_achievements[achievement_key] = True
                    break

        return DiaryStats(
            total_distance=route.total_distance,
            total_duration=route.total_duration,
            poi_count=len(route.waypoints) + (1 if route.origin else 0) + (1 if route.destination else 0),
            city_count=len(cities),
            transport_stats=transport_stats,
            photo_count=0,
            cross_river=cross_river,
            fachengjie=fachengjie,
            **shanghai_achievements,
            museum_count=museum_count,
            avg_smoothness=sum(smoothness_scores) / len(smoothness_scores) if smoothness_scores else 0,
            note_count=total_notes,
            days=len(route.daily_routes)
        )

    def _generate_entries(self, route: RouteResponse) -> list[DiaryEntry]:
        """生成日记条目"""
        entries = []
        for daily in route.daily_routes:
            for point in daily.points:
                if not point.poi:
                    continue
                entry = DiaryEntry(
                    entry_id=str(uuid.uuid4())[:12],
                    day=daily.day,
                    title=f"游览 {point.poi.name}",
                    content=self._generate_entry_content(point, daily),
                    poi_name=point.poi.name,
                    is_highlight=point.poi.rating >= 4.5 if point.poi.rating else False
                )
                entries.append(entry)
        return entries

    def _generate_entry_content(self, point, daily) -> str:
        """生成条目内容"""
        parts = []
        if point.arrival_time:
            parts.append(f"于{point.arrival_time.strftime('%H:%M')}到达{point.poi.name}")
        if point.stay_minutes > 0:
            parts.append(f"停留约{point.stay_minutes}分钟")
        if point.poi.rating > 0:
            parts.append(f"评分: {point.poi.rating}/5.0")
        if point.weather and point.weather.weather_tip:
            parts.append(point.weather.weather_tip)
        if point.note:
            parts.append(point.note)
        return "。".join(parts) if parts else f"游览了{point.poi.name}"

    def _generate_title(self, route: RouteResponse) -> str:
        """生成日记标题"""
        if route.origin and route.destination:
            return f"{route.origin.city} → {route.destination.city} 之旅"
        elif route.waypoints:
            cities = list(dict.fromkeys(p.city for p in route.waypoints if p.city))
            if len(cities) >= 2:
                return f"{'·'.join(cities[:3])} 之旅"
            elif cities:
                return f"{cities[0]} 之旅"
        return "我的旅行日记"

    def _generate_default_text(
        self, route: RouteResponse, entries: list[DiaryEntry], stats: DiaryStats
    ) -> str:
        """生成默认文字（LLM失败时的降级）"""
        lines = [
            f"# {self._generate_title(route)}",
            "",
            f"这是一场为期{len(route.daily_routes)}天的旅行，",
            f"共游览了{stats.poi_count}个目的地，",
            f"行程总计{stats.total_distance/1000:.1f}公里。",
            "",
            "## 行程概览",
        ]

        for daily in route.daily_routes:
            lines.append(f"\n### 第{daily.day}天 ({daily.date})")
            for point in daily.points:
                if point.poi:
                    lines.append(f"- {point.poi.name}")

        return "\n".join(lines)

    def _check_achievements(self, stats: DiaryStats) -> list[Achievement]:
        """检查成就"""
        unlocked = []
        stats_dict = {
            "days": stats.days,
            "poi_count": stats.poi_count,
            "total_distance": stats.total_distance,
            "city_count": stats.city_count,
            "photo_count": stats.photo_count,
            "avg_smoothness": stats.avg_smoothness,
            "note_count": stats.note_count,
        }

        for ach_def in ACHIEVEMENTS_DEF:
            try:
                if ach_def["condition"](stats_dict):
                    unlocked.append(Achievement(
                        id=ach_def["id"],
                        name=ach_def["name"],
                        description=ach_def["description"],
                        icon=ach_def["icon"]
                    ))
            except Exception:
                continue

        return unlocked

    async def _export_image(self, diary: Diary) -> dict:
        """导出为长图（使用Pillow）"""
        try:
            from PIL import Image, ImageDraw, ImageFont
            width, height = 800, max(600, 200 + len(diary.entries) * 150)
            img = Image.new("RGB", (width, height), color=(255, 255, 255))
            draw = ImageDraw.Draw(img)

            # 标题
            draw.text((40, 40), diary.title, fill=(0, 0, 0))
            draw.text((40, 80), diary.subtitle, fill=(100, 100, 100))

            y = 140
            for entry in diary.entries:
                draw.text((40, y), f"Day {entry.day}: {entry.title}", fill=(50, 50, 50))
                y += 30
                draw.text((60, y), entry.content[:100], fill=(100, 100, 100))
                y += 60

            output_path = f"/tmp/diary_{diary.diary_id}.png"
            img.save(output_path)

            return {
                "success": True,
                "url": output_path,
                "format": "image"
            }
        except ImportError:
            return {"success": False, "message": "Pillow未安装"}

    async def _export_pdf(self, diary: Diary) -> dict:
        """导出为PDF"""
        try:
            from reportlab.lib.pagesizes import A4
            from reportlab.pdfgen import canvas

            output_path = f"/tmp/diary_{diary.diary_id}.pdf"
            c = canvas.Canvas(output_path, pagesize=A4)
            c.drawString(100, 800, diary.title)
            c.drawString(100, 770, diary.subtitle)

            y = 730
            for entry in diary.entries:
                c.drawString(100, y, f"Day {entry.day}: {entry.title}")
                y -= 30
                if y < 100:
                    c.showPage()
                    y = 800

            c.save()
            return {"success": True, "url": output_path, "format": "pdf"}
        except ImportError:
            return {"success": False, "message": "reportlab未安装"}

    async def _export_h5(self, diary: Diary) -> dict:
        """导出为H5链接"""
        html_content = f"""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>{diary.title}</title></head>
<body>
<h1>{diary.title}</h1>
<p>{diary.subtitle}</p>
<div>{diary.polished_text}</div>
</body>
</html>"""
        output_path = f"/tmp/diary_{diary.diary_id}.html"
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html_content)

        return {
            "success": True,
            "url": output_path,
            "format": "h5"
        }


_diary_service: Optional[DiaryService] = None


def get_diary_service() -> DiaryService:
    """获取日记服务单例"""
    global _diary_service
    if _diary_service is None:
        _diary_service = DiaryService()
    return _diary_service
