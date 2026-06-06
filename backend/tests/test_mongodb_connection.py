"""
MongoDB 连接测试脚本
用于测试 MongoDB 数据库连接是否正常
"""

import asyncio
import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from motor.motor_asyncio import AsyncIOMotorClient
from config import get_settings


async def test_mongodb_connection():
    """测试 MongoDB 连接"""
    settings = get_settings()
    
    print("=" * 60)
    print("MongoDB 连接测试")
    print("=" * 60)
    
    # 获取 MongoDB 配置
    mongodb_url = settings.mongodb_url if hasattr(settings, 'mongodb_url') else "mongodb://localhost:27017"
    database_name = settings.mongodb_database if hasattr(settings, 'mongodb_database') else "travel_planner"
    
    print(f"\n📋 配置信息:")
    print(f"   MongoDB URL: {mongodb_url}")
    print(f"   数据库名称: {database_name}")
    
    # 测试连接
    print(f"\n🔄 正在连接 MongoDB...")
    
    try:
        # 创建客户端
        client = AsyncIOMotorClient(mongodb_url, serverSelectionTimeoutMS=5000)
        
        # 测试连接 - 发送 ping 命令
        await client.admin.command('ping')
        print("✅ MongoDB 连接成功!")
        
        # 获取数据库
        db = client[database_name]
        print(f"✅ 数据库 '{database_name}' 访问成功!")
        
        # 列出所有集合
        print(f"\n📦 数据库中的集合:")
        collections = await db.list_collection_names()
        if collections:
            for collection in collections:
                print(f"   - {collection}")
        else:
            print("   (数据库为空，没有集合)")
        
        # 测试 users 集合
        print(f"\n👤 测试 users 集合:")
        users_collection = db.users
        
        # 统计文档数量
        count = await users_collection.count_documents({})
        print(f"   users 集合中的文档数量: {count}")
        
        # 如果有用户，显示前3个
        if count > 0:
            print(f"\n   前3个用户文档:")
            cursor = users_collection.find().limit(3)
            async for doc in cursor:
                print(f"   - ID: {doc.get('_id')}, 用户名: {doc.get('username', 'N/A')}, 邮箱: {doc.get('email', 'N/A')}")
        
        # 测试写入权限
        print(f"\n✍️  测试写入权限:")
        test_doc = {
            "test": True,
            "message": "MongoDB 连接测试",
            "timestamp": str(asyncio.get_event_loop().time())
        }
        
        result = await db.test_collection.insert_one(test_doc)
        print(f"✅ 写入成功! 文档ID: {result.inserted_id}")
        
        # 清理测试文档
        await db.test_collection.delete_one({"_id": result.inserted_id})
        print("✅ 测试文档已清理")
        
        # 关闭连接
        client.close()
        print("\n" + "=" * 60)
        print("🎉 所有测试通过! MongoDB 连接正常。")
        print("=" * 60)
        return True
        
    except Exception as e:
        print(f"\n❌ MongoDB 连接失败!")
        print(f"\n错误信息: {str(e)}")
        print(f"\n💡 可能的解决方案:")
        print("   1. 检查 MongoDB 服务是否已启动")
        print("   2. 检查 MongoDB URL 是否正确")
        print("   3. 检查网络连接")
        print("   4. 检查防火墙设置")
        print("=" * 60)
        return False


async def test_mongodb_with_models():
    """使用项目中的 MongoDB 模型进行测试"""
    print("\n" + "=" * 60)
    print("使用项目模型测试 MongoDB")
    print("=" * 60)
    
    try:
        from models.mongodb import init_mongodb, users_collection, client
        
        print("\n🔄 初始化 MongoDB...")
        await init_mongodb()
        
        print("\n📊 测试 users 集合操作:")
        
        # 测试查询
        count = await users_collection.count_documents({})
        print(f"   用户数量: {count}")
        
        # 测试索引
        indexes = await users_collection.index_information()
        print(f"\n📑 索引信息:")
        for index_name, index_info in indexes.items():
            print(f"   - {index_name}: {index_info}")
        
        print("\n✅ 模型测试通过!")
        return True
        
    except Exception as e:
        print(f"\n❌ 模型测试失败!")
        print(f"错误信息: {str(e)}")
        return False


if __name__ == "__main__":
    # 运行基础连接测试
    result1 = asyncio.run(test_mongodb_connection())
    
    # 运行模型测试
    result2 = asyncio.run(test_mongodb_with_models())
    
    # 总结
    print("\n" + "=" * 60)
    print("测试总结")
    print("=" * 60)
    print(f"基础连接测试: {'✅ 通过' if result1 else '❌ 失败'}")
    print(f"模型测试: {'✅ 通过' if result2 else '❌ 失败'}")
    
    if result1 and result2:
        print("\n🎉 所有测试通过!")
        sys.exit(0)
    else:
        print("\n⚠️  部分测试失败，请检查配置。")
        sys.exit(1)
