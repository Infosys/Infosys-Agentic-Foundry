# # # # # © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
# # # # """
# # # # Token-usage Excel export endpoint.

# # # # GET /token-usage/export
# # # #     Optional query params: user_id, agent_id, agent_name, date_from, date_to, model

# # # # Returns a multi-sheet Excel workbook (.xlsx) as a downloadable attachment.

# # # # Sheets
# # # # ------
# # # # 1. Summary            – aggregate KPIs (total tokens, total cost, call counts …)
# # # # 2. Query Usage        – one row per user query  (from query_token_usage table)
# # # # 3. LLM Call Details   – one row per individual LLM call (from token_usage_logs table)
# # # # 4. Daily Trend        – tokens & cost aggregated by calendar day  + embedded LineChart
# # # # 5. Cost by Model      – cost & token breakdown per model           + embedded BarChart
# # # # 6. Cost by Category   – cost breakdown per call_category           + embedded PieChart
# # # # """

# # # # import io
# # # # import json
# # # # from datetime import datetime, date
# # # # from typing import Optional, List, Dict, Any

# # # # from fastapi import APIRouter, Depends, Query, HTTPException
# # # # from fastapi.responses import StreamingResponse
# # # # from openpyxl import Workbook
# # # # from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
# # # # from openpyxl.chart import BarChart, LineChart, PieChart, Reference
# # # # from openpyxl.chart.series import DataPoint
# # # # from openpyxl.utils import get_column_letter

# # # # from src.database.repositories import QueryTokenUsageRepository, TokenUsageLogsRepository
# # # # from src.api.dependencies import ServiceProvider
# # # # from src.auth.dependencies import get_current_user
# # # # from src.auth.models import User
# # # # from telemetry_wrapper import logger as log


# # # # router = APIRouter(prefix="/token-usage", tags=["Token Usage Report"])

# # # # # ─────────────────────────────────────────────────────────────────────────────
# # # # # Colour palette
# # # # # ─────────────────────────────────────────────────────────────────────────────
# # # # _HEADER_FILL   = PatternFill("solid", fgColor="1F4E79")   # dark blue
# # # # _ALT_ROW_FILL  = PatternFill("solid", fgColor="D6E4F0")   # light blue
# # # # _SUMMARY_FILL  = PatternFill("solid", fgColor="2E75B6")   # medium blue
# # # # _HEADER_FONT   = Font(bold=True, color="FFFFFF", size=10)
# # # # _TITLE_FONT    = Font(bold=True, size=14, color="1F4E79")
# # # # _BOLD_FONT     = Font(bold=True)
# # # # _THIN_BORDER   = Border(
# # # #     left=Side(style="thin"), right=Side(style="thin"),
# # # #     top=Side(style="thin"),  bottom=Side(style="thin"),
# # # # )


# # # # def _style_header_row(ws, row: int, n_cols: int) -> None:
# # # #     for col in range(1, n_cols + 1):
# # # #         cell = ws.cell(row=row, column=col)
# # # #         cell.fill   = _HEADER_FILL
# # # #         cell.font   = _HEADER_FONT
# # # #         cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
# # # #         cell.border = _THIN_BORDER


# # # # def _style_data_row(ws, row: int, n_cols: int, alt: bool = False) -> None:
# # # #     fill = _ALT_ROW_FILL if alt else PatternFill("solid", fgColor="FFFFFF")
# # # #     for col in range(1, n_cols + 1):
# # # #         cell = ws.cell(row=row, column=col)
# # # #         cell.fill   = fill
# # # #         cell.border = _THIN_BORDER
# # # #         cell.alignment = Alignment(vertical="center", wrap_text=False)


# # # # def _auto_width(ws, min_w: int = 10, max_w: int = 50) -> None:
# # # #     for col in ws.columns:
# # # #         width = max(
# # # #             (len(str(cell.value)) if cell.value else 0 for cell in col),
# # # #             default=min_w,
# # # #         )
# # # #         ws.column_dimensions[get_column_letter(col[0].column)].width = min(max(width + 2, min_w), max_w)


# # # # def _write_headers(ws, headers: List[str], row: int = 1) -> None:
# # # #     for ci, h in enumerate(headers, 1):
# # # #         ws.cell(row=row, column=ci, value=h)
# # # #     _style_header_row(ws, row, len(headers))


# # # # # ─────────────────────────────────────────────────────────────────────────────
# # # # # Sheet builders
# # # # # ─────────────────────────────────────────────────────────────────────────────

# # # # def _build_summary_sheet(ws, query_rows: List[Dict], log_rows: List[Dict],
# # # #                           filters: Dict[str, Any]) -> None:
# # # #     ws.title = "Summary"
# # # #     ws.sheet_view.showGridLines = False

# # # #     # Title
# # # #     ws.merge_cells("A1:D1")
# # # #     title_cell = ws["A1"]
# # # #     title_cell.value = "Token Usage & Cost — Summary Report"
# # # #     title_cell.font  = _TITLE_FONT
# # # #     title_cell.alignment = Alignment(horizontal="center", vertical="center")
# # # #     ws.row_dimensions[1].height = 28

# # # #     # Applied filters
# # # #     ws["A3"] = "Filters Applied"
# # # #     ws["A3"].font = _BOLD_FONT
# # # #     row = 4
# # # #     for k, v in filters.items():
# # # #         if v:
# # # #             ws.cell(row=row, column=1, value=k)
# # # #             ws.cell(row=row, column=2, value=str(v))
# # # #             row += 1
# # # #     if row == 4:
# # # #         ws.cell(row=row, column=1, value="(none)")
# # # #         row += 1

# # # #     row += 1  # blank separator

# # # #     # KPI block
# # # #     kpi_header_row = row
# # # #     ws.cell(row=kpi_header_row, column=1, value="Metric")
# # # #     ws.cell(row=kpi_header_row, column=2, value="Value")
# # # #     _style_header_row(ws, kpi_header_row, 2)
# # # #     row += 1

# # # #     total_prompt     = sum(r.get("prompt_tokens",     0)   for r in query_rows)
# # # #     total_completion = sum(r.get("completion_tokens", 0)   for r in query_rows)
# # # #     total_cached     = sum(r.get("cached_tokens",     0)   for r in query_rows)
# # # #     total_tokens     = sum(r.get("total_tokens",      0)   for r in query_rows)
# # # #     total_cost       = sum(float(r.get("total_cost",  0.0)) for r in query_rows)
# # # #     total_queries    = len(query_rows)
# # # #     query_llm_calls  = sum(r.get("total_llm_calls",  0)   for r in query_rows)
# # # #     total_llm_calls  = len(log_rows)
# # # #     unique_agents    = len({r.get("agent_name") or r.get("agent_id") for r in query_rows} - {None})
# # # #     unique_users     = len({r.get("user_id") for r in query_rows} - {None})

# # # #     kpis = [
# # # #         ("Total Queries",               total_queries),
# # # #         ("Query-Related LLM Calls",     query_llm_calls),
# # # #         ("Total LLM Calls",             total_llm_calls),
# # # #         ("Total Prompt Tokens",         total_prompt),
# # # #         ("Total Completion Tokens",     total_completion),
# # # #         ("Total Cached Tokens",         total_cached),
# # # #         ("Total Tokens",                total_tokens),
# # # #         ("Total Cost (USD)",            f"${total_cost:.6f}"),
# # # #         ("Unique Agents",               unique_agents),
# # # #         ("Unique Users",                unique_users),
# # # #     ]
# # # #     for i, (metric, value) in enumerate(kpis):
# # # #         ws.cell(row=row, column=1, value=metric)
# # # #         ws.cell(row=row, column=2, value=value)
# # # #         _style_data_row(ws, row, 2, alt=(i % 2 == 1))
# # # #         row += 1

# # # #     _auto_width(ws)
# # # #     ws.column_dimensions["A"].width = 30
# # # #     ws.column_dimensions["B"].width = 20


# # # # def _build_query_usage_sheet(ws, rows: List[Dict]) -> None:
# # # #     ws.title = "Query Usage"

# # # #     headers = [
# # # #         "ID", "Created At", "User ID", "Agent ID", "Agent Name",
# # # #         "Session ID", "Query",
# # # #         "Prompt Tokens", "Completion Tokens", "Cached Tokens", "Total Tokens",
# # # #         "Prompt Cost ($)", "Completion Cost ($)", "Cached Cost ($)", "Total Cost ($)",
# # # #         "Total LLM Calls",
# # # #     ]
# # # #     _write_headers(ws, headers, row=1)
# # # #     ws.row_dimensions[1].height = 30

# # # #     for ri, r in enumerate(rows, 2):
# # # #         values = [
# # # #             r.get("id"),
# # # #             r.get("created_at").strftime("%Y-%m-%d %H:%M:%S") if r.get("created_at") else None,
# # # #             r.get("user_id"),
# # # #             r.get("agent_id"),
# # # #             r.get("agent_name"),
# # # #             r.get("session_id"),
# # # #             r.get("query"),
# # # #             r.get("prompt_tokens", 0),
# # # #             r.get("completion_tokens", 0),
# # # #             r.get("cached_tokens", 0),
# # # #             r.get("total_tokens", 0),
# # # #             float(r.get("prompt_cost", 0)),
# # # #             float(r.get("completion_cost", 0)),
# # # #             float(r.get("cached_cost", 0)),
# # # #             float(r.get("total_cost", 0)),
# # # #             r.get("total_llm_calls", 0),
# # # #         ]
# # # #         for ci, v in enumerate(values, 1):
# # # #             ws.cell(row=ri, column=ci, value=v)
# # # #         _style_data_row(ws, ri, len(headers), alt=(ri % 2 == 0))

# # # #     _auto_width(ws)
# # # #     ws.freeze_panes = "A2"


# # # # def _build_llm_calls_sheet(ws, log_rows: List[Dict], query_rows: List[Dict]) -> None:
# # # #     """
# # # #     Populate from token_usage_logs if available; otherwise explode the llm_calls
# # # #     JSONB column from query_token_usage rows.
# # # #     """
# # # #     ws.title = "LLM Call Details"

# # # #     headers = [
# # # #         "Timestamp", "User ID", "Agent ID", "Agent Name", "Session ID",
# # # #         "Model", "Prompt Tokens", "Completion Tokens", "Cached Tokens", "Total Tokens",
# # # #         "Prompt Cost ($)", "Completion Cost ($)", "Cached Cost ($)", "Total Cost ($)",
# # # #         "Status", "Call Category", "Call Sub-Category", "Call Operation",
# # # #         "Tool Name", "Agent Type", "Agent Component",
# # # #     ]
# # # #     _write_headers(ws, headers, row=1)
# # # #     ws.row_dimensions[1].height = 30

# # # #     ri = 2
# # # #     if log_rows:
# # # #         for r in log_rows:
# # # #             values = [
# # # #                 r.get("timestamp").strftime("%Y-%m-%d %H:%M:%S") if r.get("timestamp") else None,
# # # #                 r.get("user_id"),
# # # #                 str(r.get("agent_id", "")),
# # # #                 r.get("agent_name"),
# # # #                 r.get("session_id"),
# # # #                 r.get("model_name"),
# # # #                 r.get("prompt_tokens", 0),
# # # #                 r.get("completion_tokens", 0),
# # # #                 r.get("cached_tokens", 0),
# # # #                 r.get("total_tokens", 0),
# # # #                 float(r.get("prompt_tokens_cost", 0) or 0),
# # # #                 float(r.get("completion_tokens_cost", 0) or 0),
# # # #                 float(r.get("cached_tokens_cost", 0) or 0),
# # # #                 float(r.get("total_cost", 0) or 0),
# # # #                 r.get("status"),
# # # #                 r.get("call_category"),
# # # #                 r.get("call_sub_category"),
# # # #                 r.get("call_operation"),
# # # #                 r.get("tool_name"),
# # # #                 r.get("agent_type"),
# # # #                 r.get("agent_component"),
# # # #             ]
# # # #             for ci, v in enumerate(values, 1):
# # # #                 ws.cell(row=ri, column=ci, value=v)
# # # #             _style_data_row(ws, ri, len(headers), alt=(ri % 2 == 0))
# # # #             ri += 1
# # # #     else:
# # # #         # Fallback: explode llm_calls JSONB from query rows
# # # #         for qr in query_rows:
# # # #             raw_calls = qr.get("llm_calls") or []
# # # #             if isinstance(raw_calls, str):
# # # #                 try:
# # # #                     raw_calls = json.loads(raw_calls)
# # # #                 except Exception:
# # # #                     raw_calls = []
# # # #             created_at = qr.get("created_at")
# # # #             ts_str = created_at.strftime("%Y-%m-%d %H:%M:%S") if created_at else None
# # # #             for call in raw_calls:
# # # #                 values = [
# # # #                     ts_str,
# # # #                     qr.get("user_id"),
# # # #                     qr.get("agent_id"),
# # # #                     qr.get("agent_name"),
# # # #                     qr.get("session_id"),
# # # #                     call.get("model"),
# # # #                     call.get("prompt_tokens", 0),
# # # #                     call.get("completion_tokens", 0),
# # # #                     call.get("cached_tokens", 0),
# # # #                     call.get("total_tokens", 0),
# # # #                     float(call.get("prompt_cost", 0) or 0),
# # # #                     float(call.get("completion_cost", 0) or 0),
# # # #                     float(call.get("cached_cost", 0) or 0),
# # # #                     float(call.get("total_cost", 0) or 0),
# # # #                     call.get("status"),
# # # #                     call.get("call_category"),
# # # #                     call.get("call_sub_category"),
# # # #                     None, None, None, None,
# # # #                 ]
# # # #                 for ci, v in enumerate(values, 1):
# # # #                     ws.cell(row=ri, column=ci, value=v)
# # # #                 _style_data_row(ws, ri, len(headers), alt=(ri % 2 == 0))
# # # #                 ri += 1

# # # #     _auto_width(ws)
# # # #     ws.freeze_panes = "A2"


# # # # def _build_daily_trend_sheet(ws, log_rows: List[Dict], query_rows: List[Dict]) -> None:
# # # #     ws.title = "Daily Trend"

# # # #     # Aggregate by day
# # # #     day_map: Dict[str, Dict[str, float]] = {}

# # # #     def _add_day(day_str: str, tokens: int, cost: float) -> None:
# # # #         if day_str not in day_map:
# # # #             day_map[day_str] = {"total_tokens": 0, "total_cost": 0.0, "call_count": 0}
# # # #         day_map[day_str]["total_tokens"] += tokens
# # # #         day_map[day_str]["total_cost"]   += cost
# # # #         day_map[day_str]["call_count"]   += 1

# # # #     if log_rows:
# # # #         for r in log_rows:
# # # #             ts = r.get("timestamp")
# # # #             if ts:
# # # #                 day_str = ts.strftime("%Y-%m-%d")
# # # #                 _add_day(day_str, r.get("total_tokens", 0), float(r.get("total_cost", 0) or 0))
# # # #     else:
# # # #         for r in query_rows:
# # # #             ts = r.get("created_at")
# # # #             if ts:
# # # #                 day_str = ts.strftime("%Y-%m-%d")
# # # #                 _add_day(day_str, r.get("total_tokens", 0), float(r.get("total_cost", 0) or 0))

# # # #     sorted_days = sorted(day_map.keys())

# # # #     headers = ["Date", "Total Tokens", "Total Cost ($)", "LLM Call Count"]
# # # #     _write_headers(ws, headers, row=1)

