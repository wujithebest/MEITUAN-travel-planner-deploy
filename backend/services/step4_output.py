from __future__ import annotations
import uuid
from typing import Any
from .data_schema import CompletePlan, MicroPOI, ParsedIntent, RouteSegment
from .day_slots import WEATHER_LOW_SCORE_THRESHOLD
from .step2_macro import OUTDOOR_TYPECODES
from .utils import PipelineLogger, emit_done, emit_status, push_output

# 路线缓存：按 route_id 存储 points/segments，供重新计算端点使用
_route_cache: dict[str, dict[str, Any]] = {}


def _duration_desc(parsed_intent: ParsedIntent) -> str:
    weekday = ""
    if parsed_intent.start_time:
        names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
        weekday = names[parsed_intent.start_time.weekday()]
    mapping = {
        "a quarter day": "小半天",
        "a half day": f"{weekday}半天" if weekday else "半天",
        "a full day": f"{weekday}一天" if weekday else "一天",
        "a day and a half": "一天半",
        "two days": "两天一夜",
        "two and a half days": "两天半",
        "three days": "三天两夜",
    }
    return mapping.get(parsed_intent.duration, "一天")


def _is_quarter_day(parsed_intent: ParsedIntent) -> bool:
    return parsed_intent.duration == "a quarter day" or float(getattr(parsed_intent, "time_budget", 0) or 0) < 0.5


def _is_half_day(parsed_intent: ParsedIntent) -> bool:
    tb = float(getattr(parsed_intent, "time_budget", 0) or 0)
    return parsed_intent.duration == "a half day" or tb == 0.5


def _is_compact_duration(parsed_intent: ParsedIntent) -> str:
    """返回 '' | 'short' | 'half_day' 表示 compact 展示粒度"""
    if _is_quarter_day(parsed_intent):
        return "short"
    if _is_half_day(parsed_intent):
        return "half_day"
    return ""


def _short_trip_label() -> str:
    return "短途路线"


def _segment_lookup(route_segments: list[RouteSegment]) -> dict[tuple[str, str], RouteSegment]:
    return {(segment.from_poi, segment.to_poi): segment for segment in route_segments}


def _route_line(names: list[str], segments: dict[tuple[str, str], RouteSegment]) -> str:
    if len(names) <= 1:
        return names[0] if names else ""
    parts = [names[0]]
    for start, end in zip(names, names[1:]):
        segment = segments.get((start, end))
        if segment:
            duration = max(1, int(round(segment.duration_min)))
            duration_text = f"约{duration}min" if segment.transport == "步行" and duration <= 2 else f"{duration}min"
            parts.extend([f"{segment.transport}({duration_text})", end])
        else:
            parts.extend(["路线缺失", end])
    return " - ".join(parts)


def _order_slot_names(previous_name: str, anchor_name: str, children, segments: dict[tuple[str, str], RouteSegment], all_point_names: list[str]) -> list[str]:
    # v5.2: children可以是list[str]或list[MicroPOI]
    child_names = [c if isinstance(c, str) else c.name for c in children]
    # 基于路线段顺序推断名称顺序
    ordered: list[str] = []
    seen: set[str] = set()
    for seg_key in segments:
        from_name, to_name = seg_key
        if from_name not in seen and from_name in all_point_names:
            ordered.append(from_name)
            seen.add(from_name)
        if to_name not in seen and to_name in all_point_names:
            ordered.append(to_name)
            seen.add(to_name)
    if not ordered:
        ordered = [anchor_name] + child_names
    return ordered


def _activity_label(
    index: int,
    capacity: str,
    total_anchors: int,
    evening_requested: bool,
    start_hour: float | None = None,
) -> str:
    # v6: 晚间开始的短行程统一使用晚间标签
    if start_hour is not None and start_hour >= 20:
        h = int(start_hour)
        end_h = min(h + 2, 24)
        labels = [f"晚上（{h:02d}:00-{end_h:02d}:00）"]
        while len(labels) <= index:
            labels.append("夜间继续")
        return labels[min(index, len(labels) - 1)]
    if index == 0 and start_hour is not None:
        if 17 <= start_hour < 20:
            h = int(start_hour)
            end_h = min(h + 2, 22)
            return f"傍晚（{h:02d}:00-{end_h:02d}:00）"
        if 13 <= start_hour < 17:
            h = max(14, int(start_hour))
            return f"下午（{h:02d}:00-18:00）"
        if start_hour >= 20:
            return "晚上（20:00-22:00）"
    if capacity == "full_day":
        return "全天（9:00-18:00）"
    if evening_requested:
        if total_anchors <= 1:
            labels = ["白天（9:00-18:00）", "晚上（19:00-21:30）"]
        elif total_anchors == 2:
            labels = ["上午（9:00-12:00）", "下午（14:00-18:00）"]
        else:
            labels = ["上午（9:00-12:00）", "下午（14:00-18:00）", "晚上（20:00-22:00）"]
        return labels[min(index, len(labels) - 1)]
    if total_anchors <= 2:
        labels = ["上午（9:00-12:00）", "下午（14:00-18:00）"]
    elif total_anchors >= 4:
        labels = ["上午前段（9:00-10:30）", "上午后段（10:30-12:00）", "下午前段（14:00-16:00）", "下午后段（16:00-18:00）"]
    else:
        labels = ["上午（9:00-12:00）", "下午前段（14:00-16:00）", "下午后段（16:00-18:00）"]
    return labels[min(index, len(labels) - 1)]


def _half_day_label(start_hour: float | None = None) -> str:
    return "半天"


def _meal_label(meal: str, start_hour: float | None = None) -> str:
    if meal == "lunch":
        return "中午（12:00-14:00）"
    if meal != "dinner":
        return "餐饮"
    # v6: 动态晚餐窗口，和 _activity_label 的晚间语义对齐
    if start_hour is None or start_hour < 20:
        return "晚餐（18:00-20:00）"
    h = int(start_hour)
    end_h = min(h + 2, 24)
    if end_h == 24:
        end_label = "24:00"
    else:
        end_label = f"{end_h:02d}:00"
    return f"晚餐（{h:02d}:00-{end_label}）"


