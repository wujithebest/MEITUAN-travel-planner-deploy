"""
数据模型包
重新导出所有模型以保持向后兼容
"""

from .base import (
    TransportMode, OperationType, Permission,
    LocationInput, POI, WeatherInfo,
    ApiResponse, ErrorResponse
)
from .route import (
    RoutePoint, DailyRoute, RouteResponse,
    RouteOptimizeRequest, DisambiguateRequest
)
from .collab import (
    RoomMember, Operation, CollaborationRoom,
    WSMessage, CreateRoomRequest, JoinRoomRequest, OperationRequest
)
from .diary import (
    DiaryEntry, Achievement, DiaryStats, Diary,
    DiaryEntryRequest, DiaryExportRequest
)
from .llm import (
    ParsedLocation, LLMParseResult
)
from .mongodb import UserMongoDB, init_mongodb, close_mongodb
from .user import (
    UserProfile, UserProfileUpdate, UserLocation, UserPreferences,
    UsernameCheckResponse
)

__all__ = [
    # 枚举
    'TransportMode', 'OperationType', 'Permission',
    # 基础
    'LocationInput', 'POI', 'WeatherInfo',
    'ApiResponse', 'ErrorResponse',
    # 路线
    'RoutePoint', 'DailyRoute', 'RouteResponse',
    'RouteOptimizeRequest', 'DisambiguateRequest',
    # 协作
    'RoomMember', 'Operation', 'CollaborationRoom',
    'WSMessage', 'CreateRoomRequest', 'JoinRoomRequest', 'OperationRequest',
    # 日记
    'DiaryEntry', 'Achievement', 'DiaryStats', 'Diary',
    'DiaryEntryRequest', 'DiaryExportRequest',
    # LLM
    'ParsedLocation', 'LLMParseResult',
    # MongoDB
    'UserMongoDB', 'init_mongodb', 'close_mongodb',
    # 用户资料
    'UserProfile', 'UserProfileUpdate', 'UserLocation', 'UserPreferences',
    'UsernameCheckResponse',
]