# # # #     for ri, day in enumerate(sorted_days, 2):
# # # #         d = day_map[day]
# # # #         ws.cell(row=ri, column=1, value=day)
# # # #         ws.cell(row=ri, column=2, value=d["total_tokens"])
# # # #         ws.cell(row=ri, column=3, value=round(d["total_cost"], 8))
# # # #         ws.cell(row=ri, column=4, value=d["call_count"])
# # # #         _style_data_row(ws, ri, 4, alt=(ri % 2 == 0))

# # # #     _auto_width(ws)
# # # #     ws.freeze_panes = "A2"

# # # #     n = len(sorted_days)
# # # #     if n < 2:
# # # #         return

# # # #     # LineChart — tokens over time
# # # #     chart = LineChart()
# # # #     chart.title  = "Daily Token Usage Trend"
# # # #     chart.style  = 10
# # # #     chart.y_axis.title = "Tokens"
# # # #     chart.x_axis.title = "Date"
# # # #     chart.height = 14
# # # #     chart.width  = 26

# # # #     data_ref   = Reference(ws, min_col=2, min_row=1, max_row=1 + n)
# # # #     cats_ref   = Reference(ws, min_col=1, min_row=2, max_row=1 + n)
# # # #     chart.add_data(data_ref, titles_from_data=True)
# # # #     chart.set_categories(cats_ref)
# # # #     chart.series[0].graphicalProperties.line.solidFill = "2E75B6"

# # # #     ws.add_chart(chart, f"F2")


# # # # def _build_cost_by_model_sheet(ws, log_rows: List[Dict], query_rows: List[Dict]) -> None:
# # # #     ws.title = "Cost by Model"

# # # #     model_map: Dict[str, Dict[str, float]] = {}

# # # #     def _add_model(model: str, tokens: int, cost: float) -> None:
# # # #         model = model or "unknown"
# # # #         if model not in model_map:
# # # #             model_map[model] = {"total_tokens": 0, "total_cost": 0.0, "call_count": 0}
# # # #         model_map[model]["total_tokens"] += tokens
# # # #         model_map[model]["total_cost"]   += cost
# # # #         model_map[model]["call_count"]   += 1

# # # #     if log_rows:
# # # #         for r in log_rows:
# # # #             _add_model(r.get("model_name", ""), r.get("total_tokens", 0),
# # # #                        float(r.get("total_cost", 0) or 0))
# # # #     else:
# # # #         for qr in query_rows:
# # # #             raw_calls = qr.get("llm_calls") or []
# # # #             if isinstance(raw_calls, str):
# # # #                 try:
# # # #                     raw_calls = json.loads(raw_calls)
# # # #                 except Exception:
# # # #                     raw_calls = []
# # # #             for call in raw_calls:
# # # #                 _add_model(call.get("model", ""), call.get("total_tokens", 0),
# # # #                            float(call.get("total_cost", 0) or 0))

# # # #     sorted_models = sorted(model_map.keys())

# # # #     headers = ["Model", "Total Tokens", "Total Cost ($)", "LLM Call Count"]
# # # #     _write_headers(ws, headers, row=1)

# # # #     for ri, model in enumerate(sorted_models, 2):
# # # #         d = model_map[model]
# # # #         ws.cell(row=ri, column=1, value=model)
# # # #         ws.cell(row=ri, column=2, value=d["total_tokens"])
# # # #         ws.cell(row=ri, column=3, value=round(d["total_cost"], 8))
# # # #         ws.cell(row=ri, column=4, value=d["call_count"])
# # # #         _style_data_row(ws, ri, 4, alt=(ri % 2 == 0))

# # # #     _auto_width(ws)
# # # #     ws.freeze_panes = "A2"

# # # #     n = len(sorted_models)
# # # #     if n < 1:
# # # #         return

# # # #     # BarChart — cost per model
# # # #     chart = BarChart()
# # # #     chart.type   = "col"
# # # #     chart.title  = "Cost by Model"
# # # #     chart.style  = 10
# # # #     chart.y_axis.title = "Total Cost (USD)"
# # # #     chart.x_axis.title = "Model"
# # # #     chart.height = 14
# # # #     chart.width  = 26

# # # #     data_ref = Reference(ws, min_col=3, min_row=1, max_row=1 + n)
# # # #     cats_ref = Reference(ws, min_col=1, min_row=2, max_row=1 + n)
# # # #     chart.add_data(data_ref, titles_from_data=True)
# # # #     chart.set_categories(cats_ref)
# # # #     chart.series[0].graphicalProperties.solidFill = "2E75B6"

# # # #     ws.add_chart(chart, "F2")


# # # # def _build_cost_by_category_sheet(ws, log_rows: List[Dict], query_rows: List[Dict]) -> None:
# # # #     ws.title = "Cost by Category"

# # # #     cat_map: Dict[str, Dict[str, float]] = {}

# # # #     def _add_cat(cat: str, tokens: int, cost: float) -> None:
# # # #         cat = cat or "uncategorized"
# # # #         if cat not in cat_map:
# # # #             cat_map[cat] = {"total_tokens": 0, "total_cost": 0.0, "call_count": 0}
# # # #         cat_map[cat]["total_tokens"] += tokens
# # # #         cat_map[cat]["total_cost"]   += cost
# # # #         cat_map[cat]["call_count"]   += 1

# # # #     if log_rows:
# # # #         for r in log_rows:
# # # #             _add_cat(r.get("call_category", ""), r.get("total_tokens", 0),
# # # #                      float(r.get("total_cost", 0) or 0))
# # # #     else:
# # # #         for qr in query_rows:
# # # #             raw_calls = qr.get("llm_calls") or []
# # # #             if isinstance(raw_calls, str):
# # # #                 try:
# # # #                     raw_calls = json.loads(raw_calls)
# # # #                 except Exception:
# # # #                     raw_calls = []
# # # #             for call in raw_calls:
# # # #                 _add_cat(call.get("call_category", ""), call.get("total_tokens", 0),
# # # #                          float(call.get("total_cost", 0) or 0))

# # # #     sorted_cats = sorted(cat_map.keys())

# # # #     headers = ["Category", "Total Tokens", "Total Cost ($)", "LLM Call Count"]
# # # #     _write_headers(ws, headers, row=1)

# # # #     for ri, cat in enumerate(sorted_cats, 2):
# # # #         d = cat_map[cat]
# # # #         ws.cell(row=ri, column=1, value=cat)
# # # #         ws.cell(row=ri, column=2, value=d["total_tokens"])
# # # #         ws.cell(row=ri, column=3, value=round(d["total_cost"], 8))
# # # #         ws.cell(row=ri, column=4, value=d["call_count"])
# # # #         _style_data_row(ws, ri, 4, alt=(ri % 2 == 0))

# # # #     _auto_width(ws)
# # # #     ws.freeze_panes = "A2"

# # # #     n = len(sorted_cats)
# # # #     if n < 1:
# # # #         return

# # # #     # PieChart — cost share by category
# # # #     chart = PieChart()
# # # #     chart.title  = "Cost Share by Call Category"
# # # #     chart.style  = 10
# # # #     chart.height = 14
# # # #     chart.width  = 20

# # # #     data_ref = Reference(ws, min_col=3, min_row=1, max_row=1 + n)
# # # #     cats_ref = Reference(ws, min_col=1, min_row=2, max_row=1 + n)
# # # #     chart.add_data(data_ref, titles_from_data=True)
# # # #     chart.set_categories(cats_ref)
# # # #     chart.dataLabels = None

# # # #     ws.add_chart(chart, "F2")


# # # # # ─────────────────────────────────────────────────────────────────────────────
# # # # # Endpoint
# # # # # ─────────────────────────────────────────────────────────────────────────────

# # # # @router.get(
# # # #     "/export",
# # # #     summary="Download token-usage & cost report as Excel",
# # # #     response_description="Excel workbook (.xlsx) with 6 analysis sheets and embedded charts",
# # # # )
# # # # async def export_token_usage_report(
# # # #     user_id: Optional[str]   = Query(None, description="Filter by user e-mail"),
# # # #     agent_id: Optional[str]  = Query(None, description="Filter by agent ID"),
# # # #     agent_name: Optional[str] = Query(None, description="Filter by agent name (partial match)"),
# # # #     date_from: Optional[date] = Query(None, description="Start date  (YYYY-MM-DD)"),
# # # #     date_to: Optional[date]   = Query(None, description="End date    (YYYY-MM-DD)"),
# # # #     model: Optional[str]      = Query(None, description="Filter by model name (partial match, applied to LLM call details)"),
# # # #     user_data: User = Depends(get_current_user),
# # # #     query_token_usage_repo: QueryTokenUsageRepository = Depends(ServiceProvider.get_query_token_usage_repo),
# # # #     token_usage_logs_repo: TokenUsageLogsRepository   = Depends(ServiceProvider.get_token_usage_logs_repo),
# # # # ):
# # # #     """
# # # #     Export a token-usage and cost report as an Excel (.xlsx) file.

# # # #     The workbook contains 6 sheets:

# # # #     | Sheet              | Content                                    |
# # # #     |--------------------|--------------------------------------------|
# # # #     | Summary            | Aggregate KPIs for the selected filters    |
# # # #     | Query Usage        | One row per user query                     |
# # # #     | LLM Call Details   | One row per individual LLM call            |
# # # #     | Daily Trend        | Tokens & cost by day + line chart          |
# # # #     | Cost by Model      | Cost breakdown per model + bar chart       |
# # # #     | Cost by Category   | Cost breakdown per category + pie chart    |
# # # #     """
# # # #     dt_from = datetime(date_from.year, date_from.month, date_from.day) if date_from else None
# # # #     dt_to   = datetime(date_to.year,   date_to.month,   date_to.day,
# # # #                        23, 59, 59) if date_to else None

# # # #     log.info(
# # # #         f"[TokenUsageExport] Request by {user_data.email} | "
# # # #         f"filters: user_id={user_id}, agent_id={agent_id}, agent_name={agent_name}, "
# # # #         f"date_from={date_from}, date_to={date_to}, model={model}"
# # # #     )

# # # #     # Fetch data from both sources concurrently
# # # #     import asyncio
# # # #     query_rows, log_rows = await asyncio.gather(
# # # #         query_token_usage_repo.get_report_data(
# # # #             user_id=user_id,
# # # #             agent_id=agent_id,
# # # #             agent_name=agent_name,
# # # #             date_from=dt_from,
# # # #             date_to=dt_to,
# # # #         ),
# # # #         token_usage_logs_repo.get_report_data(
# # # #             user_id=user_id,
# # # #             agent_id=agent_id,
# # # #             agent_name=agent_name,
# # # #             date_from=dt_from,
# # # #             date_to=dt_to,
# # # #             model=model,
# # # #         ),
# # # #     )

# # # #     log.info(
# # # #         f"[TokenUsageExport] Fetched {len(query_rows)} query rows, "
# # # #         f"{len(log_rows)} LLM call rows"
# # # #     )

# # # #     if not query_rows and not log_rows:
# # # #         raise HTTPException(
# # # #             status_code=404,
# # # #             detail="No token usage data found for the given filters.",
# # # #         )

# # # #     filters = {
# # # #         "User ID":    user_id,
# # # #         "Agent ID":   agent_id,
# # # #         "Agent Name": agent_name,
# # # #         "Date From":  str(date_from) if date_from else None,
# # # #         "Date To":    str(date_to)   if date_to   else None,
# # # #         "Model":      model,
# # # #     }

# # # #     # Build workbook
# # # #     wb = Workbook()
# # # #     wb.remove(wb.active)  # remove default blank sheet

# # # #     _build_summary_sheet(wb.create_sheet(),       query_rows, log_rows, filters)
# # # #     _build_query_usage_sheet(wb.create_sheet(),   query_rows)
# # # #     _build_llm_calls_sheet(wb.create_sheet(),     log_rows, query_rows)
# # # #     _build_daily_trend_sheet(wb.create_sheet(),   log_rows, query_rows)
# # # #     _build_cost_by_model_sheet(wb.create_sheet(), log_rows, query_rows)
# # # #     _build_cost_by_category_sheet(wb.create_sheet(), log_rows, query_rows)

# # # #     # Serialise to bytes
# # # #     buffer = io.BytesIO()
# # # #     wb.save(buffer)
# # # #     buffer.seek(0)

# # # #     ts = datetime.now().strftime("%Y%m%d_%H%M%S")
# # # #     filename = f"token_usage_report_{ts}.xlsx"

# # # #     log.info(f"[TokenUsageExport] Workbook built — returning '{filename}'")

# # # #     return StreamingResponse(
# # # #         buffer,
# # # #         media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
# # # #         headers={"Content-Disposition": f'attachment; filename="{filename}"'},
# # # #     )

# # # # © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.

# # # """
# # # Token Usage Report Endpoints - IMPROVED VERSION

# # # Generates comprehensive token usage and cost reports with:
# # # - Multi-sheet Excel export with downloadable file
# # # - Summary JSON response for UI rendering
# # # - Daily trends, model breakdown, category analysis
# # # """

# # # import os
# # # from pathlib import Path
# # # from datetime import datetime, date
# # # from typing import List, Dict, Optional, Any

# # # from fastapi import APIRouter, Depends, HTTPException, Query
# # # from fastapi.responses import FileResponse
# # # from pydantic import BaseModel, Field

# # # from openpyxl import Workbook
# # # from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
# # # from openpyxl.chart import LineChart, BarChart, PieChart, Reference
# # # from openpyxl.utils import get_column_letter

# # # from src.database.repositories import QueryTokenUsageRepository, TokenUsageLogsRepository
# # # from src.api.dependencies import ServiceProvider
# # # from src.auth.dependencies import get_current_user
# # # from src.auth.models import User, UserRole
# # # from telemetry_wrapper import logger as log

# # # router = APIRouter(prefix="/reports", tags=["Reports - Token Usage"])

# # # # ========== EXCEL STYLING CONSTANTS ==========
# # # _TITLE_FONT = Font(name="Calibri", size=16, bold=True, color="FFFFFF")
# # # _HEADER_FONT = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
# # # _SUMMARY_FILL = PatternFill("solid", fgColor="2E75B6")
# # # _HEADER_FILL = PatternFill("solid", fgColor="4472C4")
# # # _ALT_ROW_FILL = PatternFill("solid", fgColor="D9E1F2")
# # # _THIN_BORDER = Border(
# # #     left=Side(style="thin"), right=Side(style="thin"),
# # #     top=Side(style="thin"), bottom=Side(style="thin")
# # # )
# # # _CENTER_ALIGN = Alignment(horizontal="center", vertical="center", wrap_text=True)
# # # _LEFT_ALIGN = Alignment(horizontal="left", vertical="center", wrap_text=False)


# # # # ========== RESPONSE MODELS ==========

# # # class TokenUsageSummary(BaseModel):
# # #     """Summary data for UI rendering"""
# # #     total_queries: int
# # #     total_llm_calls: int
# # #     total_tokens: int
# # #     total_cost: float
# # #     prompt_tokens: int
# # #     completion_tokens: int
# # #     cached_tokens: int
# # #     unique_users: int
# # #     unique_agents: int
# # #     unique_models: int
# # #     date_range: Dict[str, Optional[str]]
# # #     top_agents: List[Dict[str, Any]]
# # #     top_models: List[Dict[str, Any]]
# # #     category_breakdown: List[Dict[str, Any]]


# # # class TokenUsageReportResponse(BaseModel):
# # #     """Response with both summary and file download info"""
# # #     summary: TokenUsageSummary
# # #     file_download_url: str
# # #     filename: str
# # #     generated_at: str


