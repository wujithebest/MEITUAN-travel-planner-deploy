"""
意图处理流水线测试
验证闭环机制的完整功能

测试覆盖：
1. 强制响应契约 - 确保2秒内产生反馈
2. 防断链机制 - 3秒超时熔断
3. 响应组装校验 - 确保响应非空
4. 端到端追踪 - trace_id贯穿全流程
"""
import asyncio
import pytest
import time
import uuid
from datetime import datetime

from services.intent_pipeline import (
    IntentPipeline,
    IntentResult,
    IntentType,
    ResponseStatus,
    PipelineResponse,
    FALLBACK_TEMPLATES,
    process_intent,
    init_pipeline
)


class TestIntentPipeline:
    """意图处理流水线测试类"""
    
    @pytest.fixture
    def pipeline(self):
        """创建测试用流水线"""
        pipeline = IntentPipeline()
        
        # 注册测试处理器
        async def mock_handler(trace_id, user_input, intent_result, context):
            await asyncio.sleep(0.1)  # 模拟处理时间
            return PipelineResponse(
                trace_id=trace_id,
                status=ResponseStatus.SUCCESS,
                content=f"处理成功: {user_input}",
                intent_type=intent_result.intent_type,
                confidence=intent_result.confidence
            )
        
        async def slow_handler(trace_id, user_input, intent_result, context):
            await asyncio.sleep(5)  # 模拟超时
            return PipelineResponse(
                trace_id=trace_id,
                status=ResponseStatus.SUCCESS,
                content="不应该到达这里",
                intent_type=intent_result.intent_type
            )
        
        async def error_handler(trace_id, user_input, intent_result, context):
            raise Exception("模拟错误")
        
        async def empty_response_handler(trace_id, user_input, intent_result, context):
            return PipelineResponse(
                trace_id=trace_id,
                status=ResponseStatus.SUCCESS,
                content="",  # 空内容，触发兜底
                intent_type=intent_result.intent_type
            )
        
        pipeline.register_handler(IntentType.TRAVEL_PLANNING, mock_handler)
        pipeline.register_handler(IntentType.ROUTE_GENERATION, mock_handler)
        pipeline.register_handler(IntentType.POI_QUERY, mock_handler)
        pipeline.register_handler(IntentType.WEATHER_QUERY, mock_handler)
        pipeline.register_handler(IntentType.CHAT_MESSAGE, mock_handler)
        pipeline.register_handler(IntentType.UNKNOWN, slow_handler)
        
        return pipeline
    
    @pytest.fixture
    def sample_intent_result(self):
        """创建示例意图结果"""
        return IntentResult(
            intent_type=IntentType.TRAVEL_PLANNING,
            confidence=0.92,
            entities={
                "destination": "上海",
                "days": 3,
                "themes": ["美食", "历史"]
            },
            raw_input="规划上海3日游",
            trace_id=str(uuid.uuid4())
        )
    
    @pytest.mark.asyncio
    async def test_successful_processing(self, pipeline, sample_intent_result):
        """测试正常处理流程"""
        response = await pipeline.process(
            user_input="规划上海3日游",
            intent_result=sample_intent_result
        )
        
        # 验证响应
        assert response is not None
        assert response.status == ResponseStatus.SUCCESS
        assert response.content is not None
        assert len(response.content) > 0
        assert response.trace_id == sample_intent_result.trace_id
        assert response.processing_time_ms > 0
        
    @pytest.mark.asyncio
    async def test_response_within_2_seconds(self, pipeline, sample_intent_result):
        """测试2秒内产生响应"""
        start_time = time.time()
        
        response = await pipeline.process(
            user_input="规划上海3日游",
            intent_result=sample_intent_result
        )
        
        elapsed_time = time.time() - start_time
        
        # 验证在2秒内完成
        assert elapsed_time < 2.0, f"响应时间 {elapsed_time:.2f}s 超过2秒"
        assert response is not None
        assert len(response.content) > 0
        
    @pytest.mark.asyncio
    async def test_timeout_fallback(self):
        """测试超时熔断机制"""
        pipeline = IntentPipeline()
        
        # 注册一个会超时的处理器
        async def timeout_handler(trace_id, user_input, intent_result, context):
            await asyncio.sleep(10)  # 超过3秒超时
            return PipelineResponse(
                trace_id=trace_id,
                status=ResponseStatus.SUCCESS,
                content="不应该到达这里"
            )
        
        pipeline.register_handler(IntentType.TRAVEL_PLANNING, timeout_handler)
        
        intent_result = IntentResult(
            intent_type=IntentType.TRAVEL_PLANNING,
            confidence=0.9,
            entities={"destination": "北京", "days": 3},
            raw_input="规划北京3日游"
        )
        
        start_time = time.time()
        response = await pipeline.process(
            user_input="规划北京3日游",
            intent_result=intent_result
        )
        elapsed_time = time.time() - start_time
        