def _distance_text(distance: float | int | None) -> str:
    if distance is None:
        return ""
    value = max(float(distance), 0.01)
    return f"（距上一站步行约{value:.2f}km）"


def _meal_meta(item: MicroPOI) -> str:
    parts = []
    if item.gaode_rating is not None:
        parts.append(f"评分{item.gaode_rating:.1f}")
    if item.avg_cost is not None:
        parts.append(f"人均约{int(round(item.avg_cost))}元")
    if (item.typecode or "").startswith("05"):
        parts.append("正餐 POI")
    return f"（{'，'.join(parts)}）" if parts else ""


def _lunch_after_index(anchor_count: int) -> int:
    return 1 if anchor_count >= 4 else 0


def _origin_label(parsed_intent: ParsedIntent) -> str:
    location = parsed_intent.original_location or {}
    return (
        parsed_intent.original_location_label
        or location.get("label")
        or location.get("name")
        or "出发点"
    )


def _append_meal_line(
    lines: list[str],
    meal: str,
    previous: str,
    meal_by_name: dict[str, MicroPOI],
    meal_slots: list[dict],
    segments: dict[tuple[str, str], RouteSegment],
    start_hour: float | None = None,
) -> str:
    if not meal_slots:
        return previous
    slot = meal_slots[0]
    meal_name = slot.get("poi_name")
    if meal_name and meal_name in meal_by_name:
        meal_item = meal_by_name[meal_name]
        lines.append(
            f"{_meal_label(meal, start_hour)}：餐饮推荐 - {meal_name}"
            f"{_distance_text(slot.get('meal_walk_distance_km'))}{_meal_meta(meal_item)}"
        )
        if previous != meal_name:
            route_line = _route_line([previous, meal_name], segments)
            if "路线缺失" in route_line:
                walk_km = slot.get("meal_walk_distance_km")
                if walk_km:
                    lines.append(f"  步行约{max(1, int(round(walk_km * 1000)))}米到达{meal_name}")
                else:
                    lines.append(f"  {route_line}")
            else:
                lines.append(f"  {route_line}")
        return meal_name
    lines.append(f"{_meal_label(meal, start_hour)}：未检索到符合条件的真实餐饮 POI")
    return previous


