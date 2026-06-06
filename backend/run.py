"""
上海旅游路线规划服务 - 启动脚本
系统仅支持上海市内旅游规划
支持 Docker 部署模式
"""

import os
import sys
import asyncio
import logging

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 修复 Windows 控制台 GBK 编码无法打印 emoji 的问题
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)


def check_env():
    """检查环境变量配置"""
    from config import get_settings
    settings = get_settings()
    
    warnings = []
    
    if not settings.gaode_key:
        warnings.append("⚠️  GAODE_KEY 未配置，高德地图API将无法使用")
    
    if not settings.llm_api_key:
        warnings.append("⚠️  LLM_API_KEY 未配置，LLM解析将无法使用")
    
    if not settings.weather_key:
        warnings.append("⚠️  WEATHER_KEY 未配置，上海天气查询将降级为静态提示")
    
    if warnings:
        print("\n" + "=" * 50)
        print("上海旅游路线规划服务 - 环境检查")
        print("=" * 50)
        for w in warnings:
            print(w)
        print("=" * 50)
        print("\n请复制 .env.example 为 .env 并填入你的 API Key")
        print("cp .env.example .env")
        print("\n是否继续启动? (y/n): ", end="")
        
        try:
            answer = input().strip().lower()
            if answer != 'y':
                print("启动已取消")
                sys.exit(0)
        except EOFError:
            print("\n继续启动...")


async def main():
    """主函数"""
    import uvicorn
    from config import get_settings, SHANGHAI_CENTER
    
    settings = get_settings()
    
    # 检测 Docker 模式
    is_docker = os.getenv("APP_PORT") == "8000" or os.path.exists("/.dockerenv")
    
    print("\n" + "=" * 60)
    if is_docker:
        print("🐳 上海旅游路线规划服务 [Docker 模式]")
    else:
        print("🏙️  上海旅游路线规划服务")
    print("=" * 60)
    print(f"📍 服务区域: 上海市（含崇明、嘉定、青浦、松江、奉贤、金山、浦东、闵行、宝山等）")
    print(f"🗺️  地图中心: {SHANGHAI_CENTER['name']} ({SHANGHAI_CENTER['lng']}, {SHANGHAI_CENTER['lat']})")
    print(f"🔌 服务端口: {settings.app_port}")
    print(f"🤖 LLM模型: {settings.llm_model}")
    print(f"🔐 SECRET_KEY: {'已配置' if os.getenv('SECRET_KEY') else '未配置'}")
    if is_docker:
        print(f"🐳 Docker 模式: 已启用")
    print("=" * 60)
    print(f"\n📖 API文档: http://localhost:{settings.app_port}/docs")
    print(f"📋 ReDoc文档: http://localhost:{settings.app_port}/redoc")
    print("\n按 Ctrl+C 停止服务\n")
    
    # 启动服务
    config = uvicorn.Config(
        "main:app",
        host="0.0.0.0",
        port=settings.app_port,
        log_level="info",
        reload=not is_docker  # Docker 模式下禁用自动重载
    )
    server = uvicorn.Server(config)
    await server.serve()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n服务已停止")
    except Exception as e:
        logger.exception(f"启动失败: {str(e)}")
        sys.exit(1)