# # # # ========== HELPER FUNCTIONS ==========

# # # def _apply_header_style(ws, row_num: int, headers: List[str]):
# # #     """Apply header styling to a row"""
# # #     for col_idx, header in enumerate(headers, start=1):
# # #         cell = ws.cell(row=row_num, column=col_idx, value=header)
# # #         cell.font = _HEADER_FONT
# # #         cell.fill = _HEADER_FILL
# # #         cell.alignment = _CENTER_ALIGN
# # #         cell.border = _THIN_BORDER


# # # def _auto_size_columns(ws, min_width=10, max_width=50):
# # #     """Auto-size columns based on content"""
# # #     for column in ws.columns:
# # #         max_length = 0
# # #         column_letter = get_column_letter(column[0].column)
# # #         for cell in column:
# # #             try:
# # #                 if cell.value:
# # #                     max_length = max(max_length, len(str(cell.value)))
# # #             except:
# # #                 pass
# # #         adjusted_width = min(max(max_length + 2, min_width), max_width)
# # #         ws.column_dimensions[column_letter].width = adjusted_width


# # # def _build_summary_sheet(ws, query_rows: List[Dict], log_rows: List[Dict], date_from, date_to):
# # #     """Build the Summary sheet"""
# # #     ws.title = "Summary"
    
# # #     # Title
# # #     ws.merge_cells('A1:D1')
# # #     title_cell = ws['A1']
# # #     title_cell.value = "Token Usage Report - Summary"
# # #     title_cell.font = _TITLE_FONT
# # #     title_cell.fill = _SUMMARY_FILL
# # #     title_cell.alignment = _CENTER_ALIGN
    
# # #     # Date range
# # #     ws['A2'] = "Report Period:"
# # #     ws['B2'] = f"{date_from or 'All'} to {date_to or 'All'}"
# # #     ws['A2'].font = Font(bold=True)
    
# # #     # Overall metrics
# # #     row = 4
# # #     ws.merge_cells(f'A{row}:D{row}')
# # #     ws[f'A{row}'] = "Overall Metrics"
# # #     ws[f'A{row}'].font = Font(size=14, bold=True)
# # #     ws[f'A{row}'].fill = PatternFill("solid", fgColor="E7E6E6")
    
# # #     metrics = [
# # #         ("Total Queries", len(query_rows)),
# # #         ("Total LLM Calls", len(log_rows)),
# # #         ("Total Tokens", sum(r.get("total_tokens", 0) for r in query_rows)),
# # #         ("Total Cost ($)", f"${sum(float(r.get('total_cost', 0)) for r in query_rows):.6f}"),
# # #         ("Prompt Tokens", sum(r.get("prompt_tokens", 0) for r in query_rows)),
# # #         ("Completion Tokens", sum(r.get("completion_tokens", 0) for r in query_rows)),
# # #         ("Cached Tokens", sum(r.get("cached_tokens", 0) for r in query_rows)),
# # #     ]
    
# # #     row += 1
# # #     for metric, value in metrics:
# # #         ws[f'A{row}'] = metric
# # #         ws[f'B{row}'] = value
# # #         ws[f'A{row}'].font = Font(bold=True)
# # #         row += 1
    
# # #     # Usage breakdown
# # #     row += 1
# # #     ws.merge_cells(f'A{row}:D{row}')
# # #     ws[f'A{row}'] = "Usage Breakdown"
# # #     ws[f'A{row}'].font = Font(size=14, bold=True)
# # #     ws[f'A{row}'].fill = PatternFill("solid", fgColor="E7E6E6")
    
# # #     row += 1
# # #     ws[f'A{row}'] = "Unique Users"
# # #     ws[f'B{row}'] = len(set(r.get("user_id") for r in query_rows if r.get("user_id")))
# # #     ws[f'A{row}'].font = Font(bold=True)
    
# # #     row += 1
# # #     ws[f'A{row}'] = "Unique Agents"
# # #     ws[f'B{row}'] = len(set(r.get("agent_id") for r in query_rows if r.get("agent_id")))
# # #     ws[f'A{row}'].font = Font(bold=True)
    
# # #     row += 1
# # #     ws[f'A{row}'] = "Unique Models"
# # #     ws[f'B{row}'] = len(set(r.get("model_name") for r in log_rows if r.get("model_name")))
# # #     ws[f'A{row}'].font = Font(bold=True)
    
# # #     _auto_size_columns(ws)


# # # def _build_query_usage_sheet(ws, query_rows: List[Dict]):
# # #     """Build the Query Usage sheet"""
# # #     ws.title = "Query Usage"
    
# # #     headers = [
# # #         "User ID", "Agent ID", "Agent Name", "Session ID", "Query",
# # #         "Total Tokens", "Prompt Tokens", "Completion Tokens", "Cached Tokens",
# # #         "Prompt Cost", "Completion Cost", "Cached Cost", "Total Cost", 
# # #         "LLM Calls", "Created At"
# # #     ]
# # #     _apply_header_style(ws, 1, headers)
    
# # #     for row_idx, row in enumerate(query_rows, start=2):
# # #         ws.cell(row=row_idx, column=1, value=row.get("user_id"))
# # #         ws.cell(row=row_idx, column=2, value=row.get("agent_id"))
# # #         ws.cell(row=row_idx, column=3, value=row.get("agent_name"))
# # #         ws.cell(row=row_idx, column=4, value=row.get("session_id"))
# # #         ws.cell(row=row_idx, column=5, value=row.get("query_text", "")[:100])
# # #         ws.cell(row=row_idx, column=6, value=row.get("total_tokens"))
# # #         ws.cell(row=row_idx, column=7, value=row.get("prompt_tokens"))
# # #         ws.cell(row=row_idx, column=8, value=row.get("completion_tokens"))
# # #         ws.cell(row=row_idx, column=9, value=row.get("cached_tokens"))
# # #         ws.cell(row=row_idx, column=10, value=float(row.get("prompt_cost", 0)))
# # #         ws.cell(row=row_idx, column=11, value=float(row.get("completion_cost", 0)))
# # #         ws.cell(row=row_idx, column=12, value=float(row.get("cached_cost", 0)))
# # #         ws.cell(row=row_idx, column=13, value=float(row.get("total_cost", 0)))
# # #         ws.cell(row=row_idx, column=14, value=row.get("total_llm_calls"))
# # #         ws.cell(row=row_idx, column=15, value=str(row.get("created_at", "")))
        
# # #         # Alternate row coloring
# # #         if row_idx % 2 == 0:
# # #             for col in range(1, len(headers) + 1):
# # #                 ws.cell(row=row_idx, column=col).fill = _ALT_ROW_FILL
    
# # #     _auto_size_columns(ws)


# # # def _build_llm_call_details_sheet(ws, log_rows: List[Dict]):
# # #     """Build the LLM Call Details sheet"""
# # #     ws.title = "LLM Call Details"
    
# # #     headers = [
# # #         "Timestamp", "User ID", "Agent ID", "Agent Name", "Model", "Session ID",
# # #         "Prompt Tokens", "Completion Tokens", "Cached Tokens", "Total Tokens",
# # #         "Prompt Cost", "Completion Cost", "Cached Cost", "Total Cost",
# # #         "Category", "Sub-Category", "Status"
# # #     ]
# # #     _apply_header_style(ws, 1, headers)
    
# # #     for row_idx, row in enumerate(log_rows, start=2):
# # #         ws.cell(row=row_idx, column=1, value=str(row.get("timestamp", "")))
# # #         ws.cell(row=row_idx, column=2, value=row.get("user_id"))
# # #         ws.cell(row=row_idx, column=3, value=row.get("agent_id"))
# # #         ws.cell(row=row_idx, column=4, value=row.get("agent_name"))
# # #         ws.cell(row=row_idx, column=5, value=row.get("model_name"))
# # #         ws.cell(row=row_idx, column=6, value=row.get("session_id"))
# # #         ws.cell(row=row_idx, column=7, value=row.get("prompt_tokens"))
# # #         ws.cell(row=row_idx, column=8, value=row.get("completion_tokens"))
# # #         ws.cell(row=row_idx, column=9, value=row.get("cached_tokens"))
# # #         ws.cell(row=row_idx, column=10, value=row.get("total_tokens"))
# # #         ws.cell(row=row_idx, column=11, value=float(row.get("prompt_cost", 0)))
# # #         ws.cell(row=row_idx, column=12, value=float(row.get("completion_cost", 0)))
# # #         ws.cell(row=row_idx, column=13, value=float(row.get("cached_cost", 0)))
# # #         ws.cell(row=row_idx, column=14, value=float(row.get("total_cost", 0)))
# # #         ws.cell(row=row_idx, column=15, value=row.get("call_category"))
# # #         ws.cell(row=row_idx, column=16, value=row.get("call_sub_category"))
# # #         ws.cell(row=row_idx, column=17, value=row.get("status"))
        
# # #         if row_idx % 2 == 0:
# # #             for col in range(1, len(headers) + 1):
# # #                 ws.cell(row=row_idx, column=col).fill = _ALT_ROW_FILL
    
# # #     _auto_size_columns(ws)


# # # def _build_daily_trend_sheet(ws, query_rows: List[Dict], log_rows: List[Dict]):
# # #     """Build the Daily Trend sheet with charts"""
# # #     ws.title = "Daily Trend"
    
# # #     # Aggregate by date
# # #     daily_data = {}
# # #     for row in query_rows:
# # #         created_at = row.get("created_at")
# # #         if created_at:
# # #             day = str(created_at)[:10]  # YYYY-MM-DD
# # #             if day not in daily_data:
# # #                 daily_data[day] = {"queries": 0, "tokens": 0, "cost": 0}
# # #             daily_data[day]["queries"] += 1
# # #             daily_data[day]["tokens"] += row.get("total_tokens", 0)
# # #             daily_data[day]["cost"] += float(row.get("total_cost", 0))
    
# # #     # Sort by date
# # #     sorted_days = sorted(daily_data.items())
    
# # #     headers = ["Date", "Queries", "Tokens", "Cost ($)"]
# # #     _apply_header_style(ws, 1, headers)
    
# # #     for row_idx, (day, data) in enumerate(sorted_days, start=2):
# # #         ws.cell(row=row_idx, column=1, value=day)
# # #         ws.cell(row=row_idx, column=2, value=data["queries"])
# # #         ws.cell(row=row_idx, column=3, value=data["tokens"])
# # #         ws.cell(row=row_idx, column=4, value=data["cost"])
    
# # #     # Add line chart
# # #     if len(sorted_days) > 1:
# # #         chart = LineChart()
# # #         chart.title = "Daily Cost Trend"
# # #         chart.style = 13
# # #         chart.y_axis.title = "Cost ($)"
# # #         chart.x_axis.title = "Date"
        
# # #         data_ref = Reference(ws, min_col=4, min_row=1, max_row=len(sorted_days) + 1)
# # #         cats_ref = Reference(ws, min_col=1, min_row=2, max_row=len(sorted_days) + 1)
# # #         chart.add_data(data_ref, titles_from_data=True)
# # #         chart.set_categories(cats_ref)
        
# # #         ws.add_chart(chart, "F2")
    
# # #     _auto_size_columns(ws)


# # # def _build_model_breakdown_sheet(ws, query_rows: List[Dict], log_rows: List[Dict]):
# # #     """Build the Model Breakdown sheet"""
# # #     ws.title = "Model Breakdown"
    
# # #     # Aggregate by model
# # #     model_data = {}
# # #     for row in log_rows:
# # #         model = row.get("model_name", "Unknown")
# # #         if model not in model_data:
# # #             model_data[model] = {"calls": 0, "tokens": 0, "cost": 0}
# # #         model_data[model]["calls"] += 1
# # #         model_data[model]["tokens"] += row.get("total_tokens", 0)
# # #         model_data[model]["cost"] += float(row.get("total_cost", 0))
    
# # #     # Sort by cost
# # #     sorted_models = sorted(model_data.items(), key=lambda x: x[1]["cost"], reverse=True)
    
# # #     headers = ["Model", "Calls", "Tokens", "Cost ($)"]
# # #     _apply_header_style(ws, 1, headers)
    
# # #     for row_idx, (model, data) in enumerate(sorted_models, start=2):
# # #         ws.cell(row=row_idx, column=1, value=model)
# # #         ws.cell(row=row_idx, column=2, value=data["calls"])
# # #         ws.cell(row=row_idx, column=3, value=data["tokens"])
# # #         ws.cell(row=row_idx, column=4, value=data["cost"])
        
# # #         if row_idx % 2 == 0:
# # #             for col in range(1, 5):
# # #                 ws.cell(row=row_idx, column=col).fill = _ALT_ROW_FILL
    
# # #     # Add pie chart
# # #     if len(sorted_models) > 0:
# # #         pie = PieChart()
# # #         pie.title = "Cost Distribution by Model"
# # #         labels = Reference(ws, min_col=1, min_row=2, max_row=len(sorted_models) + 1)
# # #         data = Reference(ws, min_col=4, min_row=1, max_row=len(sorted_models) + 1)
# # #         pie.add_data(data, titles_from_data=True)
# # #         pie.set_categories(labels)
# # #         ws.add_chart(pie, "F2")
    
# # #     _auto_size_columns(ws)


# # # def _build_category_breakdown_sheet(ws, query_rows: List[Dict], log_rows: List[Dict]):
# # #     """Build the Category Breakdown sheet"""
# # #     ws.title = "Category Breakdown"
    
# # #     # Aggregate by category
# # #     cat_data = {}
# # #     for row in log_rows:
# # #         cat = row.get("call_category", "other")
# # #         if cat not in cat_data:
# # #             cat_data[cat] = {"calls": 0, "tokens": 0, "cost": 0}
# # #         cat_data[cat]["calls"] += 1
# # #         cat_data[cat]["tokens"] += row.get("total_tokens", 0)
# # #         cat_data[cat]["cost"] += float(row.get("total_cost", 0))
    
# # #     # Sort by cost
# # #     sorted_cats = sorted(cat_data.items(), key=lambda x: x[1]["cost"], reverse=True)
    
# # #     headers = ["Category", "Calls", "Tokens", "Cost ($)"]
# # #     _apply_header_style(ws, 1, headers)
    
# # #     for row_idx, (cat, data) in enumerate(sorted_cats, start=2):
# # #         ws.cell(row=row_idx, column=1, value=cat)
# # #         ws.cell(row=row_idx, column=2, value=data["calls"])
# # #         ws.cell(row=row_idx, column=3, value=data["tokens"])
# # #         ws.cell(row=row_idx, column=4, value=data["cost"])
        
# # #         if row_idx % 2 == 0:
# # #             for col in range(1, 5):
# # #                 ws.cell(row=row_idx, column=col).fill = _ALT_ROW_FILL
    
# # #     # Add bar chart
# # #     if len(sorted_cats) > 0:
# # #         chart = BarChart()
# # #         chart.type = "col"
# # #         chart.title = "Calls by Category"
# # #         chart.y_axis.title = "Number of Calls"
        
# # #         data = Reference(ws, min_col=2, min_row=1, max_row=len(sorted_cats) + 1)
# # #         cats = Reference(ws, min_col=1, min_row=2, max_row=len(sorted_cats) + 1)
# # #         chart.add_data(data, titles_from_data=True)
# # #         chart.set_categories(cats)
        
# # #         ws.add_chart(chart, "F2")
    
# # #     _auto_size_columns(ws)


