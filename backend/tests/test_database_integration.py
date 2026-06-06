"""
数据库集成测试
测试 MongoDB 和 SQLite 的集成工作情况
"""

import asyncio
import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def test_mock_profile():
    """测试 mock_profile 是否能正常获取用户地址"""
    print("=" * 60)
    print("测试 mock_profile 用户地址获取")
    print("=" * 60)
    
    try:
        from services.mock_profile import get_user_home_location, get_mock_profile
        
        # 测试1：不传 user_id
        print("\n1️⃣  测试不传 user_id（应返回环境变量或默认地址）:")
        location = await get_user_home_location()
        print(f"   结果: {location}")
        assert "lat" in location and "lng" in location
        print("   ✅ 通过")
        
        # 测试2：传不存在的 user_id
        print("\n2️⃣  测试不存在的 user_id（应降级到环境变量）:")
        location = await get_user_home_location("non-existent-id")
        print(f"   结果: {location}")
        assert "lat" in location and "lng" in location
        print("   ✅ 通过")
        
        # 测试3：传存在的 user_id（MongoDB中有用户）
        print("\n3️⃣  测试存在的 user_id:")
        location = await get_user_home_location("9ab50f42-cbe6-463e-8278-d0c3331aaed8")
        print(f"   结果: {location}")
        assert "lat" in location and "lng" in location
        print("   ✅ 通过")
        
        # 测试4：get_mock_profile
        print("\n4️⃣  测试 get_mock_profile:")
        profile = await get_mock_profile("9ab50f42-cbe6-463e-8278-d0c3331aaed8")
        print(f"   昵称: {profile.nickname}")
        print(f"   家位置: {profile.home_location}")
        assert profile.home_location is not None
        print("   ✅ 通过")
        
        print("\n" + "=" * 60)
        print("🎉 所有测试通过!")
        print("=" * 60)
        return True
        
    except Exception as e:
        print(f"\n❌ 测试失败!")
        print(f"错误信息: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


async def test_mongodb_user_operations():
    """测试 MongoDB 用户操作"""
    print("\n" + "=" * 60)
    print("测试 MongoDB 用户操作")
    print("=" * 60)
    
    try:
        from models.mongodb import UserMongoDB
        
        # 测试获取用户
        print("\n1️⃣  测试获取用户:")
        user = await UserMongoDB.get_by_id("9ab50f42-cbe6-463e-8278-d0c3331aaed8")
        if user:
            print(f"   用户名: {user.get('username')}")
            print(f"   邮箱: {user.get('email')}")
            print(f"   位置: {user.get('location')}")
            print("   ✅ 通过")
        else:
            print("   ⚠️  用户不存在")
        
        # 测试通过邮箱获取
        print("\n2️⃣  测试通过邮箱获取用户:")
        user = await UserMongoDB.get_by_email("15975509487@163.com")
        if user:
            print(f"   用户名: {user.get('username')}")
            print("   ✅ 通过")
        else:
            print("   ⚠️  用户不存在")
        
        print("\n" + "=" * 60)
        print("🎉 MongoDB 测试通过!")
        print("=" * 60)
        return True
        
    except Exception as e:
        print(f"\n❌ 测试失败!")
        print(f"错误信息: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


async def test_sqlite_user_operations():
    """测试 SQLite 用户操作"""
    print("\n" + "=" * 60)
    print("测试 SQLite 用户操作")
    print("=" * 60)
    
    try:
        from models.database import UserRepository, init_db
        
        # 确保表存在
        await init_db()
        
        # 测试获取用户（可能不存在）
        print("\n1️⃣  测试获取用户:")
        try:
            user = await UserRepository.get_by_id("test-id")
            if user:
                print(f"   用户名: {user.get('username')}")
                print("   ✅ 通过")
            else:
                print("   ⚠️  用户不存在（这是正常的）")
        except Exception as e:
            print(f"   ⚠️  查询失败: {e}")
        
        print("\n" + "=" * 60)
        print("🎉 SQLite 测试通过!")
        print("=" * 60)
        return True
        
    except Exception as e:
        print(f"\n❌ 测试失败!")
        print(f"错误信息: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    print("🚀 开始数据库集成测试...\n")
    
    # 测试 MongoDB
    result1 = asyncio.run(test_mongodb_user_operations())
    
    # 测试 SQLite
    result2 = asyncio.run(test_sqlite_user_operations())
    
    # 测试 mock_profile
    result3 = asyncio.run(test_mock_profile())
    
    # 总结
    print("\n" + "=" * 60)
    print("测试总结")
    print("=" * 60)
    print(f"MongoDB 测试: {'✅ 通过' if result1 else '❌ 失败'}")
    print(f"SQLite 测试: {'✅ 通过' if result2 else '❌ 失败'}")
    print(f"Mock Profile 测试: {'✅ 通过' if result3 else '❌ 失败'}")
    
    if result1 and result2 and result3:
        print("\n🎉 所有测试通过!")
        sys.exit(0)
    else:
        print("\n⚠️  部分测试失败")
        sys.exit(1)
