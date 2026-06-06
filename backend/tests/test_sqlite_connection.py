"""
SQLite 连接测试脚本
用于测试 SQLite 数据库连接和表是否存在
"""

import asyncio
import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import inspect, text
from models.database import engine, init_db, UserDB, AsyncSessionLocal, select


async def test_sqlite_connection():
    """测试 SQLite 连接和表结构"""
    print("=" * 60)
    print("SQLite 连接测试")
    print("=" * 60)
    
    # 获取数据库路径
    database_url = str(engine.url)
    print(f"\n📋 数据库路径: {database_url}")
    
    # 检查数据库文件是否存在
    db_path = database_url.replace("sqlite+aiosqlite:///", "")
    print(f"📁 数据库文件: {db_path}")
    print(f"   文件存在: {os.path.exists(db_path)}")
    
    if os.path.exists(db_path):
        print(f"   文件大小: {os.path.getsize(db_path)} bytes")
    
    # 测试连接
    print(f"\n🔄 正在连接 SQLite...")
    
    try:
        async with engine.begin() as conn:
            # 检查连接
            result = await conn.execute(text("SELECT 1"))
            print("✅ SQLite 连接成功!")
            
            # 列出所有表
            print(f"\n📦 数据库中的表:")
            result = await conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table'")
            )
            tables = result.fetchall()
            
            if tables:
                for table in tables:
                    print(f"   - {table[0]}")
            else:
                print("   (数据库为空，没有表)")
        
        # 检查 users 表
        print(f"\n👤 检查 users 表:")
        
        # 检查表是否存在
        async with engine.begin() as conn:
            result = await conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
            )
            table_exists = result.fetchone() is not None
            
            if table_exists:
                print("   ✅ users 表存在")
                
                # 获取表结构
                print(f"\n📑 表结构:")
                async with AsyncSessionLocal() as session:
                    result = await session.execute(
                        text("PRAGMA table_info(users)")
                    )
                    columns = result.fetchall()
                    for col in columns:
                        print(f"   - {col[1]} ({col[2]})")
                
                # 统计记录数
                async with AsyncSessionLocal() as session:
                    result = await session.execute(text("SELECT COUNT(*) FROM users"))
                    count = result.scalar()
                    print(f"\n   用户数量: {count}")
                    
                    if count > 0:
                        result = await session.execute(
                            text("SELECT id, username, email FROM users LIMIT 3")
                        )
                        users = result.fetchall()
                        print(f"\n   前3个用户:")
                        for user in users:
                            print(f"   - ID: {user[0]}, 用户名: {user[1]}, 邮箱: {user[2]}")
            else:
                print("   ❌ users 表不存在!")
                print(f"\n💡 解决方案:")
                print("   正在尝试创建表...")
                
                await init_db()
                
                # 再次检查
                async with engine.begin() as conn:
                    result = await conn.execute(
                        text("SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
                    )
                    if result.fetchone():
                        print("   ✅ users 表创建成功!")
                    else:
                        print("   ❌ 创建失败!")
        
        print("\n" + "=" * 60)
        print("🎉 SQLite 测试完成!")
        print("=" * 60)
        return True
        
    except Exception as e:
        print(f"\n❌ SQLite 连接失败!")
        print(f"\n错误信息: {str(e)}")
        print(f"\n💡 可能的解决方案:")
        print("   1. 检查数据库文件路径是否正确")
        print("   2. 检查文件权限")
        print("   3. 删除旧的数据库文件重新启动")
        print("=" * 60)
        return False


if __name__ == "__main__":
    result = asyncio.run(test_sqlite_connection())
    sys.exit(0 if result else 1)