def _day_detail(day, parsed_intent: ParsedIntent, micro_pois: list[MicroPOI], route_segments: list[RouteSegment], anchor_hints: dict[str, str] | None = None, waypoint_annotations: dict[str, dict[str, Any]] | None = None) -> str:
    segments = _segment_lookup(route_segments)
    lines = [f"【Day{day.day_index}】"]
    previous = _origin_label(parsed_intent)
    meal_by_name = {item.name: item for item in micro_pois if item.is_meal}
    lunch_slots = [slot for slot in day.meal_slots if slot.get("meal") == "lunch"]
    dinner_slots = [slot for slot in day.meal_slots if slot.get("meal") == "dinner"]
    dinner_rendered = False

    # 收集当天的途经点（被waypoint优化合并的POI）
    day_passing_pois: list[str] = []
    day_same_building_pois: list[str] = []
    if waypoint_annotations:
        for name, ann in waypoint_annotations.items():
            if ann.get("day") != day.day_index:
                continue
            if ann.get("same_building"):
                day_same_building_pois.append(name)
            elif not ann.get("is_waypoint", True):
                walk = ann.get("walk_from_route_min", 0)
                day_passing_pois.append(f"途经{name}（步行{walk}分钟可达）")
    evening_start_index = (
        len(day.anchors) - 1
        if parsed_intent.evening_requested and len(day.anchors) >= 3
        else 2 if parsed_intent.evening_requested else None
    )
    start_hour = None
    if parsed_intent.start_time and day.day_index == 1:
        start_hour = parsed_intent.start_time.hour + parsed_intent.start_time.minute / 60
    if getattr(parsed_intent, "dinner_first", False):
        previous = _append_meal_line(lines, "dinner", previous, meal_by_name, dinner_slots, segments, start_hour)
        dinner_rendered = True

    # 收集所有有效段名
    all_names: set[str] = set()
    for seg in route_segments:
        if seg.day_index == day.day_index:
            all_names.add(seg.from_poi)
            all_names.add(seg.to_poi)

    for index, anchor in enumerate(day.anchors):
        # v5.2 r5: 多锚点同天时，第一次迭代已渲染完所有锚点，跳过后续迭代
        if len(day.anchors) >= 2 and index > 0:
            break
        if evening_start_index is not None and index == evening_start_index and not dinner_rendered:
            previous = _append_meal_line(lines, "dinner", previous, meal_by_name, dinner_slots, segments, start_hour)
            dinner_rendered = True
        # 餐饮名称集合
        meal_names_set = set(meal_by_name.keys())
        # v5.2: children来自route_segments中kind=anchor_internal的POI，不再从micro_pois取
        children_names = []
        for seg in route_segments:
            if seg.day_index == day.day_index and seg.to_poi not in meal_names_set and seg.to_poi != anchor.name and seg.to_poi != previous and seg.to_poi in all_names:
                children_names.append(seg.to_poi)
        title = f"{anchor.name}周边游览" if children_names else anchor.name
        ordered_slot_names = _order_slot_names(previous, anchor.name, children_names, segments, list(all_names))
        # v5: 修剪为从 previous 开始，避免前序锚点的POI串入当前段
        if previous in ordered_slot_names:
            prev_idx = ordered_slot_names.index(previous)
            ordered_slot_names = ordered_slot_names[prev_idx:]
        else:
            # previous 不在路段中时，只显示当前锚点相关POI，不从全天生凑
            ordered_slot_names = [anchor.name] + list(children_names)
        names = ordered_slot_names or [previous, anchor.name]
        names = [n for n in names if n not in meal_names_set or n == previous]
        # 过滤纯道路名（"中山南一路"等，非实际POI）
        known_poi_names = {anchor.name, previous} | set(children_names)
        _road_suffixes = ("路", "街", "大道", "巷", "弄", "公路")
        names = [n for n in names if n in known_poi_names or not n.endswith(_road_suffixes)]
        if not names:
            names = [previous, anchor.name]
        time_budget = anchor.final_time_budget or anchor.final_capacity or "half_day"

        # v5.2 r5: 多锚点同天时统一按lunch切分上午/下午，不再区分full_day/half_day
        if len(day.anchors) >= 2 and len(names) >= 2:
            # 构建 route_segments 的完整有序列表（含餐饮POI）
            lunch_name = lunch_slots[0].get("poi_name") if lunch_slots else None
            dinner_name = dinner_slots[0].get("poi_name") if dinner_slots else None

            ordered_with_meals: list[str] = []
            seen_in_order: set[str] = set()
            for seg in route_segments:
                if seg.day_index != day.day_index:
                    continue
                if seg.from_poi not in seen_in_order and (seg.from_poi in all_names or seg.from_poi == lunch_name):
                    ordered_with_meals.append(seg.from_poi)
                    seen_in_order.add(seg.from_poi)
                if seg.to_poi not in seen_in_order and (seg.to_poi in all_names or seg.to_poi == lunch_name):
                    ordered_with_meals.append(seg.to_poi)
                    seen_in_order.add(seg.to_poi)

            if _is_quarter_day(parsed_intent) or _is_half_day(parsed_intent):
                short_pois = [n for n in ordered_with_meals if n not in meal_names_set] or names
                first_anchor = day.anchors[0].name
                is_quarter = _is_quarter_day(parsed_intent)
                short_title = f"{first_anchor}周边随走" if is_quarter else f"{first_anchor}周边游览"
                label = _short_trip_label() if is_quarter else _half_day_label(start_hour)
                lines.append(f"{label}：{short_title}")
                _short_route = [previous] + short_pois if previous and previous not in short_pois else short_pois
                lines.append(f"  {_route_line(_short_route, segments)}")
                for reason_anchor in day.anchors:
                    if reason_anchor.recommend_reason:
                        lines.append(f"  推荐理由：{reason_anchor.recommend_reason}")
                if anchor_hints:
                    for reason_anchor in day.anchors:
                        hint = anchor_hints.get(reason_anchor.name)
                        if hint:
                            lines.append(f"  {hint}")
                previous = short_pois[-1] if short_pois else previous
                if lunch_slots and not is_quarter:
                    previous = _append_meal_line(lines, "lunch", previous, meal_by_name, lunch_slots, segments, start_hour)
                continue

            # 按 lunch 切分上午/下午
            if lunch_name and lunch_name in ordered_with_meals:
                lunch_idx = ordered_with_meals.index(lunch_name)
                morning_pois = [n for n in ordered_with_meals[:lunch_idx] if n not in meal_names_set]
                _raw_afternoon = ordered_with_meals[lunch_idx + 1:]
                if dinner_name and dinner_name in _raw_afternoon and _raw_afternoon and _raw_afternoon[-1] == dinner_name:
                    afternoon_pois = [n for n in _raw_afternoon[:-1] if n not in meal_names_set]
                else:
                    afternoon_pois = [n for n in _raw_afternoon if n not in meal_names_set]
            else:
                # 无午餐名时，按锚点数量均分
                non_meal_ordered = [n for n in ordered_with_meals if n not in meal_names_set]
                mid = len(non_meal_ordered) // 2
                morning_pois = non_meal_ordered[:mid]
                afternoon_pois = non_meal_ordered[mid:]

            first_anchor = day.anchors[0].name
            second_anchor = day.anchors[1].name if len(day.anchors) > 1 else first_anchor

            morning_title = f"{first_anchor}周边游览" if morning_pois else first_anchor
            afternoon_title = f"{second_anchor}周边游览" if len(day.anchors) > 1 and afternoon_pois else second_anchor

            lines.append(f"上午（9:00-12:00）：{morning_title}")
            _morning_route = [previous] + morning_pois if previous and previous not in morning_pois else morning_pois
            lines.append(f"  {_route_line(_morning_route, segments)}")
            if day.anchors[0].recommend_reason:
                lines.append(f"  推荐理由：{day.anchors[0].recommend_reason}")
            if anchor_hints:
                hint = anchor_hints.get(first_anchor)
                if hint:
                    lines.append(f"  {hint}")

            if lunch_slots and morning_pois:
                previous = _append_meal_line(lines, "lunch", morning_pois[-1], meal_by_name, lunch_slots, segments, start_hour)
            elif lunch_slots:
                previous = _append_meal_line(lines, "lunch", previous, meal_by_name, lunch_slots, segments, start_hour)
            else:
                previous = morning_pois[-1] if morning_pois else previous

            lines.append(f"下午（14:00-18:00）：{afternoon_title}")
            _afternoon_route = [previous] + afternoon_pois if previous and previous not in afternoon_pois else afternoon_pois
            lines.append(f"  {_route_line(_afternoon_route, segments)}")
            if len(day.anchors) > 1 and day.anchors[1].recommend_reason:
                lines.append(f"  推荐理由：{day.anchors[1].recommend_reason}")
            if anchor_hints and len(day.anchors) > 1:
                hint = anchor_hints.get(second_anchor)
                if hint:
                    lines.append(f"  {hint}")
            previous = afternoon_pois[-1] if afternoon_pois else previous

            # 如果还有第3个及以上锚点，追加渲染
            for extra_idx in range(2, len(day.anchors)):
                extra_anchor = day.anchors[extra_idx]
                extra_label = _activity_label(extra_idx, extra_anchor.final_time_budget or extra_anchor.final_capacity or "half_day", len(day.anchors), parsed_intent.evening_requested, start_hour)
                lines.append(f"{extra_label}：{extra_anchor.name}")
                previous = extra_anchor.name

        elif time_budget == "full_day" and len(names) >= 2:
            # 拆分为上午/下午两段，以午饭位置为分界
            lunch_name = lunch_slots[0].get("poi_name") if lunch_slots else None
            dinner_name = dinner_slots[0].get("poi_name") if dinner_slots else None

            # v5.2修复: 使用route_segments构建包含餐饮POI的完整有序列表
            # 解决餐饮名被过滤后找不到lunch_name导致中点切分不准的问题
            ordered_with_meals: list[str] = []
            seen_in_order: set[str] = set()
            for seg in route_segments:
                if seg.day_index != day.day_index:
                    continue
                if seg.from_poi not in seen_in_order and (seg.from_poi in all_names or seg.from_poi == lunch_name):
                    ordered_with_meals.append(seg.from_poi)
                    seen_in_order.add(seg.from_poi)
                if seg.to_poi not in seen_in_order and (seg.to_poi in all_names or seg.to_poi == lunch_name):
                    ordered_with_meals.append(seg.to_poi)
                    seen_in_order.add(seg.to_poi)

            if lunch_name and lunch_name in ordered_with_meals:
                lunch_idx = ordered_with_meals.index(lunch_name)
                # 午餐前=上午（不含午餐），午餐后=下午（不含午餐）
                morning_names = [n for n in ordered_with_meals[:lunch_idx] if n not in meal_names_set]
                # v5.2 r3 fix: 晚餐POI如果位于路线中间节点，不能过滤掉，
                # 否则下午路线会断链（如 观景台→[晚餐POI被删]→大壶春 导致"路线缺失"）
                # 只有晚餐POI是下午段末尾时才排除（避免与独立晚餐段落重复）
                _raw_afternoon = ordered_with_meals[lunch_idx + 1:]
                _dinner_in_afternoon = dinner_name and dinner_name in _raw_afternoon
                if _dinner_in_afternoon and _raw_afternoon and _raw_afternoon[-1] == dinner_name:
                    # 晚餐在末尾 → 排除（独立晚餐段会单独渲染）
                    afternoon_names = [n for n in _raw_afternoon[:-1] if n not in meal_names_set]
                else:
                    # 晚餐在中间 → 保留，确保路线链不断
                    afternoon_names = [n for n in _raw_afternoon if n not in (meal_names_set - {dinner_name})]
            elif lunch_name:
                # lunch_name不在ordered列表中（可能段不存在），回退到按segments找前驱
                lunch_predecessor = None
                for seg in route_segments:
                    if seg.day_index == day.day_index and seg.to_poi == lunch_name:
                        lunch_predecessor = seg.from_poi
                        break
                if lunch_predecessor and lunch_predecessor in names:
                    pred_idx = names.index(lunch_predecessor)
                    morning_names = names[:pred_idx + 1]
                    afternoon_names = names[pred_idx + 1:]
                else:
                    mid = len(names) // 2
                    morning_names = names[:mid + 1]
                    afternoon_names = names[mid:]
            else:
                mid = len(names) // 2
                morning_names = names[:mid + 1]
                afternoon_names = names[mid:]
            # 晚餐若已包含在下午段末尾则排除，避免重复渲染
            # v5.2 r3 fix: 如果晚餐已在路线中间保留，不再排除
            if dinner_name and afternoon_names and afternoon_names[-1] == dinner_name and dinner_name not in meal_names_set:
                afternoon_names = afternoon_names[:-1]

            lines.append(f"上午（9:00-12:00）：{title}")
            lines.append(f"  {_route_line(morning_names, segments)}")
            if anchor.recommend_reason:
                lines.append(f"  推荐理由：{anchor.recommend_reason}")
            if anchor_hints:
                hint = anchor_hints.get(anchor.name)
                if hint:
                    lines.append(f"  {hint}")

            if lunch_slots and morning_names:
                previous = _append_meal_line(lines, "lunch", morning_names[-1], meal_by_name, lunch_slots, segments, start_hour)
            elif lunch_slots:
                previous = _append_meal_line(lines, "lunch", previous, meal_by_name, lunch_slots, segments, start_hour)
            else:
                previous = morning_names[-1] if morning_names else previous

            lines.append(f"下午（14:00-18:00）：{title}")
            # v5.2修复: previous（午餐POI）是下午路线的起点，必须保留才能找到路线段
            # afternoon_names已不含meal_names_set中的名字，需要加回previous作为路线起点
            _afternoon_route_names = list(afternoon_names)
            if _afternoon_route_names and previous and previous not in _afternoon_route_names:
                _afternoon_route_names = [previous] + _afternoon_route_names
            lines.append(f"  {_route_line(_afternoon_route_names or afternoon_names, segments)}")
            previous = afternoon_names[-1] if afternoon_names else previous
        else:
            if getattr(parsed_intent, "dinner_first", False) and index == 0:
                activity_label = "晚饭后（19:00-21:30）"
            elif _is_quarter_day(parsed_intent):
                activity_label = _short_trip_label()
            elif _is_half_day(parsed_intent):
                activity_label = _half_day_label(start_hour)
            else:
                activity_label = _activity_label(index, time_budget, len(day.anchors), parsed_intent.evening_requested, start_hour)
            lines.append(f"{activity_label}：{title}")
            lines.append(f"  {_route_line(names, segments)}")
            if anchor.recommend_reason:
                lines.append(f"  推荐理由：{anchor.recommend_reason}")
            if anchor_hints:
                hint = anchor_hints.get(anchor.name)
                if hint:
                    lines.append(f"  {hint}")
            previous = names[-1] if names else anchor.name

            if index == _lunch_after_index(len(day.anchors)) and lunch_slots:
                previous = _append_meal_line(lines, "lunch", previous, meal_by_name, lunch_slots, segments, start_hour)

    if dinner_slots and not dinner_rendered:
        _append_meal_line(lines, "dinner", previous, meal_by_name, dinner_slots, segments, start_hour)
    if day_passing_pois:
        lines.append(f"  沿途可顺路游览：{'、'.join(day_passing_pois)}")
    if day_same_building_pois:
        lines.append(f"  同一建筑内还有：{'、'.join(day_same_building_pois)}")
    return "\n".join(lines)


