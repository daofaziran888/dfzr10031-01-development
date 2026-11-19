"""月度取数接口：执行月度取数、发布指标结果快照、提交交易更正、查询双月汇总。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.metric_run import MetricRunService

router = APIRouter(prefix="/api/metric_run", tags=["月度取数"])

service = MetricRunService()

LIST_FIELDS = ["快照编号", "指标编号", "统计月份", "口径版本", "输入批次", "指标金额", "交易笔数", "快照状态"]
STATUSES = ["已发布", "已取代", "计算失败"]


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出指标结果快照清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "metric_run", "total": total, "items": items}


@router.get("/summary")
def monthly_summary(
    metric: str = Query(..., description="指标编号"),
    months: str = Query(..., description="逗号分隔的统计月份，如 2026-09,2026-10"),
) -> dict[str, Any]:
    """核账双月汇总：每个月返回当前已发布的快照金额，先把两个月对齐再提更正。"""
    month_list = [item.strip() for item in months.split(",") if item.strip()]
    if not month_list:
        raise HTTPException(status_code=400, detail="months 至少包含一个月份，格式 YYYY-MM")
    items = service.monthly_summary(metric, month_list)
    return {"指标编号": metric, "items": items}


@router.get("/transactions")
def list_transactions(
    txn: str | None = Query(default=None, description="按交易编号检索"),
    month: str | None = Query(default=None, description="按业务日期所在月份过滤，格式 YYYY-MM"),
) -> dict[str, Any]:
    """交易源记录：核对一笔交易当前归入哪个月份、属于哪个输入批次、是否已被更正。"""
    items = service.list_transactions(txn_code=txn, month=month)
    return {"total": len(items), "items": items}


@router.post("/corrections", response_model=ActionResult)
def submit_correction(payload: EntryPayload) -> ActionResult:
    """提交交易更正：把一笔交易改到另一个月份，两个受影响月份一起重算并重新判定告警。"""
    result, message = service.submit_correction(payload.values)
    if result is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=result)


@router.get("", response_model=PageResult[dict])
def list_entries(
    request: Request,
    keyword: str | None = Query(default=None, description="按指标编号检索"),
    status: str | None = Query(default=None, description="已发布、已取代、计算失败"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按指标编号与快照状态过滤指标结果快照列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    extra = {k: v for k, v in request.query_params.items() if k not in ("keyword", "status", "page", "size") and v.strip()}
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size, extra=extra)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条指标结果快照明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"指标结果快照 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """执行一次月度取数：按指标编号与统计月份聚合并发布快照；计算失败会留下失败行。"""
    entry, message = service.create_entry(payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=entry.get("status") == "已发布", message=message, entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条快照执行重新取数；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=entry.get("status") == "已发布", message=message, entry=entry)