# 验证超时处理
        assert response.status == ResponseStatus.TIMEOUT
        assert elapsed_time < 4.0, "超时熔断未生效"
        assert len(response.content) > 0  # 有兜底内容
    
    @pytest.mark.asyncio
    async def test_empty_response_fallback(self):
        """测试空响应兜底"""
        pipeline = IntentPipeline()
        
        async def empty_handler(trace_id, user_input, intent_result, context):
            return PipelineResponse(
                trace_id=trace_id,
                status=ResponseStatus.SUCCESS,
                content="",  # 空内容
                intent_type=intent_result.intent_type
            )
        
        pipeline.register_handler(IntentType.TRAVEL_PLANNING, empty_handler)
        
        intent_result = IntentResult(
            intent_type=IntentType.TRAVEL_PLANNING,
            confidence=0.9,
            entities={"destination": "上海", "days": 3},
            raw_input="规划上海3日游"
        )
        
        response = await pipeline.process(
            user_input="规划上海3日游",
            intent_result=intent_result
        )
        
        # 验证兜底模板被使用
        assert len(response.content) > 0
        # 验证响应内容不为空（可能包含模板占位符或格式化后的内容）
        assert response.content is not None
        # 验证错误消息标记为使用兜底模板
        assert response.error_message == "使用兜底模板"
        
    @pytest.mark.asyncio
    async def test_low_confidence_handling(self, pipeline):
        """测试低置信度处理"""
        intent_result = IntentResult(
            intent_type=IntentType.UNKNOWN,
            confidence=0.3,  # 低于0.7阈值
            entities={},
            raw_input="随便说点什么"
        )
        
        response = await pipeline.process(
            user_input="随便说点什么",
            intent_result=intent_result
        )
        
        # 验证需要澄清
        assert response.status == ResponseStatus.NEEDS_CLARIFICATION
        assert len(response.content) > 0
        assert len(response.suggestions) > 0
        
    @pytest.mark.asyncio
    async def test_error_handling(self):
        """测试错误处理"""
        pipeline = IntentPipeline()
        
        async def error_handler(trace_id, user_input, intent_result, context):
            raise Exception("模拟错误")
        
        pipeline.register_handler(IntentType.TRAVEL_PLANNING, error_handler)
        
        intent_result = IntentResult(
            intent_type=IntentType.TRAVEL_PLANNING,
            confidence=0.9,
            entities={"destination": "上海"},
            raw_input="规划上海游"
        )
        
        response = await pipeline.process(
            user_input="规划上海游",
            intent_result=intent_result
        )
        
        # 验证错误兜底
        assert response.status == ResponseStatus.FAILED
        assert len(response.content) > 0
        assert response.error_message != ""
        
    @pytest.mark.asyncio
    async def test_trace_id_preserved(self, pipeline, sample_intent_result):
        """测试trace_id贯穿全流程"""
        response = await pipeline.process(
            user_input="规划上海3日游",
            intent_result=sample_intent_result
        )
        
        # 验证trace_id一致
        assert response.trace_id == sample_intent_result.trace_id
        
        # 验证追踪信息存在
        trace = pipeline.get_trace(sample_intent_result.trace_id)
        assert trace is not None
        assert trace["trace_id"] == sample_intent_result.trace_id
        assert trace["status"] == "completed"
        
    @pytest.mark.asyncio
    async def test_break_chain_logging(self):
        """测试断链日志记录"""
        pipeline = IntentPipeline()
        
        async def timeout_handler(trace_id, user_input, intent_result, context):
            await asyncio.sleep(10)
            return PipelineResponse(trace_id=trace_id, status=ResponseStatus.SUCCESS, content="")
        
        pipeline.register_handler(IntentType.TRAVEL_PLANNING, timeout_handler)
        
        intent_result = IntentResult(
            intent_type=IntentType.TRAVEL_PLANNING,
            confidence=0.9,
            entities={},
            raw_input="测试断链"
        )
        
        await pipeline.process(
            user_input="测试断链",
            intent_result=intent_result
        )
        
        # 验证断链日志
        logs = pipeline.get_break_chain_logs()
        assert len(logs) > 0
        assert logs[-1]["intent_type"] == "travel_planning"
        assert logs[-1]["break_point"] == "handler_execution"
        
    @pytest.mark.asyncio
    async def test_no_handler_fallback(self):
        """测试无处理器兜底"""
        pipeline = IntentPipeline()
        # 不注册任何处理器
        
        intent_result = IntentResult(
            intent_type=IntentType.TRAVEL_PLANNING,
            confidence=0.9,
            entities={},
            raw_input="测试无处理器"
        )
        
        response = await pipeline.process(
            user_input="测试无处理器",
            intent_result=intent_result
        )
        
        # 验证失败响应
        assert response.status == ResponseStatus.FAILED
        assert len(response.content) > 0
        assert "暂不支持" in response.content
        
    @pytest.mark.asyncio
    async def test_fallback_templates(self):
        """测试兜底模板"""
        # 验证所有意图类型都有兜底模板
        for intent_type in IntentType:
            assert intent_type in FALLBACK_TEMPLATES
            templates = FALLBACK_TEMPLATES[intent_type]
            assert "success" in templates
            assert "processing" in templates
            assert "failed" in templates
            
    @pytest.mark.asyncio
    async def test_concurrent_processing(self, pipeline):
        """测试并发处理"""
        tasks = []
        
        for i in range(5):
            intent_result = IntentResult(
                intent_type=IntentType.TRAVEL_PLANNING,
                confidence=0.9,
                entities={"destination": f"城市{i}", "days": i + 1},
                raw_input=f"规划城市{i}游"
            )
            tasks.append(pipeline.process(
                user_input=f"规划城市{i}游",
                intent_result=intent_result
            ))
        
        responses = await asyncio.gather(*tasks)
        
        # 验证所有请求都得到响应
        assert len(responses) == 5
        for response in responses:
            assert response is not None
            assert len(response.content) > 0
            assert response.trace_id is not None


class TestProcessIntentConvenience:
    """测试便捷函数"""
    
    @pytest.mark.asyncio
    async def test_process_intent_convenience(self):
        """测试process_intent便捷函数"""
        response = await process_intent(
            user_input="规划北京3日游",
            intent_type=IntentType.TRAVEL_PLANNING,
            confidence=0.92,
            entities={"destination": "北京", "days": 3}
        )
        
        assert response is not None
        assert response.trace_id is not None
        assert len(response.content) > 0


class TestResponseSerialization:
    """测试响应序列化"""
    
    def test_response_to_dict(self):
        """测试响应转字典"""
        response = PipelineResponse(
            trace_id="test-trace-id",
            status=ResponseStatus.SUCCESS,
            content="测试内容",
            intent_type=IntentType.TRAVEL_PLANNING,
            confidence=0.9,
            processing_time_ms=150.0
        )
        
        result = response.to_dict()
        
        assert result["trace_id"] == "test-trace-id"
        assert result["status"] == "success"
        assert result["content"] == "测试内容"
        assert result["intent_type"] == "travel_planning"
        assert result["confidence"] == 0.9
        assert result["processing_time_ms"] == 150.0
        assert "timestamp" in result


# ==================== 运行测试 ====================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