def _all_anchors(complete_plan: CompletePlan):
    return [anchor for day in complete_plan.day_plans for anchor in day.anchors]


def _weather_warning_needed(complete_plan: CompletePlan) -> bool:
    outdoor = [
        anchor
        for anchor in _all_anchors(complete_plan)
        if (anchor.typecode or "")[:6] in OUTDOOR_TYPECODES
    ]
    return bool(outdoor) and all(anchor.final_score < WEATHER_LOW_SCORE_THRESHOLD for anchor in outdoor)


async def run_step4(
    parsed_intent: ParsedIntent,
    complete_plan: CompletePlan,
    micro_pois: list[MicroPOI],
    route_segments: list[RouteSegment],
    map_file_path: str,
    logger: PipelineLogger,
    anchor_hints: dict[str, str] | None = None,
    waypoint_annotations: dict[str, dict[str, Any]] | None = None,
    route_points: list[dict[str, Any]] | None = None,
    candidate_points: list[dict[str, Any]] | None = None,
) -> None:
    """Step 4: 生成输出"""
    logger.start_step("step_4_output")
    await emit_status("正在生成行程方案...")
    await emit_status("路线规划完成！")

    anchors = _all_anchors(complete_plan)
    # v6: 从 route_points 中取正式展示的 POI 名称作为 summary 核心
    if route_points:
        _display_names = [p.get("name") for p in route_points
                          if p.get("is_waypoint") and p.get("kind") not in ("start", "hint", "free_explore")]
    else:
        _display_names = []
    first_anchor = _display_names[0] if _display_names else (anchors[0].name if anchors else "出发点")
    last_anchor = _display_names[-1] if len(_display_names) > 1 else first_anchor
    origin = _origin_label(parsed_intent)
    meal_suffix = "，含餐饮推荐" if any(item.is_meal for item in micro_pois) else ""
    if first_anchor == last_anchor:
        summary = f"为您规划了{_duration_desc(parsed_intent)}的{complete_plan.city}之旅，从{origin}出发，以{first_anchor}为核心{meal_suffix}。"
    else:
        summary = f"为您规划了{_duration_desc(parsed_intent)}的{complete_plan.city}之旅，从{origin}出发，串联{first_anchor}到{last_anchor}{meal_suffix}。"
    await push_output(summary)

    for day in complete_plan.day_plans:
        await push_output(_day_detail(day, parsed_intent, micro_pois, route_segments, anchor_hints, waypoint_annotations))

    for anchor in anchors:
        await push_output(f"· {anchor.name}：{anchor.recommend_reason}")

    await push_output(f"[ROUTE_PLANNER]: 完整路线地图已按天生成，点击查看：{map_file_path}")
    if _weather_warning_needed(complete_plan):
        await push_output("当前天气可能影响户外活动，建议选择室内景点或改日出行。")

    # 构建完整计划数据并通过 SSE complete 事件发送给前端
    map_paths = [map_file_path] if map_file_path else []
    full_plan = {
        "summary": summary,
        "city": complete_plan.city,
        "duration": parsed_intent.duration,
        "time_budget": complete_plan.time_budget,
        "days": [
            {
                "day_index": day.day_index,
                "anchors": [
                    {
                        "name": a.name,
                        "recommend_reason": a.recommend_reason,
                    }
                    for a in day.anchors
                ],
                "meal_slots": day.meal_slots,
            }
            for day in complete_plan.day_plans
        ],
    }
    
    # 构建路线数据（用于前端验证）
    # v6: 提取 plan_mode
    _plan_mode = getattr(parsed_intent, 'plan_mode', 'exploratory') or 'exploratory'
    _duration = getattr(parsed_intent, 'duration', '') or ''
    _time_budget_val = float(getattr(parsed_intent, 'time_budget', 0) or 0)
    route_data = await _build_route_data(
        route_points, route_segments, anchor_hints, waypoint_annotations,
        candidate_points=candidate_points, plan_mode=_plan_mode,
        duration=_duration, time_budget=_time_budget_val,
        parsed_intent=parsed_intent,  # v18: for planning_state in route_data
    )

    # v6: 一致性校验 — summary 核心 POI 是否在 route_data.points 中
    _point_names = {p.get("name") for p in route_data.get("points", [])}
    _summary_refs = set()
    for day in complete_plan.day_plans:
        for anchor in day.anchors:
            _summary_refs.add(anchor.name)
        for slot in day.meal_slots:
            pn = slot.get("poi_name")
            if pn:
                _summary_refs.add(pn)
    _missing = _summary_refs - _point_names
    if _missing:
        print(f"[WARNING step4] summary_anchor_missing_in_route_points: missing={_missing} summary_refs={_summary_refs} route_point_names={_point_names}")

    # [DEBUG-雨天半天] emit_done 前打印关键字段
    print(f"[DEBUG step4] full_plan.duration={full_plan.get('duration')} full_plan.time_budget={full_plan.get('time_budget')}")
    print(f"[DEBUG step4] route_data.points count={len(route_data.get('points', []))}")
    print(f"[DEBUG step4] route_data.points names/kinds/slots: {[(p.get('name'), p.get('kind'), p.get('display_slot')) for p in route_data.get('points', [])]}")

    await emit_done(map_paths=map_paths, full_plan=full_plan, route_data=route_data)

    await logger.log_step("step_4_output", output_count=len(anchors) + len(complete_plan.day_plans) + 1)