# # # # ========== MAIN EXPORT ENDPOINT ==========

# # # @router.get(
# # #     "/token-usage-export",
# # #     response_model=TokenUsageReportResponse,
# # #     summary="Export token usage report with summary"
# # # )
# # # async def export_token_usage_report(
# # #     user_id: Optional[str] = Query(None, description="Filter by user ID"),
# # #     agent_id: Optional[str] = Query(None, description="Filter by agent ID"),
# # #     agent_name: Optional[str] = Query(None, description="Filter by agent name"),
# # #     date_from: Optional[date] = Query(None, description="Start date (YYYY-MM-DD)"),
# # #     date_to: Optional[date] = Query(None, description="End date (YYYY-MM-DD)"),
# # #     query_token_usage_repo: QueryTokenUsageRepository = Depends(ServiceProvider.get_query_token_usage_repo),
# # #     token_logs_repo: TokenUsageLogsRepository = Depends(ServiceProvider.get_token_usage_logs_repo),
# # #     current_user: User = Depends(get_current_user),
# # # ):
# # #     """
# # #     Generate comprehensive token usage report with both summary JSON and downloadable Excel file.
    
# # #     **Admin only**
    
# # #     Returns:
# # #     - Summary statistics for immediate UI display
# # #     - Download URL for full Excel report
# # #     """
# # #     if current_user.role not in [UserRole.ADMIN, UserRole.SUPER_ADMIN, "Admin", "SuperAdmin"]:
# # #         raise HTTPException(status_code=403, detail="Admin privileges required")

# # #     try:
# # #         log.info(f"📊 Generating token usage report for {current_user.email}")
        
# # #         # Fetch data
# # #         query_rows = await query_token_usage_repo.get_report_data(
# # #             user_id=user_id, agent_id=agent_id, agent_name=agent_name,
# # #             date_from=date_from, date_to=date_to
# # #         )
# # #         log_rows = await token_logs_repo.get_report_data(
# # #             user_id=user_id, agent_id=agent_id, agent_name=agent_name,
# # #             date_from=date_from, date_to=date_to
# # #         )

# # #         # Calculate summary statistics
# # #         total_queries = len(query_rows)
# # #         total_llm_calls = len(log_rows)
# # #         total_tokens = sum(r.get("total_tokens", 0) for r in query_rows)
# # #         total_cost = sum(float(r.get("total_cost", 0.0)) for r in query_rows)
# # #         prompt_tokens = sum(r.get("prompt_tokens", 0) for r in query_rows)
# # #         completion_tokens = sum(r.get("completion_tokens", 0) for r in query_rows)
# # #         cached_tokens = sum(r.get("cached_tokens", 0) for r in query_rows)
        
# # #         unique_users = len(set(r.get("user_id") for r in query_rows if r.get("user_id")))
# # #         unique_agents = len(set(r.get("agent_id") for r in query_rows if r.get("agent_id")))
# # #         unique_models = len(set(r.get("model_name") for r in log_rows if r.get("model_name")))

# # #         # Top agents by cost
# # #         agent_costs = {}
# # #         for r in query_rows:
# # #             agent = r.get("agent_name", "Unknown")
# # #             agent_costs[agent] = agent_costs.get(agent, 0) + float(r.get("total_cost", 0))
# # #         top_agents = [{"name": k, "cost": round(v, 6)} 
# # #                       for k, v in sorted(agent_costs.items(), key=lambda x: x[1], reverse=True)[:5]]

# # #         # Top models by tokens
# # #         model_tokens = {}
# # #         for r in log_rows:
# # #             model = r.get("model_name", "Unknown")
# # #             model_tokens[model] = model_tokens.get(model, 0) + r.get("total_tokens", 0)
# # #         top_models = [{"name": k, "tokens": v} 
# # #                       for k, v in sorted(model_tokens.items(), key=lambda x: x[1], reverse=True)[:5]]

# # #         # Category breakdown
# # #         cat_costs = {}
# # #         for r in log_rows:
# # #             cat = r.get("call_category", "other")
# # #             cat_costs[cat] = cat_costs.get(cat, 0) + float(r.get("total_cost", 0) or 0)
# # #         category_breakdown = [{"category": k, "cost": round(v, 6)} 
# # #                               for k, v in sorted(cat_costs.items(), key=lambda x: x[1], reverse=True)]

# # #         # Build Excel workbook
# # #         wb = Workbook()
# # #         wb.remove(wb.active)
# # #         _build_summary_sheet(wb.create_sheet("Summary"), query_rows, log_rows, date_from, date_to)
# # #         _build_query_usage_sheet(wb.create_sheet("Query Usage"), query_rows)
# # #         _build_llm_call_details_sheet(wb.create_sheet("LLM Call Details"), log_rows)
# # #         _build_daily_trend_sheet(wb.create_sheet("Daily Trend"), query_rows, log_rows)
# # #         _build_model_breakdown_sheet(wb.create_sheet("Model Breakdown"), query_rows, log_rows)
# # #         _build_category_breakdown_sheet(wb.create_sheet("Category Breakdown"), query_rows, log_rows)

# # #         # Save file to disk
# # #         reports_dir = Path("reports")
# # #         reports_dir.mkdir(exist_ok=True)
# # #         timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
# # #         filename = f"token_usage_report_{timestamp}.xlsx"
# # #         file_path = reports_dir / filename
# # #         wb.save(file_path)

# # #         log.info(f"✅ Token usage report generated: {filename}")

# # #         # Return JSON response with summary + download URL
# # #         summary = TokenUsageSummary(
# # #             total_queries=total_queries,
# # #             total_llm_calls=total_llm_calls,
# # #             total_tokens=total_tokens,
# # #             total_cost=round(total_cost, 6),
# # #             prompt_tokens=prompt_tokens,
# # #             completion_tokens=completion_tokens,
# # #             cached_tokens=cached_tokens,
# # #             unique_users=unique_users,
# # #             unique_agents=unique_agents,
# # #             unique_models=unique_models,
# # #             date_range={
# # #                 "from": date_from.isoformat() if date_from else None,
# # #                 "to": date_to.isoformat() if date_to else None
# # #             },
# # #             top_agents=top_agents,
# # #             top_models=top_models,
# # #             category_breakdown=category_breakdown
# # #         )

# # #         return TokenUsageReportResponse(
# # #             summary=summary,
# # #             file_download_url=f"/reports/token-usage-download/{filename}",
# # #             filename=filename,
# # #             generated_at=datetime.now().isoformat()
# # #         )

# # #     except Exception as e:
# # #         log.error(f"❌ Error generating token usage report: {e}", exc_info=True)
# # #         raise HTTPException(status_code=500, detail=f"Failed to generate report: {str(e)}")


# # # # ========== DOWNLOAD ENDPOINT ==========

# # # @router.get(
# # #     "/token-usage-download/{filename}",
# # #     summary="Download token usage report file"
# # # )
# # # async def download_token_usage_report(
# # #     filename: str,
# # #     current_user: User = Depends(get_current_user)
# # # ):
# # #     """
# # #     Download a previously generated token usage report Excel file.
    
# # #     **Admin only**
# # #     """
# # #     if current_user.role not in [UserRole.ADMIN, UserRole.SUPER_ADMIN, "Admin", "SuperAdmin"]:
# # #         raise HTTPException(status_code=403, detail="Admin privileges required")

# # #     try:
# # #         # Security: Prevent path traversal
# # #         safe_filename = os.path.basename(filename)
# # #         if safe_filename != filename or '..' in filename:
# # #             raise HTTPException(status_code=400, detail="Invalid filename")

# # #         file_path = Path("reports") / safe_filename
# # #         if not file_path.exists():
# # #             raise HTTPException(status_code=404, detail="Report file not found")

# # #         log.info(f"📥 Token usage report downloaded: {filename} by {current_user.email}")

# # #         return FileResponse(
# # #             path=str(file_path),
# # #             filename=filename,
# # #             media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
# # #             headers={"Content-Disposition": f'attachment; filename="{filename}"'}
# # #         )

# # #     except HTTPException:
# # #         raise
# # #     except Exception as e:
# # #         log.error(f"❌ Error downloading report: {e}", exc_info=True)
# # #         raise HTTPException(status_code=500, detail=f"Failed to download report: {str(e)}")

# # # © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.

# # """
# # Token Usage Report Endpoints - OPTION 3: JSON with Base64 File

# # Generates comprehensive token usage and cost reports with:
# # - Summary JSON for immediate UI rendering
# # - Base64-encoded Excel file embedded in response
# # - Single endpoint returns both summary and downloadable file
# # """

# # import os
# # import base64
# # from pathlib import Path
# # from datetime import datetime, date
# # from typing import List, Dict, Optional, Any
# # from io import BytesIO

# # from fastapi import APIRouter, Depends, HTTPException, Query
# # from pydantic import BaseModel, Field

# # from openpyxl import Workbook
# # from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
# # from openpyxl.chart import LineChart, BarChart, PieChart, Reference
# # from openpyxl.utils import get_column_letter

# # from src.database.repositories import QueryTokenUsageRepository, TokenUsageLogsRepository
# # from src.api.dependencies import ServiceProvider
# # from src.auth.dependencies import get_current_user
# # from src.auth.models import User, UserRole
# # from telemetry_wrapper import logger as log

# # router = APIRouter(prefix="/reports", tags=["Reports - Token Usage"])

# # # ========== EXCEL STYLING CONSTANTS ==========
# # _TITLE_FONT = Font(name="Calibri", size=16, bold=True, color="FFFFFF")
# # _HEADER_FONT = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
# # _SUMMARY_FILL = PatternFill("solid", fgColor="2E75B6")
# # _HEADER_FILL = PatternFill("solid", fgColor="4472C4")
# # _ALT_ROW_FILL = PatternFill("solid", fgColor="D9E1F2")
# # _THIN_BORDER = Border(
# #     left=Side(style="thin"), right=Side(style="thin"),
# #     top=Side(style="thin"), bottom=Side(style="thin")
# # )
# # _CENTER_ALIGN = Alignment(horizontal="center", vertical="center", wrap_text=True)
# # _LEFT_ALIGN = Alignment(horizontal="left", vertical="center", wrap_text=False)


# # # ========== HELPER FUNCTIONS ==========

# # def _apply_header_style(ws, row_num: int, headers: List[str]):
# #     """Apply header styling to a row"""
# #     for col_idx, header in enumerate(headers, start=1):
# #         cell = ws.cell(row=row_num, column=col_idx, value=header)
# #         cell.font = _HEADER_FONT
# #         cell.fill = _HEADER_FILL
# #         cell.alignment = _CENTER_ALIGN
# #         cell.border = _THIN_BORDER


# # def _auto_size_columns(ws, min_width=10, max_width=50):
# #     """Auto-size columns based on content"""
# #     for column in ws.columns:
# #         max_length = 0
# #         column_letter = get_column_letter(column[0].column)
# #         for cell in column:
# #             try:
# #                 if cell.value:
# #                     max_length = max(max_length, len(str(cell.value)))
# #             except:
# #                 pass
# #         adjusted_width = min(max(max_length + 2, min_width), max_width)
# #         ws.column_dimensions[column_letter].width = adjusted_width


# # def _build_summary_sheet(ws, query_rows: List[Dict], log_rows: List[Dict], date_from, date_to):
# #     """Build the Summary sheet"""
# #     ws.title = "Summary"
    
# #     # Title
# #     ws.merge_cells('A1:D1')
# #     title_cell = ws['A1']
# #     title_cell.value = "Token Usage Report - Summary"
# #     title_cell.font = _TITLE_FONT
# #     title_cell.fill = _SUMMARY_FILL
# #     title_cell.alignment = _CENTER_ALIGN
    
# #     # Date range
# #     ws['A2'] = "Report Period:"
# #     ws['B2'] = f"{date_from or 'All'} to {date_to or 'All'}"
# #     ws['A2'].font = Font(bold=True)
    
# #     # Overall metrics
# #     row = 4
# #     ws.merge_cells(f'A{row}:D{row}')
# #     ws[f'A{row}'] = "Overall Metrics"
# #     ws[f'A{row}'].font = Font(size=14, bold=True)
# #     ws[f'A{row}'].fill = PatternFill("solid", fgColor="E7E6E6")
    
# #     metrics = [
# #         ("Total Queries", len(query_rows)),
# #         ("Total LLM Calls", len(log_rows)),
# #         ("Total Tokens", sum(r.get("total_tokens", 0) for r in query_rows)),
# #         ("Total Cost ($)", f"${sum(float(r.get('total_cost', 0)) for r in query_rows):.6f}"),
# #         ("Prompt Tokens", sum(r.get("prompt_tokens", 0) for r in query_rows)),
# #         ("Completion Tokens", sum(r.get("completion_tokens", 0) for r in query_rows)),
# #         ("Cached Tokens", sum(r.get("cached_tokens", 0) for r in query_rows)),
# #     ]
    
# #     row += 1
# #     for metric, value in metrics:
# #         ws[f'A{row}'] = metric
# #         ws[f'B{row}'] = value
# #         ws[f'A{row}'].font = Font(bold=True)
# #         row += 1
    
# #     # Usage breakdown
# #     row += 1
# #     ws.merge_cells(f'A{row}:D{row}')
# #     ws[f'A{row}'] = "Usage Breakdown"
# #     ws[f'A{row}'].font = Font(size=14, bold=True)
# #     ws[f'A{row}'].fill = PatternFill("solid", fgColor="E7E6E6")
    
# #     row += 1
# #     ws[f'A{row}'] = "Unique Users"
# #     ws[f'B{row}'] = len(set(r.get("user_id") for r in query_rows if r.get("user_id")))
# #     ws[f'A{row}'].font = Font(bold=True)
    
# #     row += 1
# #     ws[f'A{row}'] = "Unique Agents"
# #     ws[f'B{row}'] = len(set(r.get("agent_id") for r in query_rows if r.get("agent_id")))
# #     ws[f'A{row}'].font = Font(bold=True)
    
# #     row += 1
# #     ws[f'A{row}'] = "Unique Models"
# #     ws[f'B{row}'] = len(set(r.get("model_name") for r in log_rows if r.get("model_name")))
# #     ws[f'A{row}'].font = Font(bold=True)
    
# #     _auto_size_columns(ws)


# # def _build_query_usage_sheet(ws, query_rows: List[Dict]):
# #     """Build the Query Usage sheet"""
# #     ws.title = "Query Usage"
    
# #     headers = [
# #         "User ID", "Agent ID", "Agent Name", "Session ID", "Query",
# #         "Total Tokens", "Prompt Tokens", "Completion Tokens", "Cached Tokens",
# #         "Prompt Cost", "Completion Cost", "Cached Cost", "Total Cost", 
# #         "LLM Calls", "Created At"
# #     ]
# #     _apply_header_style(ws, 1, headers)
    
# #     for row_idx, row in enumerate(query_rows, start=2):
# #         ws.cell(row=row_idx, column=1, value=row.get("user_id"))
# #         ws.cell(row=row_idx, column=2, value=row.get("agent_id"))
# #         ws.cell(row=row_idx, column=3, value=row.get("agent_name"))
# #         ws.cell(row=row_idx, column=4, value=row.get("session_id"))
# #         ws.cell(row=row_idx, column=5, value=row.get("query_text", "")[:100])
# #         ws.cell(row=row_idx, column=6, value=row.get("total_tokens"))
# #         ws.cell(row=row_idx, column=7, value=row.get("prompt_tokens"))
# #         ws.cell(row=row_idx, column=8, value=row.get("completion_tokens"))
# #         ws.cell(row=row_idx, column=9, value=row.get("cached_tokens"))
# #         ws.cell(row=row_idx, column=10, value=float(row.get("prompt_cost", 0)))
# #         ws.cell(row=row_idx, column=11, value=float(row.get("completion_cost", 0)))
# #         ws.cell(row=row_idx, column=12, value=float(row.get("cached_cost", 0)))
# #         ws.cell(row=row_idx, column=13, value=float(row.get("total_cost", 0)))
# #         ws.cell(row=row_idx, column=14, value=row.get("total_llm_calls"))
# #         ws.cell(row=row_idx, column=15, value=str(row.get("created_at", "")))
        
