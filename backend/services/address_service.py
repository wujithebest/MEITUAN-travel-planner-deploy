"""
地址搜索服务 - 调用高德输入提示API
"""
import logging
import httpx
from typing import Optional
from config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()


async def search_address(keyword: str, city: Optional[str] = None) -> list:
    """
    调用高德输入提示API搜索地址
    
    Args:
        keyword: 用户输入的关键词（至少2个字）
        city: 限制搜索的城市名称
    
    Returns:
        格式化后的地址列表 [{"name", "address", "location", "district"}]
    """
    try:
        params = {
            "key": settings.gaode_key,
            "keywords": keyword,
            "city": city or "",
            "datatype": "all",  # 改为 all 获取更全面的结果
            "page_size": 10,
        }
        
        # 只有当城市不为空时才添加 citylimit
        if city:
            params["citylimit"] = "true"
        
        url = "https://restapi.amap.com/v3/assistant/inputtips"
        
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get(url, params=params)
            data = response.json()
        
        # 关键：处理高德返回的错误状态
        if data.get("status") != "1":
            error_info = data.get("info", "未知错误")
            logger.error(f"[AddressService] 高德API错误: {error_info}")
            return []
        
        tips = data.get("tips", [])
        
        # 格式化结果
        results = []
        for tip in tips:
            # 过滤掉没有名称的条目
            name = tip.get("name", "").strip()
            if not name:
                continue
            
            # 解析location "lng,lat"
            location_str = tip.get("location", "")
            lng, lat = None, None
            if location_str and "," in location_str:
                parts = location_str.split(",")
                try:
                    lng = float(parts[0])
                    lat = float(parts[1])
                except (ValueError, IndexError):
                    pass
            
            results.append({
                "name": name,
                "address": tip.get("address", "") or name,
                "location": {
                    "lng": lng,
                    "lat": lat
                } if lng and lat else None,
                "district": tip.get("district", ""),
            })
        
        logger.info(f"[AddressService] 搜索 '{keyword}' 返回 {len(results)} 条结果")
        return results
    
    except httpx.TimeoutException:
        logger.error("[AddressService] 高德API请求超时")
        return []
    except Exception as e:
        logger.error(f"[AddressService] 地址搜索失败: {e}")
        return []


async def get_districts(keywords: str = "中国", subdistrict: int = 1) -> list:
    """
    调用高德行政区划API获取省/市/区数据

    Args:
        keywords: 查询关键词，如"中国"获取省级，"110000"获取北京市下级
        subdistrict: 下级行政区层级，1=下一级，2=下两级

    Returns:
        行政区划列表 [{"name", "adcode", "level", "children": [...]}]
    """
    try:
        params = {
            "key": settings.gaode_key,
            "keywords": keywords,
            "subdistrict": subdistrict,
            "extensions": "base",
        }

        url = "https://restapi.amap.com/v3/config/district"

        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get(url, params=params)
            data = response.json()

        if data.get("status") != "1":
            logger.error(f"[AddressService] 行政区划API错误: {data.get('info')}")
            return []

        districts = data.get("districts", [])

        # Flatten: Gaode wraps results in their parent district (country/province/city).
        # When there's a single result with children, return the children directly.
        if len(districts) == 1 and districts[0].get("districts"):
            districts = districts[0].get("districts", [])

        results = []

        for d in districts:
            item = {
                "name": d.get("name", ""),
                "adcode": d.get("adcode", ""),
                "level": d.get("level", ""),
            }
            children = d.get("districts", [])
            if children:
                item["children"] = [
                    {
                        "name": c.get("name", ""),
                        "adcode": c.get("adcode", ""),
                        "level": c.get("level", ""),
                        "children": [
                            {"name": gc.get("name", ""), "adcode": gc.get("adcode", ""), "level": gc.get("level", "")}
                            for gc in c.get("districts", [])
                        ] if c.get("districts") else []
                    }
                    for c in children
                ]
            results.append(item)

        logger.info(f"[AddressService] 行政区划查询 '{keywords}' 返回 {len(results)} 条")
        return results

    except httpx.TimeoutException:
        logger.error("[AddressService] 行政区划API请求超时")
        return []
    except Exception as e:
        logger.error(f"[AddressService] 行政区划查询失败: {e}")
        return []


async def reverse_geocode(lng: float, lat: float) -> dict | None:
    """
    逆地理编码：根据经纬度获取地址信息

    Args:
        lng: 经度
        lat: 纬度

    Returns:
        {"province", "city", "district", "address", "lng", "lat"} 或 None
    """
    try:
        params = {
            "key": settings.gaode_key,
            "location": f"{lng},{lat}",
        }

        url = "https://restapi.amap.com/v3/geocode/regeo"

        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get(url, params=params)
            data = response.json()

        if data.get("status") != "1":
            logger.error(f"[AddressService] 逆地理编码失败: {data.get('info')}")
            return None

        regeo = data.get("regeocode", {})
        addr_component = regeo.get("addressComponent", {})

        return {
            "province": addr_component.get("province", ""),
            "city": addr_component.get("city", "") or addr_component.get("province", ""),
            "district": addr_component.get("district", ""),
            "address": regeo.get("formatted_address", ""),
            "lng": lng,
            "lat": lat,
        }

    except Exception as e:
        logger.error(f"[AddressService] 逆地理编码失败: {e}")
        return None