async def _build_route_data(
    route_points: list[dict[str, Any]] | None,
    route_segments: list[RouteSegment],
    anchor_hints: dict[str, str] | None,
    waypoint_annotations: dict[str, dict[str, Any]] | None,
    candidate_points: list[dict[str, Any]] | None = None,
    plan_mode: str = "exploratory",
    duration: str = "",
    time_budget: float = 0,
    parsed_intent: Any = None,  # v18: ParsedIntent for planning_state output
) -> dict[str, Any]:
    """构建路线数据，用于前端验证

    Returns:
        包含 points, segments, hints, waypoint_annotations, candidate_points, route_id 的字典
    """
    # ---- 预处理：构建 name → point 索引、name → route_order 映射 ----
    _raw_point_by_name: dict[str, dict[str, Any]] = {}
    _route_order_by_name: dict[str, int] = {}
    if route_points:
        for i, pt in enumerate(route_points):
            name = pt.get("name", "")
            if name:
                _raw_point_by_name[name] = pt
                _route_order_by_name[name] = i + 1  # 1-based

    # 非展示 kind
    _non_display_kinds = {"hint", "free_explore", "route_only", "traffic", "empty"}

    # ---- Step 1: 为每个 point name 推导 period/slot ----
    _name_period: dict[str, str] = {}
    if route_points:
        for pt in route_points:
            name = pt.get("name", "")
            if not name:
                continue
            slot = pt.get("slot") or pt.get("period") or pt.get("time_slot") or pt.get("day_period") or ""
            if slot:
                _name_period[name] = slot

    # 从 route_points 原始顺序构建有序链（不依赖 segments，因为晚餐可能没有 segment）
    # 用 route_points 作为主序列来推断 slot
    if not _name_period and route_points:
        # 构建有序 POI 名列表：优先用 route_points 原始顺序（去重保留首次出现）
        ordered_names: list[str] = []
        seen_names: set[str] = set()
        for pt in route_points:
            name = pt.get("name", "")
            if name and name not in seen_names:
                ordered_names.append(name)
                seen_names.add(name)

        # 也从 segments 补充（确保所有 POI 都在 ordered 中）
        for seg in route_segments:
            if seg.from_poi and seg.from_poi not in seen_names:
                ordered_names.append(seg.from_poi)
                seen_names.add(seg.from_poi)
            if seg.to_poi and seg.to_poi not in seen_names:
                ordered_names.append(seg.to_poi)
                seen_names.add(seg.to_poi)

        # 标记 meal POI：识别 kind=meal 的点及其在 ordered 中的位置
        meal_names: set[str] = set()
        meal_order: list[str] = []  # 按出现顺序排列的 meal 点名称
        for pt in route_points:
            if pt.get("kind") == "meal":
                n = pt.get("name", "")
                if n and n not in meal_names:
                    meal_names.add(n)
                    meal_order.append(n)

        # 在 ordered_names 中找到 meal 的索引
        meal_indices: list[int] = []
        for mn in meal_order:
            try:
                idx = ordered_names.index(mn)
                meal_indices.append(idx)
            except ValueError:
                continue

        # 用索引正确切分 slot
        lunch_idx: int | None = meal_indices[0] if len(meal_indices) >= 1 else None
        dinner_idx: int | None = meal_indices[1] if len(meal_indices) >= 2 else None

        # 如果 meal 名称含 dinner/晚餐/晚饭 → 强制 dinner；含 lunch/午餐/午饭 → 强制 lunch
        for i, mn in enumerate(meal_order):
            mn_lower = mn.lower()
            if any(kw in mn_lower for kw in ("dinner", "晚餐", "晚饭", "晚上")):
                if i == 0 and len(meal_order) >= 2 and dinner_idx is None:
                    # 第一个 meal 强制为 dinner → 交换
                    if len(meal_indices) >= 2:
                        lunch_idx, dinner_idx = meal_indices[1], meal_indices[0]
                    elif len(meal_indices) == 1:
                        dinner_idx = meal_indices[0]
                        lunch_idx = None
            elif any(kw in mn_lower for kw in ("lunch", "午餐", "午饭", "中午")):
                if i == 1 and len(meal_indices) >= 2:
                    # 第二个 meal 标记为 lunch → 交换
                    lunch_idx, dinner_idx = meal_indices[1], meal_indices[0]

        for i, name in enumerate(ordered_names):
            if name in meal_names:
                if lunch_idx is not None and i == lunch_idx:
                    _name_period[name] = "lunch"
                elif dinner_idx is not None and i == dinner_idx:
                    _name_period[name] = "dinner"
                else:
                    # 额外的 meal → 根据位置判断
                    if lunch_idx is not None and i > lunch_idx and (dinner_idx is None or i < dinner_idx):
                        _name_period[name] = "lunch"
                    else:
                        _name_period[name] = "dinner"
            elif lunch_idx is not None:
                if i < lunch_idx:
                    _name_period[name] = "morning"
                elif dinner_idx is not None and i > dinner_idx:
                    _name_period[name] = "evening"
                elif dinner_idx is not None and lunch_idx < i < dinner_idx:
                    _name_period[name] = "afternoon"
                elif i > lunch_idx:
                    # 只有一个 lunch，lunch 之后都是 afternoon
                    _name_period[name] = "afternoon"
                else:
                    _name_period[name] = "morning"
            else:
                # No meal POIs — split evenly
                mid = len(ordered_names) // 2
                _name_period[name] = "morning" if i < mid else "afternoon"

    # v10: 按 day 分组修正 period — 防止第二天活动被误标为 evening
    if route_points and any(pt.get("day") for pt in route_points):
        days_map: dict[int, list[str]] = {}
        for pt in route_points:
            d = pt.get("day", 1)
            days_map.setdefault(d, []).append(pt.get("name", ""))
        for day_idx, names in days_map.items():
            # 对每一天独立推算 meal 位置
            day_meals = [n for n in names if n in meal_names]
            if not day_meals:
                # 无餐食 → 前一半 morning，后一半 afternoon
                mid = len(names) // 2
                for i, n in enumerate(names):
                    if day_idx > 1 and _name_period.get(n) == "evening":
                        _name_period[n] = "morning" if i < mid else "afternoon"
                continue
            # 找到当天的 lunch 和 dinner
            dlunch = day_meals[0] if len(day_meals) >= 1 else None
            ddinner = day_meals[-1] if len(day_meals) >= 2 else None
            for i, n in enumerate(names):
                if n in day_meals:
                    continue  # 餐食本身已有标记
                if dlunch and names.index(dlunch) > i:
                    _name_period[n] = "morning"
                elif ddinner and names.index(ddinner) < i:
                    _name_period[n] = "evening"
                elif dlunch and ddinner and names.index(dlunch) < i < names.index(ddinner):
                    _name_period[n] = "afternoon"
                else:
                    _name_period[n] = "afternoon"

    #  segments 有 period 属性时兜底
    for seg in route_segments:
        period = getattr(seg, "period", "") or ""
        if period:
            if seg.to_poi and not _name_period.get(seg.to_poi):
                _name_period[seg.to_poi] = period
            if seg.from_poi and not _name_period.get(seg.from_poi):
                _name_period[seg.from_poi] = period

    # ---- Step 2: 转换 points，计算 route_order / display_order / display_slot ----
    # v6: detect planned mode early
    is_planned_mode = str(plan_mode or "").lower() == "planned"

    # v6: compact exploratory display — quarter/half day should not split into morning/afternoon
    _is_short_route = duration == "a quarter day" or (time_budget > 0 and time_budget < 0.5)
    _is_half_route = duration == "a half day" or time_budget == 0.5
    _compact_activity_slot = "short_trip" if _is_short_route else "half_day" if _is_half_route else ""
    display_granularity = "short" if _is_short_route else "half_day" if _is_half_route else "day"

    points = []
    _display_counter = 0
    if route_points:
        for idx, point in enumerate(route_points):
            loc = point.get("location", {})
            if not loc or not ("lat" in loc and "lng" in loc):
                continue

            route_order = idx + 1  # 1-based
            name = point.get("name", "")
            kind = str(point.get("kind", "unknown"))
            is_waypoint = bool(point.get("is_waypoint", True))
            has_name = bool(name and name.strip())
            has_loc = True  # already checked above

            # 判断是否为展示 POI
            is_start = kind == "start"
            is_display = (
                is_start
                or (
                    kind not in _non_display_kinds
                    and is_waypoint
                    and has_name
                    and has_loc
                )
            )

            if is_start:
                display_order = 0
            elif is_display:
                # v6: planned mode — use route_order/display_order from route_points directly,
                # do NOT infer order from display_slot / name_period
                if is_planned_mode:
                    raw_order = point.get("display_order")
                    if raw_order is None:
                        raw_order = point.get("route_order")
                    display_order = int(raw_order) if raw_order is not None else route_order
                    _display_counter = max(_display_counter, display_order if display_order is not None else 0)
                else:
                    _display_counter += 1
                    display_order = _display_counter
            else:
                display_order = None

            # display_slot: 优先使用 point 自身的 explicit display_slot，其次使用推断的 _name_period
            _explicit_slot = point.get("display_slot", "") or point.get("slot", "")
            if is_planned_mode:
                # v6: planned mode — display_slot is a label only, do NOT infer from _name_period
                display_slot = (
                    _explicit_slot
                    or ""
                )
            elif _compact_activity_slot and kind not in ("meal", "restaurant"):
                # v6: compact exploratory (quarter/half day) — use single slot, don't split morning/afternoon
                display_slot = _compact_activity_slot
            else:
                display_slot = (
                    _explicit_slot
                    or _name_period.get(name, "")
                    or point.get("period", "")
                    or point.get("time_slot", "")
                    or point.get("day_period", "")
                    or ""
                )

            # display_label
            display_label = "起点" if is_start else point.get("display_label", "") or ""

            # 字段兼容读取链
            _rating = point.get("rating") or point.get("gaode_rating")
            _photo = point.get("photo_url") or ""
            if not _photo and point.get("photos"):
                photos = point["photos"]
                if isinstance(photos, list) and len(photos) > 0:
                    _photo = photos[0].get("url", "") if isinstance(photos[0], dict) else ""
            _address = point.get("address") or point.get("formatted_address", "")
            _avg_cost = point.get("avg_cost")
            if _avg_cost is None and point.get("biz_ext"):
                _avg_cost = point["biz_ext"].get("cost") if isinstance(point["biz_ext"], dict) else None
            points.append({
                "poi_id": point.get("poi_id") or point.get("gaode_poi_id") or f"{name}:{loc.get('lng')},{loc.get('lat')}",
                "gaode_poi_id": point.get("gaode_poi_id") or point.get("poi_id") or "",
                "name": name,
                "location": {"lat": loc["lat"], "lng": loc["lng"]},
                "kind": kind,
                "day": point.get("day", 1),
                "typecode": point.get("typecode", ""),
                "category": point.get("category") or point.get("typecode", ""),
                "address": _address,
                "rating": _rating,
                "gaode_rating": point.get("gaode_rating"),
                "avg_cost": _avg_cost,
                "photo_url": _photo,
                "photo_source": point.get("photo_source", ""),
                "parent_anchor": point.get("parent_name") or point.get("parent_anchor", ""),
                "sub_anchor_name": point.get("sub_anchor_name", ""),
                "recommend_reason": point.get("recommend_reason", ""),
                "visit_duration_min": point.get("visit_duration_min") or point.get("visit_min"),
                "is_waypoint": is_waypoint,
                "is_passthrough": point.get("is_passthrough", False),
                "walk_from_route_min": point.get("walk_from_route_min", 0),
                "route_annotation": point.get("route_annotation", ""),
                # ---- 稳定编号字段 ----
                "route_order": route_order,
                "display_order": display_order,
                "display_slot": display_slot,
                "is_display_poi": is_display,
                "display_label": display_label,
            })

    # v6: 过滤 — 从 points 中移除已在 candidate_points 中的非展示 anchor_internal
    if candidate_points:
        _cand_names: set[str] = {c.get("name", "") for c in candidate_points if c.get("name")}
        _cand_ids: set[str] = {c.get("poi_id") or c.get("gaode_poi_id", "") for c in candidate_points}
        _cand_ids.discard("")
        points = [
            p for p in points
            if not (
                p.get("kind") == "anchor_internal"
                and not p.get("is_waypoint", True)
                and (p.get("name") in _cand_names or p.get("poi_id") in _cand_ids or p.get("gaode_poi_id") in _cand_ids)
            )
        ]

    # 元数据统计
    pts_photo = sum(1 for p in points if p.get("photo_url"))
    pts_rating = sum(1 for p in points if p.get("rating") is not None)
    pts_addr = sum(1 for p in points if p.get("address"))
    print(f"[DEBUG step4] route_data.points count={len(points)} withPhoto={pts_photo} withRating={pts_rating} withAddress={pts_addr}")
    print(f"[DEBUG step4] route_data.candidate_points count={len(candidate_points or [])} sample={[(c.get('name',''), c.get('candidate_source','')) for c in (candidate_points or [])[:5]]}")

    # display_slot 统计
    _slot_counts: dict[str, int] = {}
    for p in points:
        s = p.get("display_slot", "none")
        _slot_counts[s] = _slot_counts.get(s, 0) + 1
    print(f"[DEBUG step4] display_slot summary={_slot_counts}")

    try:
        from services.poi_photo_service import enrich_points_with_photos
        points = await enrich_points_with_photos(points)
    except Exception:
        pass
    
    # ---- Step 3: 转换 segments，补充稳定编号字段 ----
    # 构建 display_order 反向映射: name → display_order
    _display_order_by_name: dict[str, int] = {}
    for pt in points:
        name = pt.get("name", "")
        if name and pt.get("display_order") is not None:
            _display_order_by_name[name] = pt["display_order"]

    _PERIOD_COLORS = {
        "morning": "#E67E22",
        "lunch": "#D35400",
        "afternoon": "#2980B9",
        "dinner": "#C0392B",
        "evening": "#8E44AD",
        "half_day": "#E67E22",
    }
    _FALLBACK_COLORS = ["#E67E22", "#2980B9", "#27AE60", "#8E44AD", "#E74C3C", "#F39C12", "#1ABC9C", "#C0392B"]

    segments = []
    for idx, seg in enumerate(route_segments):
        period = _name_period.get(seg.to_poi, "")
        if not period:
            period = _name_period.get(seg.from_poi, "")
        color = _PERIOD_COLORS.get(period, _FALLBACK_COLORS[idx % len(_FALLBACK_COLORS)])
        segments.append({
            "from_poi": seg.from_poi,
            "to_poi": seg.to_poi,
            "day_index": seg.day_index,
            "transport": seg.transport,
            "duration_min": seg.duration_min,
            "distance_km": seg.distance_km,
            "polyline": seg.polyline,
            "period": period,
            "color": color,
            "is_dashed": seg.transport in ("地铁/公交", "自驾") or getattr(seg, "degraded", False),
            # ---- 稳定编号字段 ----
            "segment_order": idx + 1,
            "from_order": _route_order_by_name.get(seg.from_poi),
            "to_order": _route_order_by_name.get(seg.to_poi),
            "from_display_order": _display_order_by_name.get(seg.from_poi),
            "to_display_order": _display_order_by_name.get(seg.to_poi),
            # ---- v6: degraded 路线标记 ----
            "degraded": getattr(seg, "degraded", False),
            "polyline_source": getattr(seg, "polyline_source", ""),
            "route_error": getattr(seg, "route_error", ""),
        })

    # ---- [RouteDebug] 调试日志 ----
    print("[RouteDebug] points:")
    for pt in points:
        print(f"  route_order={pt['route_order']} display_order={pt.get('display_order')} "
              f"name={pt['name']} kind={pt['kind']} is_waypoint={pt['is_waypoint']} "
              f"display_slot={pt.get('display_slot','')} location=({pt['location']['lng']},{pt['location']['lat']})")
    print("[RouteDebug] segments:")
    for seg in segments:
        print(f"  segment_order={seg['segment_order']} "
              f"from_poi={seg['from_poi']} to_poi={seg['to_poi']} "
              f"from_display_order={seg.get('from_display_order')} to_display_order={seg.get('to_display_order')} "
              f"distance_km={seg['distance_km']} duration_min={seg['duration_min']} period={seg['period']} "
              f"degraded={seg.get('degraded', False)} polyline_source={seg.get('polyline_source', '')}")

    # 计算总天数
    _total_days = 1
    if route_points:
        _days = {pt.get("day", 1) for pt in route_points}
        _total_days = max(_days) if _days else 1

    route_id = str(uuid.uuid4())
    _route_cache[route_id] = {"points": points, "segments": segments}

    # v18: build planning_state from parsed_intent for frontend compatibility
    planning_state: dict[str, Any] = {}
    parsed_intent_light: dict[str, Any] = {}
    if parsed_intent is not None:
        wp_list = []
        for wp in (getattr(parsed_intent, 'planned_waypoints', []) or []):
            wp_list.append({
                "type": getattr(wp, 'type', ''),
                "name": getattr(wp, 'name', ''),
                "search_keyword": getattr(wp, 'search_keyword', ''),
                "category": getattr(wp, 'category', ''),
                "stay_minutes": getattr(wp, 'stay_minutes', 0),
                "search_keywords": getattr(wp, 'search_keywords', []) or [],
            })
        parsed_intent_light = {
            "duration": getattr(parsed_intent, 'duration', ''),
            "start_time": parsed_intent.start_time.isoformat() if getattr(parsed_intent, 'start_time', None) else None,
            "raw_keywords": getattr(parsed_intent, 'raw_keywords', []) or [],
            "search_keywords": getattr(parsed_intent, 'search_keywords', []) or [],
            "micro_keywords": getattr(parsed_intent, 'micro_keywords', []) or [],
            "fixed_pois": [{"name": f.name, "user_time_budget": f.user_time_budget} for f in (getattr(parsed_intent, 'fixed_pois', []) or [])],
            "delete_list": getattr(parsed_intent, 'delete_list', []) or [],
            "food_pref_keywords": getattr(parsed_intent, 'food_pref_keywords', []) or [],
            "meal_search_keywords": getattr(parsed_intent, 'meal_search_keywords', []) or [],
            "budget_per_capita": getattr(parsed_intent, 'budget_per_capita', None),
            "transport_hint": getattr(parsed_intent, 'transport_hint', '公共交通'),
            "evening_requested": getattr(parsed_intent, 'evening_requested', False),
            "plan_mode": getattr(parsed_intent, 'plan_mode', 'exploratory') or 'exploratory',
            "planned_waypoints": wp_list,
        }
        planning_state = {
            "plan_mode": parsed_intent_light["plan_mode"],
            "parsed_intent": parsed_intent_light,
        }

    return {
        "points": points,
        "segments": segments,
        "hints": anchor_hints or {},
        "waypoint_annotations": waypoint_annotations or {},
        "route_id": route_id,
        "candidate_points": candidate_points or [],
        "plan_mode": plan_mode,
        "total_days": _total_days,
        "display_granularity": display_granularity,
        "planning_state": planning_state,       # v18: for frontend to read detected plan_mode
        "parsed_intent": parsed_intent_light,   # v18: backward compat for previous_intent
    }