# #         # Alternate row coloring
# #         if row_idx % 2 == 0:
# #             for col in range(1, len(headers) + 1):
# #                 ws.cell(row=row_idx, column=col).fill = _ALT_ROW_FILL
    
# #     _auto_size_columns(ws)


# # def _build_llm_call_details_sheet(ws, log_rows: List[Dict]):
# #     """Build the LLM Call Details sheet"""
# #     ws.title = "LLM Call Details"
    
# #     headers = [
# #         "Timestamp", "User ID", "Agent ID", "Agent Name", "Model", "Session ID",
# #         "Prompt Tokens", "Completion Tokens", "Cached Tokens", "Total Tokens",
# #         "Prompt Cost", "Completion Cost", "Cached Cost", "Total Cost",
# #         "Category", "Sub-Category", "Status"
# #     ]
# #     _apply_header_style(ws, 1, headers)
    
# #     for row_idx, row in enumerate(log_rows, start=2):
# #         ws.cell(row=row_idx, column=1, value=str(row.get("timestamp", "")))
# #         ws.cell(row=row_idx, column=2, value=row.get("user_id"))
# #         ws.cell(row=row_idx, column=3, value=row.get("agent_id"))
# #         ws.cell(row=row_idx, column=4, value=row.get("agent_name"))
# #         ws.cell(row=row_idx, column=5, value=row.get("model_name"))
# #         ws.cell(row=row_idx, column=6, value=row.get("session_id"))
# #         ws.cell(row=row_idx, column=7, value=row.get("prompt_tokens"))
# #         ws.cell(row=row_idx, column=8, value=row.get("completion_tokens"))
# #         ws.cell(row=row_idx, column=9, value=row.get("cached_tokens"))
# #         ws.cell(row=row_idx, column=10, value=row.get("total_tokens"))
# #         ws.cell(row=row_idx, column=11, value=float(row.get("prompt_cost", 0)))
# #         ws.cell(row=row_idx, column=12, value=float(row.get("completion_cost", 0)))
# #         ws.cell(row=row_idx, column=13, value=float(row.get("cached_cost", 0)))
# #         ws.cell(row=row_idx, column=14, value=float(row.get("total_cost", 0)))
# #         ws.cell(row=row_idx, column=15, value=row.get("call_category"))
# #         ws.cell(row=row_idx, column=16, value=row.get("call_sub_category"))
# #         ws.cell(row=row_idx, column=17, value=row.get("status"))
        
# #         if row_idx % 2 == 0:
# #             for col in range(1, len(headers) + 1):
# #                 ws.cell(row=row_idx, column=col).fill = _ALT_ROW_FILL
    
# #     _auto_size_columns(ws)


# # def _build_daily_trend_sheet(ws, query_rows: List[Dict], log_rows: List[Dict]):
# #     """Build the Daily Trend sheet with charts"""
# #     ws.title = "Daily Trend"
    
# #     # Aggregate by date
# #     daily_data = {}
# #     for row in query_rows:
# #         created_at = row.get("created_at")
# #         if created_at:
# #             day = str(created_at)[:10]  # YYYY-MM-DD
# #             if day not in daily_data:
# #                 daily_data[day] = {"queries": 0, "tokens": 0, "cost": 0}
# #             daily_data[day]["queries"] += 1
# #             daily_data[day]["tokens"] += row.get("total_tokens", 0)
# #             daily_data[day]["cost"] += float(row.get("total_cost", 0))
    
# #     # Sort by date
# #     sorted_days = sorted(daily_data.items())
    
# #     headers = ["Date", "Queries", "Tokens", "Cost ($)"]
# #     _apply_header_style(ws, 1, headers)
    
# #     for row_idx, (day, data) in enumerate(sorted_days, start=2):
# #         ws.cell(row=row_idx, column=1, value=day)
# #         ws.cell(row=row_idx, column=2, value=data["queries"])
# #         ws.cell(row=row_idx, column=3, value=data["tokens"])
# #         ws.cell(row=row_idx, column=4, value=data["cost"])
    
# #     # Add line chart
# #     if len(sorted_days) > 1:
# #         chart = LineChart()
# #         chart.title = "Daily Cost Trend"
# #         chart.style = 13
# #         chart.y_axis.title = "Cost ($)"
# #         chart.x_axis.title = "Date"
        
# #         data_ref = Reference(ws, min_col=4, min_row=1, max_row=len(sorted_days) + 1)
# #         cats_ref = Reference(ws, min_col=1, min_row=2, max_row=len(sorted_days) + 1)
# #         chart.add_data(data_ref, titles_from_data=True)
# #         chart.set_categories(cats_ref)
        
# #         ws.add_chart(chart, "F2")
    
# #     _auto_size_columns(ws)


# # def _build_model_breakdown_sheet(ws, query_rows: List[Dict], log_rows: List[Dict]):
# #     """Build the Model Breakdown sheet"""
# #     ws.title = "Model Breakdown"
    
# #     # Aggregate by model
# #     model_data = {}
# #     for row in log_rows:
# #         model = row.get("model_name", "Unknown")
# #         if model not in model_data:
# #             model_data[model] = {"calls": 0, "tokens": 0, "cost": 0}
# #         model_data[model]["calls"] += 1
# #         model_data[model]["tokens"] += row.get("total_tokens", 0)
# #         model_data[model]["cost"] += float(row.get("total_cost", 0))
    
# #     # Sort by cost
# #     sorted_models = sorted(model_data.items(), key=lambda x: x[1]["cost"], reverse=True)
    
# #     headers = ["Model", "Calls", "Tokens", "Cost ($)"]
# #     _apply_header_style(ws, 1, headers)
    
# #     for row_idx, (model, data) in enumerate(sorted_models, start=2):
# #         ws.cell(row=row_idx, column=1, value=model)
# #         ws.cell(row=row_idx, column=2, value=data["calls"])
# #         ws.cell(row=row_idx, column=3, value=data["tokens"])
# #         ws.cell(row=row_idx, column=4, value=data["cost"])
        
# #         if row_idx % 2 == 0:
# #             for col in range(1, 5):
# #                 ws.cell(row=row_idx, column=col).fill = _ALT_ROW_FILL
    
# #     # Add pie chart
# #     if len(sorted_models) > 0:
# #         pie = PieChart()
# #         pie.title = "Cost Distribution by Model"
# #         labels = Reference(ws, min_col=1, min_row=2, max_row=len(sorted_models) + 1)
# #         data = Reference(ws, min_col=4, min_row=1, max_row=len(sorted_models) + 1)
# #         pie.add_data(data, titles_from_data=True)
# #         pie.set_categories(labels)
# #         ws.add_chart(pie, "F2")
    
# #     _auto_size_columns(ws)


# # def _build_category_breakdown_sheet(ws, query_rows: List[Dict], log_rows: List[Dict]):
# #     """Build the Category Breakdown sheet"""
# #     ws.title = "Category Breakdown"
    
# #     # Aggregate by category
# #     cat_data = {}
# #     for row in log_rows:
# #         cat = row.get("call_category", "other")
# #         if cat not in cat_data:
# #             cat_data[cat] = {"calls": 0, "tokens": 0, "cost": 0}
# #         cat_data[cat]["calls"] += 1
# #         cat_data[cat]["tokens"] += row.get("total_tokens", 0)
# #         cat_data[cat]["cost"] += float(row.get("total_cost", 0))
    
# #     # Sort by cost
# #     sorted_cats = sorted(cat_data.items(), key=lambda x: x[1]["cost"], reverse=True)
    
# #     headers = ["Category", "Calls", "Tokens", "Cost ($)"]
# #     _apply_header_style(ws, 1, headers)
    
# #     for row_idx, (cat, data) in enumerate(sorted_cats, start=2):
# #         ws.cell(row=row_idx, column=1, value=cat)
# #         ws.cell(row=row_idx, column=2, value=data["calls"])
# #         ws.cell(row=row_idx, column=3, value=data["tokens"])
# #         ws.cell(row=row_idx, column=4, value=data["cost"])
        
# #         if row_idx % 2 == 0:
# #             for col in range(1, 5):
# #                 ws.cell(row=row_idx, column=col).fill = _ALT_ROW_FILL
    
# #     # Add bar chart
# #     if len(sorted_cats) > 0:
# #         chart = BarChart()
# #         chart.type = "col"
# #         chart.title = "Calls by Category"
# #         chart.y_axis.title = "Number of Calls"
        
# #         data = Reference(ws, min_col=2, min_row=1, max_row=len(sorted_cats) + 1)
# #         cats = Reference(ws, min_col=1, min_row=2, max_row=len(sorted_cats) + 1)
# #         chart.add_data(data, titles_from_data=True)
# #         chart.set_categories(cats)
        
# #         ws.add_chart(chart, "F2")
    
# #     _auto_size_columns(ws)


# # # ========== MAIN EXPORT ENDPOINT ==========

# # @router.get(
# #     "/token-usage-export",
# #     summary="Export token usage report (JSON with embedded file)"
# # )
# # async def export_token_usage_report(
# #     user_id: Optional[str] = Query(None, description="Filter by user ID"),
# #     agent_id: Optional[str] = Query(None, description="Filter by agent ID"),
# #     agent_name: Optional[str] = Query(None, description="Filter by agent name"),
# #     date_from: Optional[date] = Query(None, description="Start date (YYYY-MM-DD)"),
# #     date_to: Optional[date] = Query(None, description="End date (YYYY-MM-DD)"),
# #     query_token_usage_repo: QueryTokenUsageRepository = Depends(ServiceProvider.get_query_token_usage_repo),
# #     token_logs_repo: TokenUsageLogsRepository = Depends(ServiceProvider.get_token_usage_logs_repo),
# #     current_user: User = Depends(get_current_user),
# # ):
# #     """
# #     Generate comprehensive token usage report.
    
# #     **Admin only**
    
# #     Returns JSON with:
# #     - `summary`: Statistics for immediate UI display
# #     - `file.content`: Base64-encoded Excel file
# #     - `file.filename`: Suggested filename
# #     - `file.mime_type`: MIME type for download
# #     - `generated_at`: Timestamp
    
# #     Example response:
# #     ```json
# #     {
# #       "summary": {
# #         "total_queries": 150,
# #         "total_cost": 2.345,
# #         "top_agents": [...],
# #         ...
# #       },
# #       "file": {
# #         "filename": "token_usage_report_20260422_143022.xlsx",
# #         "content": "UEsDBBQABgAIAAAAIQ...",
# #         "mime_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
# #       },
# #       "generated_at": "2026-04-22T14:30:22"
# #     }
# #     ```
    
# #     Frontend can decode base64 and trigger download:
# #     ```javascript
# #     const blob = new Blob([Uint8Array.from(atob(data.file.content), c => c.charCodeAt(0))], 
# #                           {type: data.file.mime_type});
# #     const url = URL.createObjectURL(blob);
# #     const a = document.createElement('a');
# #     a.href = url;
# #     a.download = data.file.filename;
# #     a.click();
# #     ```
# #     """
# #     if current_user.role not in [UserRole.ADMIN, UserRole.SUPER_ADMIN, "Admin", "SuperAdmin"]:
# #         raise HTTPException(status_code=403, detail="Admin privileges required")

# #     try:
# #         log.info(f"📊 Generating token usage report for {current_user.email}")
        
# #         # Fetch data from repositories
# #         query_rows = await query_token_usage_repo.get_report_data(
# #             user_id=user_id, agent_id=agent_id, agent_name=agent_name,
# #             date_from=date_from, date_to=date_to
# #         )
# #         log_rows = await token_logs_repo.get_report_data(
# #             user_id=user_id, agent_id=agent_id, agent_name=agent_name,
# #             date_from=date_from, date_to=date_to
# #         )

# #         # Calculate summary statistics
# #         total_queries = len(query_rows)
# #         total_llm_calls = len(log_rows)
# #         total_tokens = sum(r.get("total_tokens", 0) for r in query_rows)
# #         total_cost = sum(float(r.get("total_cost", 0.0)) for r in query_rows)
# #         prompt_tokens = sum(r.get("prompt_tokens", 0) for r in query_rows)
# #         completion_tokens = sum(r.get("completion_tokens", 0) for r in query_rows)
# #         cached_tokens = sum(r.get("cached_tokens", 0) for r in query_rows)
        
# #         unique_users = len(set(r.get("user_id") for r in query_rows if r.get("user_id")))
# #         unique_agents = len(set(r.get("agent_id") for r in query_rows if r.get("agent_id")))
# #         unique_models = len(set(r.get("model_name") for r in log_rows if r.get("model_name")))

# #         # Top agents by cost
# #         agent_costs = {}
# #         for r in query_rows:
# #             agent = r.get("agent_name", "Unknown")
# #             agent_costs[agent] = agent_costs.get(agent, 0) + float(r.get("total_cost", 0))
# #         top_agents = [{"name": k, "cost": round(v, 6)} 
# #                       for k, v in sorted(agent_costs.items(), key=lambda x: x[1], reverse=True)[:5]]

# #         # Top models by tokens
# #         model_tokens = {}
# #         for r in log_rows:
# #             model = r.get("model_name", "Unknown")
# #             model_tokens[model] = model_tokens.get(model, 0) + r.get("total_tokens", 0)
# #         top_models = [{"name": k, "tokens": v} 
# #                       for k, v in sorted(model_tokens.items(), key=lambda x: x[1], reverse=True)[:5]]

# #         # Category breakdown
# #         cat_costs = {}
# #         for r in log_rows:
# #             cat = r.get("call_category", "other")
# #             cat_costs[cat] = cat_costs.get(cat, 0) + float(r.get("total_cost", 0) or 0)
# #         category_breakdown = [{"category": k, "cost": round(v, 6)} 
# #                               for k, v in sorted(cat_costs.items(), key=lambda x: x[1], reverse=True)]

# #         # Build summary object
# #         summary = {
# #             "total_queries": total_queries,
# #             "total_llm_calls": total_llm_calls,
# #             "total_tokens": total_tokens,
# #             "total_cost": round(total_cost, 6),
# #             "prompt_tokens": prompt_tokens,
# #             "completion_tokens": completion_tokens,
# #             "cached_tokens": cached_tokens,
# #             "unique_users": unique_users,
# #             "unique_agents": unique_agents,
# #             "unique_models": unique_models,
# #             "date_range": {
# #                 "from": date_from.isoformat() if date_from else None,
# #                 "to": date_to.isoformat() if date_to else None
# #             },
# #             "top_agents": top_agents,
# #             "top_models": top_models,
# #             "category_breakdown": category_breakdown
# #         }

# #         # Build Excel workbook with all sheets
# #         wb = Workbook()
# #         wb.remove(wb.active)  # Remove default sheet
        
