"""
调试脚本：测试从MongoDB读取用户地址
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def test_mongodb_location():
    """详细测试MongoDB中的用户地址"""
    print("=" * 60)
    print("调试：MongoDB 用户地址读取")
    print("=" * 60)
    
    from models.mongodb import UserMongoDB
    
    user_id = "9ab50f42-cbe6-463e-8278-d0c3331aaed8"
    
    print(f"\n1️⃣  获取用户: {user_id}")
    user = await UserMongoDB.get_by_id(user_id)
    
    if not user:
        print("   ❌ 用户不存在")
        return
    
    print(f"   用户名: {user.get('username')}")
    print(f"   完整数据: {user}")
    
    print(f"\n2️⃣  检查 location 字段:")
    location_data = user.get("location")
    print(f"   location = {location_data}")
    print(f"   type(location) = {type(location_data)}")
    
    if location_data:
        print(f"\n3️⃣  检查 home_address:")
        home_address = location_data.get("home_address")
        print(f"   home_address = {home_address}")
        print(f"   type(home_address) = {type(home_address)}")
        
        if home_address:
            print(f"\n4️⃣  检查经纬度:")
            lat = home_address.get("lat")
            lng = home_address.get("lng")
            name = home_address.get("name")
            print(f"   lat = {lat} (type: {type(lat)})")
            print(f"   lng = {lng} (type: {type(lng)})")
            print(f"   name = {name}")
            
            if lat is not None and lng is not None:
                print(f"\n   ✅ 可以返回地址: lat={lat}, lng={lng}, label={name}")
            else:
                print(f"\n   ❌ lat 或 lng 为 None")
        else:
            print(f"\n   ❌ home_address 为 None 或空")
    else:
        print(f"\n   ❌ location 为 None 或空")
    
    print(f"\n5️⃣  现在测试 mock_profile.get_user_home_location:")
    from services.mock_profile import get_user_home_location
    
    location = await get_user_home_location(user_id)
    print(f"   结果: {location}")


if __name__ == "__main__":
    asyncio.run(test_mongodb_location())
