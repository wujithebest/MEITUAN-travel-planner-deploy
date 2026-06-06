"""
测试景点周边模式修复
"""

import asyncio
import sys
sys.path.insert(0, 'backend')

from services.llm_parser_fixed import LLMParser, SHANGHAI_POPULAR_ATTRACTIONS
from services.intent_planner_fixed2 import IntentPlanner


def test_attraction_recognition():
    """测试景点识别"""
    parser = LLMParser()
    
    test_cases = [
        "迪士尼周边一日游",
        "外滩附近玩两天",
        "去东方明珠玩",
        "豫园周边美食一日游",
        "田子坊附近逛街",
    ]
    
    print("=" * 60)
    print("测试景点周边模式识别")
    print("=" * 60)
    
    for text in test_cases:
        preprocessed = parser._preprocess_attraction_surroundings(text)
        print(f"\n输入: {text}")
        print(f"预处理后: {preprocessed}")
        
        # 检查是否识别到景点
        for keyword, full_name in SHANGHAI_POPULAR_ATTRACTIONS.items():
            if keyword in text:
                print(f"识别到景点: {keyword} -> {full_name}")
                break


async def test_attraction_poi_search():
    """测试景点POI搜索"""
    planner = IntentPlanner()
    
    print("\n" + "=" * 60)
    print("测试景点周边POI搜索")
    print("=" * 60)
    
    # 测试迪士尼
    attraction_area = "迪士尼周边"
    attraction_info = planner._check_attraction_surroundings(attraction_area)
    
    if attraction_info:
        print(f"\n识别到景点: {attraction_info['full_name']}")
        print(f"周边推荐: {attraction_info['nearby_attractions']}")
        print(f"搜索半径: {attraction_info['search_radius']}米")
    else:
        print(f"未识别到景点: {attraction_area}")


def test_attraction_mapping():
    """测试景点映射"""
    print("\n" + "=" * 60)
    print("上海热门景点映射表")
    print("=" * 60)
    
    for keyword, full_name in SHANGHAI_POPULAR_ATTRACTIONS.items():
        print(f"{keyword}: {full_name}")


if __name__ == "__main__":
    # 测试景点识别
    test_attraction_recognition()
    
    # 测试景点映射
    test_attraction_mapping()
    
    # 测试POI搜索（异步）
    asyncio.run(test_attraction_poi_search())
    
    print("\n" + "=" * 60)
    print("测试完成！")
    print("=" * 60)