# #         _build_summary_sheet(wb.create_sheet("Summary"), query_rows, log_rows, date_from, date_to)
# #         _build_query_usage_sheet(wb.create_sheet("Query Usage"), query_rows)
# #         _build_llm_call_details_sheet(wb.create_sheet("LLM Call Details"), log_rows)
# #         _build_daily_trend_sheet(wb.create_sheet("Daily Trend"), query_rows, log_rows)
# #         _build_model_breakdown_sheet(wb.create_sheet("Model Breakdown"), query_rows, log_rows)
# #         _build_category_breakdown_sheet(wb.create_sheet("Category Breakdown"), query_rows, log_rows)

# #         # Save workbook to BytesIO buffer
# #         excel_buffer = BytesIO()
# #         wb.save(excel_buffer)
# #         excel_buffer.seek(0)
        
# #         # Encode Excel file to base64
# #         file_base64 = base64.b64encode(excel_buffer.read()).decode('utf-8')

# #         # Generate filename with timestamp
# #         timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
# #         filename = f"token_usage_report_{timestamp}.xlsx"

# #         log.info(f"✅ Token usage report generated: {filename} ({len(file_base64)} chars base64)")

# #         # Return JSON response with summary and embedded file
# #         return {
# #             "summary": summary,
# #             "file": {
# #                 "filename": filename,
# #                 "content": file_base64,
# #                 "mime_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
# #             },
# #             "generated_at": datetime.now().isoformat()
# #         }

# #     except Exception as e:
# #         log.error(f"❌ Error generating token usage report: {e}", exc_info=True)
# #         raise HTTPException(status_code=500, detail=f"Failed to generate report: {str(e)}")


# # © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.

# """
# Token Usage Report Endpoints - Simplified Summary

# Generates token usage reports with:
# - Minimal summary (11 key metrics only)
# - Base64-encoded Excel file for download
# """

# import os
# import base64
# from pathlib import Path
# from datetime import datetime, date
# from typing import List, Dict, Optional, Any
# from io import BytesIO

# from fastapi import APIRouter, Depends, HTTPException, Query
# from pydantic import BaseModel, Field

# from openpyxl import Workbook
# from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
# from openpyxl.chart import LineChart, BarChart, PieChart, Reference
# from openpyxl.utils import get_column_letter

# from src.database.repositories import QueryTokenUsageRepository, TokenUsageLogsRepository
# from src.api.dependencies import ServiceProvider
# from src.auth.dependencies import get_current_user
# from src.auth.models import User, UserRole
# from telemetry_wrapper import logger as log

# router = APIRouter(prefix="/reports", tags=["Reports - Token Usage"])

# # ========== EXCEL STYLING CONSTANTS ==========
# _TITLE_FONT = Font(name="Calibri", size=16, bold=True, color="FFFFFF")
# _HEADER_FONT = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
# _SUMMARY_FILL = PatternFill("solid", fgColor="2E75B6")
# _HEADER_FILL = PatternFill("solid", fgColor="4472C4")
# _ALT_ROW_FILL = PatternFill("solid", fgColor="D9E1F2")
# _THIN_BORDER = Border(
#     left=Side(style="thin"), right=Side(style="thin"),
#     top=Side(style="thin"), bottom=Side(style="thin")
# )
# _CENTER_ALIGN = Alignment(horizontal="center", vertical="center", wrap_text=True)
# _LEFT_ALIGN = Alignment(horizontal="left", vertical="center", wrap_text=False)


# # ========== RESPONSE MODEL ==========

# class SimplifiedSummary(BaseModel):
#     """Simplified summary with only essential metrics"""
#     total_queries: int
#     query_related_llm_calls: int
#     total_llm_calls: int
#     total_prompt_tokens: int
#     total_completion_tokens: int
#     total_cached_tokens: int
#     total_tokens: int
#     total_cost_usd: str  # Formatted as string with $ sign
#     unique_agents: int
#     unique_users: int


# class TokenUsageReportResponse(BaseModel):
#     """Response with summary and downloadable file"""
#     summary: SimplifiedSummary
#     file: Dict[str, str]  # {filename, content, mime_type}
#     generated_at: str


# # ========== HELPER FUNCTIONS ==========

# def _apply_header_style(ws, row_num: int, headers: List[str]):
#     """Apply header styling to a row"""
#     for col_idx, header in enumerate(headers, start=1):
#         cell = ws.cell(row=row_num, column=col_idx, value=header)
#         cell.font = _HEADER_FONT
#         cell.fill = _HEADER_FILL
#         cell.alignment = _CENTER_ALIGN
#         cell.border = _THIN_BORDER


# def _auto_size_columns(ws, min_width=10, max_width=50):
#     """Auto-size columns based on content"""
#     for column in ws.columns:
#         max_length = 0
#         column_letter = get_column_letter(column[0].column)
#         for cell in column:
#             try:
#                 if cell.value:
#                     max_length = max(max_length, len(str(cell.value)))
#             except:
#                 pass
#         adjusted_width = min(max(max_length + 2, min_width), max_width)
#         ws.column_dimensions[column_letter].width = adjusted_width


# def _build_summary_sheet(ws, query_rows: List[Dict], log_rows: List[Dict], date_from, date_to):
#     """Build the Summary sheet"""
#     ws.title = "Summary"
    
#     # Title
#     ws.merge_cells('A1:D1')
#     title_cell = ws['A1']
#     title_cell.value = "Token Usage Report - Summary"
#     title_cell.font = _TITLE_FONT
#     title_cell.fill = _SUMMARY_FILL
#     title_cell.alignment = _CENTER_ALIGN
    
#     # Date range
#     ws['A2'] = "Report Period:"
#     ws['B2'] = f"{date_from or 'All'} to {date_to or 'All'}"
#     ws['A2'].font = Font(bold=True)
    
#     # Calculate metrics
#     total_queries = len(query_rows)
#     query_llm_calls = sum(r.get("total_llm_calls", 0) for r in query_rows)
#     total_llm_calls = len(log_rows)
    
#     # Overall metrics (matching your simplified list)
#     row = 4
#     ws.merge_cells(f'A{row}:D{row}')
#     ws[f'A{row}'] = "Overall Metrics"
#     ws[f'A{row}'].font = Font(size=14, bold=True)
#     ws[f'A{row}'].fill = PatternFill("solid", fgColor="E7E6E6")
    
#     metrics = [
#         ("Total Queries", total_queries),
#         ("Query-Related LLM Calls", query_llm_calls),
#         ("Total LLM Calls", total_llm_calls),
#         ("Total Prompt Tokens", sum(r.get("prompt_tokens", 0) for r in query_rows)),
#         ("Total Completion Tokens", sum(r.get("completion_tokens", 0) for r in query_rows)),
#         ("Total Cached Tokens", sum(r.get("cached_tokens", 0) for r in query_rows)),
#         ("Total Tokens", sum(r.get("total_tokens", 0) for r in query_rows)),
#         ("Total Cost (USD)", f"${sum(float(r.get('total_cost', 0)) for r in query_rows):.6f}"),
#         ("Unique Agents", len(set(r.get("agent_id") for r in query_rows if r.get("agent_id")))),
#         ("Unique Users", len(set(r.get("user_id") for r in query_rows if r.get("user_id")))),
#     ]
    
#     row += 1
#     for metric, value in metrics:
#         ws[f'A{row}'] = metric
#         ws[f'B{row}'] = value
#         ws[f'A{row}'].font = Font(bold=True)
#         row += 1
    
#     _auto_size_columns(ws)


# def _build_query_usage_sheet(ws, query_rows: List[Dict]):
#     """Build the Query Usage sheet"""
#     ws.title = "Query Usage"
    
#     headers = [
#         "User ID", "Agent ID", "Agent Name", "Session ID", "Query",
#         "Total Tokens", "Prompt Tokens", "Completion Tokens", "Cached Tokens",
#         "Prompt Cost", "Completion Cost", "Cached Cost", "Total Cost", 
#         "LLM Calls", "Created At"
#     ]
#     _apply_header_style(ws, 1, headers)
    
#     for row_idx, row in enumerate(query_rows, start=2):
#         ws.cell(row=row_idx, column=1, value=row.get("user_id"))
#         ws.cell(row=row_idx, column=2, value=row.get("agent_id"))
#         ws.cell(row=row_idx, column=3, value=row.get("agent_name"))
#         ws.cell(row=row_idx, column=4, value=row.get("session_id"))
#         ws.cell(row=row_idx, column=5, value=row.get("query_text", "")[:100])
#         ws.cell(row=row_idx, column=6, value=row.get("total_tokens"))
#         ws.cell(row=row_idx, column=7, value=row.get("prompt_tokens"))
#         ws.cell(row=row_idx, column=8, value=row.get("completion_tokens"))
#         ws.cell(row=row_idx, column=9, value=row.get("cached_tokens"))
#         ws.cell(row=row_idx, column=10, value=float(row.get("prompt_cost", 0)))
#         ws.cell(row=row_idx, column=11, value=float(row.get("completion_cost", 0)))
#         ws.cell(row=row_idx, column=12, value=float(row.get("cached_cost", 0)))
#         ws.cell(row=row_idx, column=13, value=float(row.get("total_cost", 0)))
#         ws.cell(row=row_idx, column=14, value=row.get("total_llm_calls"))
#         ws.cell(row=row_idx, column=15, value=str(row.get("created_at", "")))
        
#         if row_idx % 2 == 0:
#             for col in range(1, len(headers) + 1):
#                 ws.cell(row=row_idx, column=col).fill = _ALT_ROW_FILL
    
#     _auto_size_columns(ws)


# def _build_llm_call_details_sheet(ws, log_rows: List[Dict]):
#     """Build the LLM Call Details sheet"""
#     ws.title = "LLM Call Details"
    
#     headers = [
#         "Timestamp", "User ID", "Agent ID", "Agent Name", "Model", "Session ID",
#         "Prompt Tokens", "Completion Tokens", "Cached Tokens", "Total Tokens",
#         "Prompt Cost", "Completion Cost", "Cached Cost", "Total Cost",
#         "Category", "Sub-Category", "Status"
#     ]
#     _apply_header_style(ws, 1, headers)
    
#     for row_idx, row in enumerate(log_rows, start=2):
#         ws.cell(row=row_idx, column=1, value=str(row.get("timestamp", "")))
#         ws.cell(row=row_idx, column=2, value=row.get("user_id"))
#         ws.cell(row=row_idx, column=3, value=row.get("agent_id"))
#         ws.cell(row=row_idx, column=4, value=row.get("agent_name"))
#         ws.cell(row=row_idx, column=5, value=row.get("model_name"))
#         ws.cell(row=row_idx, column=6, value=row.get("session_id"))
#         ws.cell(row=row_idx, column=7, value=row.get("prompt_tokens"))
#         ws.cell(row=row_idx, column=8, value=row.get("completion_tokens"))
#         ws.cell(row=row_idx, column=9, value=row.get("cached_tokens"))
#         ws.cell(row=row_idx, column=10, value=row.get("total_tokens"))
#         ws.cell(row=row_idx, column=11, value=float(row.get("prompt_cost", 0)))
#         ws.cell(row=row_idx, column=12, value=float(row.get("completion_cost", 0)))
#         ws.cell(row=row_idx, column=13, value=float(row.get("cached_cost", 0)))
#         ws.cell(row=row_idx, column=14, value=float(row.get("total_cost", 0)))
#         ws.cell(row=row_idx, column=15, value=row.get("call_category"))
#         ws.cell(row=row_idx, column=16, value=row.get("call_sub_category"))
#         ws.cell(row=row_idx, column=17, value=row.get("status"))
        
#         if row_idx % 2 == 0:
#             for col in range(1, len(headers) + 1):
#                 ws.cell(row=row_idx, column=col).fill = _ALT_ROW_FILL
    
#     _auto_size_columns(ws)


# def _build_daily_trend_sheet(ws, query_rows: List[Dict], log_rows: List[Dict]):
#     """Build the Daily Trend sheet with charts"""
#     ws.title = "Daily Trend"
    
#     daily_data = {}
#     for row in query_rows:
#         created_at = row.get("created_at")
#         if created_at:
#             day = str(created_at)[:10]
#             if day not in daily_data:
#                 daily_data[day] = {"queries": 0, "tokens": 0, "cost": 0}
#             daily_data[day]["queries"] += 1
#             daily_data[day]["tokens"] += row.get("total_tokens", 0)
#             daily_data[day]["cost"] += float(row.get("total_cost", 0))
    
#     sorted_days = sorted(daily_data.items())
    
#     headers = ["Date", "Queries", "Tokens", "Cost ($)"]
#     _apply_header_style(ws, 1, headers)
    
#     for row_idx, (day, data) in enumerate(sorted_days, start=2):
#         ws.cell(row=row_idx, column=1, value=day)
#         ws.cell(row=row_idx, column=2, value=data["queries"])
#         ws.cell(row=row_idx, column=3, value=data["tokens"])
#         ws.cell(row=row_idx, column=4, value=data["cost"])
    
#     if len(sorted_days) > 1:
#         chart = LineChart()
#         chart.title = "Daily Cost Trend"
#         chart.style = 13
#         chart.y_axis.title = "Cost ($)"
#         chart.x_axis.title = "Date"
        
#         data_ref = Reference(ws, min_col=4, min_row=1, max_row=len(sorted_days) + 1)
#         cats_ref = Reference(ws, min_col=1, min_row=2, max_row=len(sorted_days) + 1)
#         chart.add_data(data_ref, titles_from_data=True)
#         chart.set_categories(cats_ref)
#         ws.add_chart(chart, "F2")
    
#     _auto_size_columns(ws)


# def _build_model_breakdown_sheet(ws, query_rows: List[Dict], log_rows: List[Dict]):
#     """Build the Model Breakdown sheet"""
#     ws.title = "Model Breakdown"
    
#     model_data = {}
#     for row in log_rows:
#         model = row.get("model_name", "Unknown")
#         if model not in model_data:
#             model_data[model] = {"calls": 0, "tokens": 0, "cost": 0}
#         model_data[model]["calls"] += 1
#         model_data[model]["tokens"] += row.get("total_tokens", 0)
#         model_data[model]["cost"] += float(row.get("total_cost", 0))
    
#     sorted_models = sorted(model_data.items(), key=lambda x: x[1]["cost"], reverse=True)
    
#     headers = ["Model", "Calls", "Tokens", "Cost ($)"]
#     _apply_header_style(ws, 1, headers)
    
#     for row_idx, (model, data) in enumerate(sorted_models, start=2):
#         ws.cell(row=row_idx, column=1, value=model)
#         ws.cell(row=row_idx, column=2, value=data["calls"])
#         ws.cell(row=row_idx, column=3, value=data["tokens"])
#         ws.cell(row=row_idx, column=4, value=data["cost"])
        
#         if row_idx % 2 == 0:
#             for col in range(1, 5):
#                 ws.cell(row=row_idx, column=col).fill = _ALT_ROW_FILL
    
#     if len(sorted_models) > 0:
#         pie = PieChart()
#         pie.title = "Cost Distribution by Model"
#         labels = Reference(ws, min_col=1, min_row=2, max_row=len(sorted_models) + 1)
#         data = Reference(ws, min_col=4, min_row=1, max_row=len(sorted_models) + 1)
#         pie.add_data(data, titles_from_data=True)
#         pie.set_categories(labels)
#         ws.add_chart(pie, "F2")
    
#     _auto_size_columns(ws)


# def _build_category_breakdown_sheet(ws, query_rows: List[Dict], log_rows: List[Dict]):
#     """Build the Category Breakdown sheet"""
#     ws.title = "Category Breakdown"
    
