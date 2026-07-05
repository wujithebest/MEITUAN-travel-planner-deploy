import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from routers import meituan_chat


def _route_context():
    return meituan_chat.RouteContextSchema(
        route_id="route-1",
        point_names=["清华大学(东南门)", "京张铁路遗址公园一期a段"],
        points=[
            {
                "poi_id": "home",
                "name": "清华大学(东南门)",
                "kind": "start",
                "location": {"lng": 116.3328, "lat": 39.996548},
                "day": 1,
                "display_slot": "morning",
            },
            {
                "poi_id": "park",
                "name": "京张铁路遗址公园一期a段",
                "kind": "anchor_internal",
                "location": {"lng": 116.338062, "lat": 39.998984},
                "day": 1,
                "display_slot": "afternoon",
            },
        ],
    )


class ConversationRouteContinuationTests(unittest.IsolatedAsyncioTestCase):
    def test_evening_category_is_current_route_append(self):
        edit = meituan_chat._classify_chat_edit("晚上去电影院", _route_context())

        self.assertEqual(edit["action"], "add")
        self.assertEqual(edit["new_name"], "电影院")
        self.assertEqual(edit["display_slot"], "evening")
        self.assertTrue(edit["continuation"])

    def test_continuation_endpoint_ignores_home_start(self):
        endpoint = meituan_chat._continuation_endpoint(_route_context())

        self.assertEqual(endpoint["name"], "京张铁路遗址公园一期a段")

    async def test_category_lookup_uses_previous_endpoint_and_rejects_non_cinema(self):
        around_search = AsyncMock(return_value=[
            {
                "id": "archive",
                "name": "中国电影资料馆",
                "typecode": "140000",
                "category": "科教文化服务",
                "location": {"lng": 116.36, "lat": 39.95},
            },
            {
                "id": "cinema",
                "name": "附近影城",
                "typecode": "080201",
                "category": "电影院",
                "location": {"lng": 116.34, "lat": 40.00},
            },
        ])
        text_search = AsyncMock(side_effect=AssertionError("附近存在合法影院时不应降级到全城文本检索"))

        with patch.object(meituan_chat, "gaode_around_search", around_search), patch.object(
            meituan_chat, "gaode_text_search", text_search
        ):
            poi = await meituan_chat._resolve_poi_for_chat_edit(
                "电影院",
                city="北京市",
                center={"lng": 116.338062, "lat": 39.998984},
            )

        self.assertEqual(poi["name"], "附近影城")
        call = around_search.await_args.kwargs
        self.assertEqual(call["location"], "116.338062,39.998984")
        self.assertEqual(call["sortrule"], "distance")
        self.assertIn("080200", call["types"])

    async def test_replan_appends_after_previous_endpoint_instead_of_home(self):
        context = _route_context()
        cinema = {
            "poi_id": "cinema",
            "name": "附近影城",
            "typecode": "080201",
            "location": {"lng": 116.34, "lat": 40.00},
            "kind": "anchor_internal",
        }
        captured = {}

        async def fake_apply(points, operations, route_id=None):
            captured["points"] = points
            captured["operations"] = operations
            added = {**operations[0]["poi"], "route_order": 3, "display_order": 3}
            return {
                "route_id": route_id,
                "route": {"points": [*points, added], "segments": []},
            }

        with patch.object(
            meituan_chat, "_resolve_poi_for_chat_edit", AsyncMock(return_value=cinema)
        ) as resolve, patch.object(
            meituan_chat, "apply_pipeline_replan", fake_apply
        ), patch.object(
            meituan_chat, "emit_status", AsyncMock()
        ), patch.object(
            meituan_chat, "push_output", AsyncMock()
        ), patch.object(
            meituan_chat, "emit_done", AsyncMock()
        ):
            handled = await meituan_chat._try_chat_edit_replan(
                "晚上去电影院",
                context,
                SimpleNamespace(permanent_city=["北京市"]),
            )

        self.assertTrue(handled)
        self.assertEqual(resolve.await_args.kwargs["center"], {"lng": 116.338062, "lat": 39.998984})
        operation = captured["operations"][0]
        self.assertEqual(operation["after_poi_name"], "京张铁路遗址公园一期a段")
        self.assertEqual(operation["poi"]["display_slot"], "evening")
        self.assertEqual(captured["points"][0]["name"], "清华大学(东南门)")
        self.assertEqual(captured["points"][1]["name"], "京张铁路遗址公园一期a段")

    async def test_failed_append_preserves_current_route_without_full_replan(self):
        done = AsyncMock()
        with patch.object(
            meituan_chat, "_resolve_poi_for_chat_edit", AsyncMock(return_value=None)
        ), patch.object(
            meituan_chat, "apply_pipeline_replan", AsyncMock()
        ) as apply, patch.object(
            meituan_chat, "emit_status", AsyncMock()
        ), patch.object(
            meituan_chat, "push_output", AsyncMock()
        ), patch.object(
            meituan_chat, "emit_done", done
        ):
            handled = await meituan_chat._try_chat_edit_replan(
                "晚上去电影院",
                _route_context(),
                SimpleNamespace(permanent_city=["北京市"]),
            )

        self.assertTrue(handled)
        apply.assert_not_awaited()
        route_data = done.await_args.kwargs["route_data"]
        self.assertEqual(
            [point["name"] for point in route_data["points"]],
            ["清华大学(东南门)", "京张铁路遗址公园一期a段"],
        )


if __name__ == "__main__":
    unittest.main()