#     cat_data = {}
#     for row in log_rows:
#         cat = row.get("call_category", "other")
#         if cat not in cat_data:
#             cat_data[cat] = {"calls": 0, "tokens": 0, "cost": 0}
#         cat_data[cat]["calls"] += 1
#         cat_data[cat]["tokens"] += row.get("total_tokens", 0)
#         cat_data[cat]["cost"] += float(row.get("total_cost", 0))
    
#     sorted_cats = sorted(cat_data.items(), key=lambda x: x[1]["cost"], reverse=True)
    
#     headers = ["Category", "Calls", "Tokens", "Cost ($)"]
#     _apply_header_style(ws, 1, headers)
    
#     for row_idx, (cat, data) in enumerate(sorted_cats, start=2):
#         ws.cell(row=row_idx, column=1, value=cat)
#         ws.cell(row=row_idx, column=2, value=data["calls"])
#         ws.cell(row=row_idx, column=3, value=data["tokens"])
#         ws.cell(row=row_idx, column=4, value=data["cost"])
        
#         if row_idx % 2 == 0:
#             for col in range(1, 5):
#                 ws.cell(row=row_idx, column=col).fill = _ALT_ROW_FILL
    
#     if len(sorted_cats) > 0:
#         chart = BarChart()
#         chart.type = "col"
#         chart.title = "Calls by Category"
#         chart.y_axis.title = "Number of Calls"
        
#         data = Reference(ws, min_col=2, min_row=1, max_row=len(sorted_cats) + 1)
#         cats = Reference(ws, min_col=1, min_row=2, max_row=len(sorted_cats) + 1)
#         chart.add_data(data, titles_from_data=True)
#         chart.set_categories(cats)
#         ws.add_chart(chart, "F2")
    
#     _auto_size_columns(ws)


# # ========== MAIN EXPORT ENDPOINT ==========

# @router.get(
#     "/token-usage-export",
#     response_model=TokenUsageReportResponse,
#     summary="Export token usage report (simplified summary + downloadable file)"
# )
# async def export_token_usage_report(
#     user_id: Optional[str] = Query(None, description="Filter by user ID"),
#     agent_id: Optional[str] = Query(None, description="Filter by agent ID"),
#     agent_name: Optional[str] = Query(None, description="Filter by agent name"),
#     date_from: Optional[date] = Query(None, description="Start date (YYYY-MM-DD)"),
#     date_to: Optional[date] = Query(None, description="End date (YYYY-MM-DD)"),
#     query_token_usage_repo: QueryTokenUsageRepository = Depends(ServiceProvider.get_query_token_usage_repo),
#     token_logs_repo: TokenUsageLogsRepository = Depends(ServiceProvider.get_token_usage_logs_repo),
#     current_user: User = Depends(get_current_user),
# ):
#     """
#     Generate token usage report with simplified 10-metric summary.
    
#     **Admin only**
    
#     Returns:
#     - Simplified summary (10 key metrics only)
#     - Base64-encoded Excel file for download
#     """
#     if current_user.role not in [UserRole.ADMIN, UserRole.SUPER_ADMIN, "Admin", "SuperAdmin"]:
#         raise HTTPException(status_code=403, detail="Admin privileges required")

#     try:
#         log.info(f"📊 Generating token usage report for {current_user.email}")
        
#         # Fetch data
#         query_rows = await query_token_usage_repo.get_report_data(
#             user_id=user_id, agent_id=agent_id, agent_name=agent_name,
#             date_from=date_from, date_to=date_to
#         )
#         log_rows = await token_logs_repo.get_report_data(
#             user_id=user_id, agent_id=agent_id, agent_name=agent_name,
#             date_from=date_from, date_to=date_to
#         )

#         # Calculate simplified summary (exactly 10 metrics)
#         total_queries = len(query_rows)
#         query_llm_calls = sum(r.get("total_llm_calls", 0) for r in query_rows)
#         total_llm_calls = len(log_rows)
#         total_prompt_tokens = sum(r.get("prompt_tokens", 0) for r in query_rows)
#         total_completion_tokens = sum(r.get("completion_tokens", 0) for r in query_rows)
#         total_cached_tokens = sum(r.get("cached_tokens", 0) for r in query_rows)
#         total_tokens = sum(r.get("total_tokens", 0) for r in query_rows)
#         total_cost = sum(float(r.get("total_cost", 0.0)) for r in query_rows)
#         unique_agents = len(set(r.get("agent_id") for r in query_rows if r.get("agent_id")))
#         unique_users = len(set(r.get("user_id") for r in query_rows if r.get("user_id")))

#         # Build simplified summary
#         summary = SimplifiedSummary(
#             total_queries=total_queries,
#             query_related_llm_calls=query_llm_calls,
#             total_llm_calls=total_llm_calls,
#             total_prompt_tokens=total_prompt_tokens,
#             total_completion_tokens=total_completion_tokens,
#             total_cached_tokens=total_cached_tokens,
#             total_tokens=total_tokens,
#             total_cost_usd=f"${total_cost:.6f}",
#             unique_agents=unique_agents,
#             unique_users=unique_users
#         )

#         # Build Excel workbook
#         wb = Workbook()
#         wb.remove(wb.active)
#         _build_summary_sheet(wb.create_sheet("Summary"), query_rows, log_rows, date_from, date_to)
#         _build_query_usage_sheet(wb.create_sheet("Query Usage"), query_rows)
#         _build_llm_call_details_sheet(wb.create_sheet("LLM Call Details"), log_rows)
#         _build_daily_trend_sheet(wb.create_sheet("Daily Trend"), query_rows, log_rows)
#         _build_model_breakdown_sheet(wb.create_sheet("Model Breakdown"), query_rows, log_rows)
#         _build_category_breakdown_sheet(wb.create_sheet("Category Breakdown"), query_rows, log_rows)

#         # Save to BytesIO and encode
#         excel_buffer = BytesIO()
#         wb.save(excel_buffer)
#         excel_buffer.seek(0)
#         file_base64 = base64.b64encode(excel_buffer.read()).decode('utf-8')

#         timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
#         filename = f"token_usage_report_{timestamp}.xlsx"

#         log.info(f"✅ Token usage report generated: {filename}")

#         return TokenUsageReportResponse(
#             summary=summary,
#             file={
#                 "filename": filename,
#                 "content": file_base64,
#                 "mime_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
#             },
#             generated_at=datetime.now().isoformat()
#         )

#     except Exception as e:
#         log.error(f"❌ Error generating token usage report: {e}", exc_info=True)
#         raise HTTPException(status_code=500, detail=f"Failed to generate report: {str(e)}")


# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.

"""
Token Usage Report Endpoints - Option 1: Summary + Download URL

Generates token usage reports with:
- Simplified 10-metric summary in JSON response
- File saved to disk with download URL (no base64)
- Separate download endpoint
"""

import os
from pathlib import Path
from datetime import datetime, date, timezone, timedelta
from typing import List, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from openpyxl.chart import LineChart, BarChart, PieChart, Reference
from openpyxl.utils import get_column_letter

_SERVER_TZ = timezone(timedelta(hours=5, minutes=30))  # IST


def _to_local_date(ts) -> str:
    """Convert a timestamp to local date string YYYY-MM-DD."""
    if ts is None:
        return ""
    if hasattr(ts, 'astimezone'):
        return ts.astimezone(_SERVER_TZ).strftime("%Y-%m-%d")
    return str(ts)[:10]

from src.database.repositories import QueryTokenUsageRepository, TokenUsageLogsRepository
from src.api.dependencies import ServiceProvider
from src.auth.dependencies import get_current_user
from src.auth.models import User, UserRole
from telemetry_wrapper import logger as log

router = APIRouter(prefix="/reports", tags=["Reports - Token Usage"])

# ========== EXCEL STYLING CONSTANTS ==========
_TITLE_FONT = Font(name="Calibri", size=16, bold=True, color="FFFFFF")
_HEADER_FONT = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
_SUMMARY_FILL = PatternFill("solid", fgColor="2E75B6")
_HEADER_FILL = PatternFill("solid", fgColor="4472C4")
_ALT_ROW_FILL = PatternFill("solid", fgColor="D9E1F2")
_THIN_BORDER = Border(
    left=Side(style="thin"), right=Side(style="thin"),
    top=Side(style="thin"), bottom=Side(style="thin")
)
_COST_NUMBER_FORMAT = '0.00000000'
_CENTER_ALIGN = Alignment(horizontal="center", vertical="center", wrap_text=True)
_LEFT_ALIGN = Alignment(horizontal="left", vertical="center", wrap_text=False)


# ========== RESPONSE MODELS ==========

class SimplifiedSummary(BaseModel):
    """Simplified summary with only essential metrics"""
    total_queries: int
    query_related_llm_calls: int
    total_llm_calls: int
    total_prompt_tokens: int
    total_completion_tokens: int
    total_cached_tokens: int
    total_tokens: int
    total_cost_usd: str  # Formatted as "$0.007112"
    unique_agents: int
    unique_users: int


class TokenUsageReportResponse(BaseModel):
    """Response with summary and download URL"""
    summary: SimplifiedSummary
    download_url: str
    filename: str
    generated_at: str


# ========== HELPER FUNCTIONS ==========

def _apply_header_style(ws, row_num: int, headers: List[str]):
    """Apply header styling to a row"""
    for col_idx, header in enumerate(headers, start=1):
        cell = ws.cell(row=row_num, column=col_idx, value=header)
        cell.font = _HEADER_FONT
        cell.fill = _HEADER_FILL
        cell.alignment = _CENTER_ALIGN
        cell.border = _THIN_BORDER


def _auto_size_columns(ws, min_width=10, max_width=50):
    """Auto-size columns based on content"""
    for column in ws.columns:
        max_length = 0
        column_letter = get_column_letter(column[0].column)
        for cell in column:
            try:
                if cell.value:
                    max_length = max(max_length, len(str(cell.value)))
            except:
                pass
        adjusted_width = min(max(max_length + 2, min_width), max_width)
        ws.column_dimensions[column_letter].width = adjusted_width


def _build_summary_sheet(ws, query_rows: List[Dict], log_rows: List[Dict], date_from, date_to):
    """Build the Summary sheet"""
    ws.title = "Summary"
    
    # Title
    ws.merge_cells('A1:D1')
    title_cell = ws['A1']
    title_cell.value = "Token Usage Report - Summary"
    title_cell.font = _TITLE_FONT
    title_cell.fill = _SUMMARY_FILL
    title_cell.alignment = _CENTER_ALIGN
    
    # Date range
    ws['A2'] = "Report Period:"
    ws['B2'] = f"{date_from or 'All'} to {date_to or 'All'}"
    ws['A2'].font = Font(bold=True)
    
    # Calculate metrics
    total_queries = len(query_rows)
    query_llm_calls = sum(r.get("total_llm_calls", 0) for r in query_rows)
    total_llm_calls = len(log_rows) if log_rows else query_llm_calls
    
    # Overall metrics
    row = 4
    ws.merge_cells(f'A{row}:D{row}')
    ws[f'A{row}'] = "Overall Metrics"
    ws[f'A{row}'].font = Font(size=14, bold=True)
    ws[f'A{row}'].fill = PatternFill("solid", fgColor="E7E6E6")
    
    metrics = [
        ("Total Queries", total_queries),
        ("Query-Related LLM Calls", query_llm_calls),
        ("Total LLM Calls", total_llm_calls),
        ("Total Prompt Tokens", sum(r.get("prompt_tokens", 0) for r in query_rows)),
        ("Total Completion Tokens", sum(r.get("completion_tokens", 0) for r in query_rows)),
        ("Total Cached Tokens", sum(r.get("cached_tokens", 0) for r in query_rows)),
        ("Total Tokens", sum(r.get("total_tokens", 0) for r in query_rows)),
        ("Total Cost (USD)", f"${sum(float(r.get('total_cost', 0)) for r in query_rows):.6f}"),
        ("Unique Agents", len(set(r.get("agent_id") for r in query_rows if r.get("agent_id")))),
        ("Unique Users", len(set(r.get("user_id") for r in query_rows if r.get("user_id")))),
    ]
    
    row += 1
    for metric, value in metrics:
        ws[f'A{row}'] = metric
        ws[f'B{row}'] = value
        ws[f'A{row}'].font = Font(bold=True)
        row += 1
    
    _auto_size_columns(ws)


def _build_query_usage_sheet(ws, query_rows: List[Dict]):
    """Build the Query Usage sheet"""
    ws.title = "Query Usage"
    
    headers = [
        "User ID", "Agent ID", "Agent Name", "Model", "Session ID", "Query",
        "Total Tokens", "Prompt Tokens", "Completion Tokens", "Cached Tokens",
        "Prompt Cost", "Completion Cost", "Cached Cost", "Total Cost",
        "LLM Calls", "Created At"
    ]
    _apply_header_style(ws, 1, headers)
    
    for row_idx, row in enumerate(query_rows, start=2):
        # Extract model name(s) from llm_calls JSONB
        llm_calls_data = row.get("llm_calls") or []
        if isinstance(llm_calls_data, str):
            import json as _json
            try:
                llm_calls_data = _json.loads(llm_calls_data)
            except Exception:
                llm_calls_data = []
        models = sorted(set(c.get("model") or c.get("model_name") or "" for c in llm_calls_data if isinstance(c, dict)))
        model_str = ", ".join(m for m in models if m) or None

        ws.cell(row=row_idx, column=1, value=row.get("user_id"))
        ws.cell(row=row_idx, column=2, value=row.get("agent_id"))
        ws.cell(row=row_idx, column=3, value=row.get("agent_name"))
        ws.cell(row=row_idx, column=4, value=model_str)
        ws.cell(row=row_idx, column=5, value=row.get("session_id"))
        ws.cell(row=row_idx, column=6, value=row.get("query_text", "")[:100])
        ws.cell(row=row_idx, column=7, value=row.get("total_tokens"))
        ws.cell(row=row_idx, column=8, value=row.get("prompt_tokens"))
        ws.cell(row=row_idx, column=9, value=row.get("completion_tokens"))
        ws.cell(row=row_idx, column=10, value=row.get("cached_tokens"))
        ws.cell(row=row_idx, column=11, value=float(row.get("prompt_cost", 0))).number_format = _COST_NUMBER_FORMAT
        ws.cell(row=row_idx, column=12, value=float(row.get("completion_cost", 0))).number_format = _COST_NUMBER_FORMAT
        ws.cell(row=row_idx, column=13, value=float(row.get("cached_cost", 0))).number_format = _COST_NUMBER_FORMAT
        ws.cell(row=row_idx, column=14, value=float(row.get("total_cost", 0))).number_format = _COST_NUMBER_FORMAT
        ws.cell(row=row_idx, column=15, value=row.get("total_llm_calls"))
        created_at = row.get("created_at")
        if created_at and hasattr(created_at, 'astimezone'):
            ws.cell(row=row_idx, column=16, value=created_at.astimezone(_SERVER_TZ).strftime("%Y-%m-%d %H:%M:%S"))
        else:
            ws.cell(row=row_idx, column=16, value=str(created_at or ""))
        
        if row_idx % 2 == 0:
            for col in range(1, len(headers) + 1):
                ws.cell(row=row_idx, column=col).fill = _ALT_ROW_FILL
    
    _auto_size_columns(ws)


def _build_llm_call_details_sheet(ws, log_rows: List[Dict]):
    """Build the LLM Call Details sheet"""
    ws.title = "LLM Call Details"
    
    headers = [
        "Timestamp", "User ID", "Agent ID", "Agent Name", "Model", "Session ID",
        "Prompt Tokens", "Completion Tokens", "Cached Tokens", "Total Tokens",
        "Prompt Cost", "Completion Cost", "Cached Cost", "Total Cost",
        "Status"
    ]
    _apply_header_style(ws, 1, headers)
    
    for row_idx, row in enumerate(log_rows, start=2):
        ts = row.get("timestamp")
        if ts and hasattr(ts, 'astimezone'):
            ws.cell(row=row_idx, column=1, value=ts.astimezone(_SERVER_TZ).strftime("%Y-%m-%d %H:%M:%S"))
        else:
            ws.cell(row=row_idx, column=1, value=str(ts or ""))
        ws.cell(row=row_idx, column=2, value=row.get("user_id"))
        ws.cell(row=row_idx, column=3, value=row.get("agent_id"))
        ws.cell(row=row_idx, column=4, value=row.get("agent_name"))
        ws.cell(row=row_idx, column=5, value=row.get("model_name"))
        ws.cell(row=row_idx, column=6, value=row.get("session_id"))
        ws.cell(row=row_idx, column=7, value=row.get("prompt_tokens"))
        ws.cell(row=row_idx, column=8, value=row.get("completion_tokens"))
        ws.cell(row=row_idx, column=9, value=row.get("cached_tokens"))
        ws.cell(row=row_idx, column=10, value=row.get("total_tokens"))
        ws.cell(row=row_idx, column=11, value=float(row.get("prompt_cost", 0))).number_format = _COST_NUMBER_FORMAT
        ws.cell(row=row_idx, column=12, value=float(row.get("completion_cost", 0))).number_format = _COST_NUMBER_FORMAT
        ws.cell(row=row_idx, column=13, value=float(row.get("cached_cost", 0))).number_format = _COST_NUMBER_FORMAT
        ws.cell(row=row_idx, column=14, value=float(row.get("total_cost", 0))).number_format = _COST_NUMBER_FORMAT
        ws.cell(row=row_idx, column=15, value=row.get("status"))
        
        if row_idx % 2 == 0:
            for col in range(1, len(headers) + 1):
                ws.cell(row=row_idx, column=col).fill = _ALT_ROW_FILL
    
    _auto_size_columns(ws)


def _build_daily_trend_sheet(ws, query_rows: List[Dict], log_rows: List[Dict]):
    """Build the Daily Trend sheet with charts"""
    ws.title = "Daily Trend"

    daily_data: Dict[str, Dict] = {}

    for row in query_rows:
        created_at = row.get("created_at")
        if created_at:
            day = _to_local_date(created_at)
            if day not in daily_data:
                daily_data[day] = {"queries": 0, "llm_calls": 0, "tokens": 0, "cost": 0.0, "users": set(), "agents": set()}
            daily_data[day]["queries"] += 1
            daily_data[day]["tokens"] += row.get("total_tokens", 0)
            daily_data[day]["cost"] += float(row.get("total_cost", 0))
            if row.get("user_id"):
                daily_data[day]["users"].add(row["user_id"])
            if row.get("agent_name"):
                daily_data[day]["agents"].add(row["agent_name"])

    for row in log_rows:
        ts = row.get("timestamp")
        if ts:
            day = _to_local_date(ts)
            if day not in daily_data:
                daily_data[day] = {"queries": 0, "llm_calls": 0, "tokens": 0, "cost": 0.0, "users": set(), "agents": set()}
            daily_data[day]["llm_calls"] += 1

    sorted_days = sorted(daily_data.items())

    headers = ["Date", "Queries", "LLM Calls", "Tokens", "Cost ($)", "Unique Users", "Unique Agents"]
    _apply_header_style(ws, 1, headers)

    for row_idx, (day, data) in enumerate(sorted_days, start=2):
        ws.cell(row=row_idx, column=1, value=day)
        ws.cell(row=row_idx, column=2, value=data["queries"])
        ws.cell(row=row_idx, column=3, value=data["llm_calls"])
        ws.cell(row=row_idx, column=4, value=data["tokens"])
        ws.cell(row=row_idx, column=5, value=data["cost"]).number_format = _COST_NUMBER_FORMAT
        ws.cell(row=row_idx, column=6, value=len(data["users"]))
        ws.cell(row=row_idx, column=7, value=len(data["agents"]))

        if row_idx % 2 == 0:
            for col in range(1, len(headers) + 1):
                ws.cell(row=row_idx, column=col).fill = _ALT_ROW_FILL

    if len(sorted_days) > 1:
        chart = LineChart()
        chart.title = "Daily Cost Trend"
        chart.style = 13
        chart.y_axis.title = "Cost ($)"
        chart.x_axis.title = "Date"

        data_ref = Reference(ws, min_col=5, min_row=1, max_row=len(sorted_days) + 1)
        cats_ref = Reference(ws, min_col=1, min_row=2, max_row=len(sorted_days) + 1)
        chart.add_data(data_ref, titles_from_data=True)
        chart.set_categories(cats_ref)
        ws.add_chart(chart, "I2")

    _auto_size_columns(ws)


def _build_daily_agent_breakdown_sheet(ws, query_rows: List[Dict], log_rows: List[Dict]):
    """Build the Daily by Agent sheet - one row per (date, agent) combination"""
    ws.title = "Daily by Agent"

    day_agent: Dict[str, Dict[str, Dict]] = {}

    for row in query_rows:
        created_at = row.get("created_at")
        agent = row.get("agent_name")
        if not agent or not created_at:
            continue
        day = _to_local_date(created_at)
        key = (day, agent)
        if key not in day_agent:
            day_agent[key] = {"tokens": 0, "cost": 0.0}
        day_agent[key]["tokens"] += row.get("total_tokens", 0)
        day_agent[key]["cost"] += float(row.get("total_cost", 0))

    for row in log_rows:
        ts = row.get("timestamp")
        agent = row.get("agent_name")
        if not agent or not ts:
            continue
        day = _to_local_date(ts)
        key = (day, agent)
        if key not in day_agent:
            day_agent[key] = {"tokens": 0, "cost": 0.0}
        day_agent[key]["tokens"] += row.get("total_tokens", 0)

    sorted_entries = sorted(day_agent.items(), key=lambda x: (x[0][0], x[0][1]))

    headers = ["Date", "Agent Name", "Tokens", "Cost ($)"]
    _apply_header_style(ws, 1, headers)

    for row_idx, ((day, agent), data) in enumerate(sorted_entries, start=2):
        ws.cell(row=row_idx, column=1, value=day)
        ws.cell(row=row_idx, column=2, value=agent)
        ws.cell(row=row_idx, column=3, value=data["tokens"])
        ws.cell(row=row_idx, column=4, value=data["cost"]).number_format = _COST_NUMBER_FORMAT

        if row_idx % 2 == 0:
            for col in range(1, len(headers) + 1):
                ws.cell(row=row_idx, column=col).fill = _ALT_ROW_FILL

    if len(sorted_entries) > 1:
        chart = BarChart()
        chart.type = "col"
        chart.title = "Daily Cost by Agent"
        chart.y_axis.title = "Cost ($)"

        data_ref = Reference(ws, min_col=4, min_row=1, max_row=len(sorted_entries) + 1)
        cats_ref = Reference(ws, min_col=1, min_row=2, max_row=len(sorted_entries) + 1)
        chart.add_data(data_ref, titles_from_data=True)
        chart.set_categories(cats_ref)
        ws.add_chart(chart, "F2")

    _auto_size_columns(ws)


def _build_model_breakdown_sheet(ws, query_rows: List[Dict], log_rows: List[Dict]):
    """Build the Model Breakdown sheet"""
    ws.title = "Model Breakdown"
    
    model_data = {}
    for row in log_rows:
        model = row.get("model_name", "Unknown")
        if model not in model_data:
            model_data[model] = {"calls": 0, "tokens": 0, "cost": 0}
        model_data[model]["calls"] += 1
        model_data[model]["tokens"] += row.get("total_tokens", 0)
        model_data[model]["cost"] += float(row.get("total_cost", 0))
    
    sorted_models = sorted(model_data.items(), key=lambda x: x[1]["cost"], reverse=True)
    
    headers = ["Model", "Calls", "Tokens", "Cost ($)"]
    _apply_header_style(ws, 1, headers)
    
    for row_idx, (model, data) in enumerate(sorted_models, start=2):
        ws.cell(row=row_idx, column=1, value=model)
        ws.cell(row=row_idx, column=2, value=data["calls"])
        ws.cell(row=row_idx, column=3, value=data["tokens"])
        ws.cell(row=row_idx, column=4, value=data["cost"])
        
        if row_idx % 2 == 0:
            for col in range(1, 5):
                ws.cell(row=row_idx, column=col).fill = _ALT_ROW_FILL
    
    if len(sorted_models) > 0:
        pie = PieChart()
        pie.title = "Cost Distribution by Model"
        labels = Reference(ws, min_col=1, min_row=2, max_row=len(sorted_models) + 1)
        data = Reference(ws, min_col=4, min_row=1, max_row=len(sorted_models) + 1)
        pie.add_data(data, titles_from_data=True)
        pie.set_categories(labels)
        ws.add_chart(pie, "F2")
    
    _auto_size_columns(ws)


# ========== MAIN EXPORT ENDPOINT ==========

@router.get(
    "/token-usage-export",
    response_model=TokenUsageReportResponse,
    summary="Export token usage report (summary + download URL)"
)
async def export_token_usage_report(
    user_id: Optional[str] = Query(None, description="Filter by user ID"),
    agent_id: Optional[str] = Query(None, description="Filter by agent ID"),
    agent_name: Optional[str] = Query(None, description="Filter by agent name"),
    date_from: Optional[date] = Query(None, description="Start date (YYYY-MM-DD)"),
    date_to: Optional[date] = Query(None, description="End date (YYYY-MM-DD)"),
    department_name: Optional[str] = Query(None, description="Filter by department (SuperAdmin only)"),
    model: Optional[str] = Query(None, description="Filter by model name"),
    status: Optional[str] = Query(None, description="Filter by status (success/failure)"),
    session_id: Optional[str] = Query(None, description="Filter by session ID"),
    query_token_usage_repo: QueryTokenUsageRepository = Depends(ServiceProvider.get_query_token_usage_repo),
    token_logs_repo: TokenUsageLogsRepository = Depends(ServiceProvider.get_token_usage_logs_repo),
    current_user: User = Depends(get_current_user),
):
    """
    Generate token usage report with simplified summary and download URL.
    
    **Admin only**
    
    RBAC rules:
    - SuperAdmin: can filter any department
    - Admin: scoped to own department only
    
    Returns:
    - `summary`: 10 key metrics for immediate UI display
    - `download_url`: Endpoint to download the Excel file
    - `filename`: Generated filename
    - `generated_at`: Timestamp
    """
    # RBAC scoping based on role
    if current_user.role in [UserRole.SUPER_ADMIN, "SuperAdmin"]:
        effective_department = department_name
        effective_user_id = user_id
    elif current_user.role in [UserRole.ADMIN, "Admin"]:
        effective_department = current_user.department_name
        effective_user_id = user_id
    else:
        effective_department = None
        effective_user_id = current_user.email

    try:
        log.info(f"Generating token usage report for {current_user.email}")
        
        # Fetch data from repositories with RBAC-scoped filters
        query_rows = await query_token_usage_repo.get_report_data(
            user_id=effective_user_id, agent_id=agent_id, agent_name=agent_name,
            date_from=date_from, date_to=date_to,
            department_name=effective_department, session_id=session_id
        )
        log_rows = await token_logs_repo.get_report_data(
            user_id=effective_user_id, agent_id=agent_id, agent_name=agent_name,
            date_from=date_from, date_to=date_to,
            department_name=effective_department, model=model,
            status=status, session_id=session_id
        )

        # Calculate simplified summary metrics
        total_queries = len(query_rows)
        query_llm_calls = sum(r.get("total_llm_calls", 0) for r in query_rows)
        total_llm_calls = len(log_rows)
        total_prompt_tokens = sum(r.get("prompt_tokens", 0) for r in query_rows)
        total_completion_tokens = sum(r.get("completion_tokens", 0) for r in query_rows)
        total_cached_tokens = sum(r.get("cached_tokens", 0) for r in query_rows)
        total_tokens = sum(r.get("total_tokens", 0) for r in query_rows)
        total_cost = sum(float(r.get("total_cost", 0.0)) for r in query_rows)
        unique_agents = len(set(r.get("agent_id") for r in query_rows if r.get("agent_id")))
        unique_users = len(set(r.get("user_id") for r in query_rows if r.get("user_id")))

        # Build simplified summary
        summary = SimplifiedSummary(
            total_queries=total_queries,
            query_related_llm_calls=query_llm_calls,
            total_llm_calls=total_llm_calls,
            total_prompt_tokens=total_prompt_tokens,
            total_completion_tokens=total_completion_tokens,
            total_cached_tokens=total_cached_tokens,
            total_tokens=total_tokens,
            total_cost_usd=f"${total_cost:.6f}",
            unique_agents=unique_agents,
            unique_users=unique_users
        )

        # Build Excel workbook with all sheets
        wb = Workbook()
        wb.remove(wb.active)
        _build_summary_sheet(wb.create_sheet("Summary"), query_rows, log_rows, date_from, date_to)
        _build_query_usage_sheet(wb.create_sheet("Query Usage"), query_rows)
        _build_llm_call_details_sheet(wb.create_sheet("LLM Call Details"), log_rows)
        _build_daily_trend_sheet(wb.create_sheet("Daily Trend"), query_rows, log_rows)
        _build_daily_agent_breakdown_sheet(wb.create_sheet("Daily by Agent"), query_rows, log_rows)
        _build_model_breakdown_sheet(wb.create_sheet("Model Breakdown"), query_rows, log_rows)

        # Save Excel file to disk
        reports_dir = Path("reports")
        reports_dir.mkdir(exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"token_usage_report_{timestamp}.xlsx"
        file_path = reports_dir / filename
        
        wb.save(file_path)

        log.info(f"✅ Token usage report generated: {filename}")

        # Return JSON response with summary and download URL
        return TokenUsageReportResponse(
            summary=summary,
            download_url=f"/reports/download/{filename}",
            filename=filename,
            generated_at=datetime.now().isoformat()
        )

    except Exception as e:
        log.error(f"❌ Error generating token usage report: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to generate report: {str(e)}")


# ========== DOWNLOAD ENDPOINT ==========

@router.get(
    "/download/{filename}",
    summary="Download token usage report file"
)
async def download_report(
    filename: str,
    current_user: User = Depends(get_current_user)
):
    """
    Download a previously generated token usage report Excel file.
    
    Security: Prevents path traversal attacks.
    All authenticated users can download reports (data is already RBAC-scoped at generation time).
    """

    try:
        # Security: Prevent path traversal attacks
        safe_filename = os.path.basename(filename)
        if safe_filename != filename or '..' in filename:
            raise HTTPException(status_code=400, detail="Invalid filename")

        file_path = Path("reports") / safe_filename
        
        if not file_path.exists():
            raise HTTPException(status_code=404, detail="Report file not found")

        log.info(f"📥 Token usage report downloaded: {filename} by {current_user.email}")

        return FileResponse(
            path=str(file_path),
            filename=filename,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'}
        )

    except HTTPException:
        raise
    except Exception as e:
        log.error(f"❌ Error downloading report: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to download report: {str(e)}")