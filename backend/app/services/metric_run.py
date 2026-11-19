"""月度取数业务规则：从已接入数据集聚合交易、发布指标结果快照并驱动告警判定。

核心约定：
- 同一交易编号只保留最新一条有效记录，一份结果中一笔交易只归入一个自然月；
- 补传更正会生成新的输入批次，并同时重算原月份与新月份两个窗口；
- 告警只按「已发布」的快照判定；计算失败只记录失败行，不覆盖上次完整结果。
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from app.store import store

MODULE = "metric_run"
TXN_MODULE = "metric_txn"
EVAL_MODULE = "alert_eval"

REQUIRED_FIELDS = ["指标编号", "统计月份"]
STATUS_ORDER = ["已发布", "已取代", "计算失败"]
ACTION_RULES = {"重新取数": "已发布"}
NEGATIVE_ACTIONS: list[str] = []

CONNECTED_DATASET_STATUSES = ("已接入", "使用中")
METRIC_PUBLISHED_STATUS = "已发布"
ALERT_ACTIVE_STATUS = "生效中"
TXN_VALID_STATUS = "有效"
TXN_CORRECTED_STATUS = "已更正"

_THRESHOLD_RE = re.compile(r"^(>=|<=|==|>|<)\s*(\d+(?:\.\d+)?)$")
_MONTH_RE = re.compile(r"^\d{4}-\d{2}$")


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _month_of(date_text: Any) -> str:
    return str(date_text or "")[:7]


def _fmt_amount(value: Any) -> str:
    try:
        return f"{float(value):g}"
    except (TypeError, ValueError):
        return str(value)


def _next_id(rows: list[dict[str, Any]]) -> int:
    return max((int(row.get("id", 0)) for row in rows), default=0) + 1


def _next_code(rows: list[dict[str, Any]], field: str, prefix: str) -> str:
    return f"{prefix}-{_next_id(rows):04d}"


def _parse_threshold(text: str) -> tuple[str, float] | None:
    match = _THRESHOLD_RE.match(text.replace(" ", ""))
    if not match:
        return None
    return match.group(1), float(match.group(2))


def _compare(amount: float, op: str, value: float) -> bool:
    if op == ">=":
        return amount >= value
    if op == "<=":
        return amount <= value
    if op == ">":
        return amount > value
    if op == "<":
        return amount < value
    return amount == value


class MetricRunService:
    # ---------- 列表与明细 ----------
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
        extra: dict[str, str] | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("指标编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        if extra:
            for field, val in extra.items():
                rows = [row for row in rows if val in str(row.get(field, ""))]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def list_transactions(
        self,
        *,
        txn_code: str | None = None,
        month: str | None = None,
    ) -> list[dict[str, Any]]:
        """交易源记录：核对一笔交易当前归入哪个月份、是否已被更正。"""
        rows = store.rows(TXN_MODULE)
        if txn_code:
            rows = [row for row in rows if txn_code in str(row.get("交易编号", ""))]
        if month:
            rows = [row for row in rows if _month_of(row.get("业务日期")) == month]
        return sorted(rows, key=lambda row: int(row.get("id", 0)))

    def monthly_summary(self, metric_code: str, months: list[str]) -> list[dict[str, Any]]:
        """核账用双月汇总：每个月返回当前「已发布」的那一份快照。"""
        items: list[dict[str, Any]] = []
        for month in months:
            snapshot = self._current_snapshot(metric_code, month)
            if snapshot is None:
                items.append({"指标编号": metric_code, "统计月份": month, "指标金额": None, "说明": "暂无已发布快照"})
            else:
                items.append(snapshot)
        return items

    # ---------- 月度取数 ----------
    def run_fetch(
        self,
        metric_code: str,
        month: str,
        *,
        dataset_code: str | None = None,
        trigger_batch: str | None = None,
    ) -> tuple[dict[str, Any] | None, str]:
        """执行一次月度取数并发布快照；失败时登记失败行，保留上次已发布结果。"""
        metric = self._find_metric(metric_code)
        if metric is None:
            return None, f"指标 {metric_code} 未登记，无法执行月度取数"
        if not _MONTH_RE.match(month):
            return None, f"统计月份 {month} 格式应为 YYYY-MM"
        if metric.get("status") != METRIC_PUBLISHED_STATUS:
            reason = f"指标 {metric_code} 当前状态为「{metric.get('status')}」，未发布不能取数"
            entry = self._record_failure(metric_code, month, metric=metric, dataset_code=dataset_code, reason=reason)
            return entry, f"月度取数失败：{reason}，上次已发布结果保持不变"

        dataset, dataset_error = self._resolve_dataset(dataset_code)
        if dataset is None:
            entry = self._record_failure(metric_code, month, metric=metric, dataset_code=dataset_code, reason=dataset_error)
            return entry, f"月度取数失败：{dataset_error}，上次已发布结果保持不变"

        txns = self._valid_transactions(str(dataset.get("数据集编号")))
        if not txns:
            reason = f"数据集 {dataset.get('数据集编号')} 没有有效交易记录"
            entry = self._record_failure(metric_code, month, metric=metric, dataset_code=dataset_code, reason=reason)
            return entry, f"月度取数失败：{reason}，上次已发布结果保持不变"

        month_txns = [txn for txn in txns if _month_of(txn.get("业务日期")) == month]
        amount = round(sum(float(txn.get("实付金额") or 0) for txn in month_txns), 2)
        batch = trigger_batch or str(max(txns, key=lambda row: int(row.get("id", 0))).get("输入批次") or "")

        rows = store.rows(MODULE)
        for snap in rows:
            if snap.get("指标编号") == metric_code and snap.get("统计月份") == month and snap.get("status") == "已发布":
                snap["status"] = "已取代"
                snap["快照状态"] = "已取代"
        entry = {
            "id": _next_id(rows),
            "快照编号": _next_code(rows, "快照编号", "MRUN"),
            "指标编号": metric_code,
            "统计月份": month,
            "口径版本": str(metric.get("口径版本") or ""),
            "输入批次": batch,
            "数据集编号": str(dataset.get("数据集编号") or ""),
            "指标金额": amount,
            "交易笔数": len(month_txns),
            "计算时间": _now(),
            "失败原因": "",
            "status": "已发布",
            "快照状态": "已发布",
            "pending": False,
            "abnormal": False,
        }
        rows.append(entry)
        evals = self._evaluate_alerts(entry)
        message = f"{month} 月度取数完成：{metric_code} 金额 {_fmt_amount(amount)}，{len(month_txns)} 笔交易（批次 {batch}）"
        if evals:
            message += "；" + "；".join(f"规则 {item['规则编号']} {item['判定结果']}" for item in evals)
        return entry, message

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        metric_code = str(values.get("指标编号") or "").strip()
        month = str(values.get("统计月份") or "").strip()
        dataset_code = str(values.get("数据集编号") or "").strip() or None
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, f"缺少必填字段：{'、'.join(missing)}"
        return self.run_fetch(metric_code, month, dataset_code=dataset_code)

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"指标结果快照 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于月度取数可执行范围"
        dataset_code = str(entry.get("数据集编号") or "").strip() or None
        return self.run_fetch(str(entry.get("指标编号")), str(entry.get("统计月份")), dataset_code=dataset_code)

    # ---------- 交易更正（补传） ----------
    def submit_correction(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        """补传更正：把一笔交易改到另一个月份，两个受影响月份一起重算、一起判定。"""
        txn_code = str(values.get("交易编号") or "").strip()
        new_date = str(values.get("新业务日期") or "").strip()
        if not txn_code or not new_date:
            return None, "缺少必填字段：交易编号、新业务日期"
        try:
            datetime.strptime(new_date, "%Y-%m-%d")
        except ValueError:
            return None, f"新业务日期 {new_date} 格式应为 YYYY-MM-DD"

        txn_rows = store.rows(TXN_MODULE)
        record = next(
            (row for row in txn_rows if row.get("交易编号") == txn_code and row.get("记录状态") == TXN_VALID_STATUS),
            None,
        )
        if record is None:
            return None, f"交易 {txn_code} 不存在或已被更正，无法再次补传"

        old_month = _month_of(record.get("业务日期"))
        new_month = _month_of(new_date)
        if new_month == old_month:
            return None, f"交易 {txn_code} 更正前后都在 {old_month}，月度金额不受影响"

        raw_amount = values.get("实付金额")
        try:
            amount = float(raw_amount) if raw_amount not in (None, "") else float(record.get("实付金额") or 0)
        except (TypeError, ValueError):
            return None, f"实付金额 {raw_amount} 必须是数字"

        new_batch = self._next_correction_batch()
        record["记录状态"] = TXN_CORRECTED_STATUS
        record["status"] = TXN_CORRECTED_STATUS
        txn_rows.append({
            "id": _next_id(txn_rows),
            "交易编号": txn_code,
            "业务日期": new_date,
            "实付金额": amount,
            "数据集编号": record.get("数据集编号"),
            "输入批次": new_batch,
            "记录状态": TXN_VALID_STATUS,
            "status": TXN_VALID_STATUS,
            "pending": False,
            "abnormal": False,
        })

        affected_months = sorted({old_month, new_month})
        dataset_code = str(record.get("数据集编号") or "").strip() or None
        metric_codes = sorted({
            str(snap.get("指标编号"))
            for snap in store.rows(MODULE)
            if snap.get("统计月份") in affected_months and snap.get("status") in ("已发布", "已取代")
        })
        before = {
            (code, month): (self._current_snapshot(code, month) or {}).get("指标金额")
            for code in metric_codes
            for month in affected_months
        }
        results: list[dict[str, Any]] = []
        for code in metric_codes:
            for month in affected_months:
                snap, _ = self.run_fetch(code, month, dataset_code=dataset_code, trigger_batch=new_batch)
                if snap is not None:
                    results.append(snap)

        changes = []
        for code in metric_codes:
            for month in affected_months:
                old_amount = before.get((code, month))
                new_snap = next((s for s in results if s.get("指标编号") == code and s.get("统计月份") == month), None)
                new_amount = new_snap.get("指标金额") if new_snap else None
                if old_amount is None:
                    changes.append(f"{month} 首次发布 {_fmt_amount(new_amount)}")
                else:
                    changes.append(f"{month} 金额 {_fmt_amount(old_amount)}→{_fmt_amount(new_amount)}")
        summary = {
            "交易编号": txn_code,
            "原月份": old_month,
            "新月份": new_month,
            "输入批次": new_batch,
            "重算结果": [
                {
                    "指标编号": snap.get("指标编号"),
                    "统计月份": snap.get("统计月份"),
                    "快照编号": snap.get("快照编号"),
                    "指标金额": snap.get("指标金额"),
                    "交易笔数": snap.get("交易笔数"),
                    "快照状态": snap.get("status"),
                }
                for snap in results
            ],
        }
        detail = "；".join(changes) if changes else "暂无已发布快照需要重算"
        return summary, f"更正已提交（批次 {new_batch}）：{detail}，告警已按新快照重新判定"

    # ---------- 内部 ----------
    def _find_metric(self, metric_code: str) -> dict[str, Any] | None:
        for row in store.rows("metric_def"):
            if str(row.get("指标编号")) == metric_code:
                return row
        return None

    def _resolve_dataset(self, dataset_code: str | None) -> tuple[dict[str, Any] | None, str]:
        rows = store.rows("dataset")
        if dataset_code:
            dataset = next((row for row in rows if str(row.get("数据集编号")) == dataset_code), None)
            if dataset is None:
                return None, f"数据集 {dataset_code} 不存在"
            if dataset.get("status") not in CONNECTED_DATASET_STATUSES:
                return None, f"数据集 {dataset_code} 当前状态为「{dataset.get('status')}」，未接入不能取数"
            return dataset, ""
        for row in rows:
            if row.get("status") in CONNECTED_DATASET_STATUSES:
                return row, ""
        return None, "没有已接入的分析数据集"

    def _valid_transactions(self, dataset_code: str) -> list[dict[str, Any]]:
        """同一交易编号只取最新一条有效记录，保证一笔交易只归入一个月份。"""
        latest: dict[str, dict[str, Any]] = {}
        for row in store.rows(TXN_MODULE):
            if str(row.get("数据集编号")) != dataset_code:
                continue
            if row.get("记录状态") != TXN_VALID_STATUS:
                continue
            key = str(row.get("交易编号"))
            if key not in latest or int(row.get("id", 0)) > int(latest[key].get("id", 0)):
                latest[key] = row
        return list(latest.values())

    def _current_snapshot(self, metric_code: str, month: str) -> dict[str, Any] | None:
        current: dict[str, Any] | None = None
        for snap in store.rows(MODULE):
            if snap.get("指标编号") == metric_code and snap.get("统计月份") == month and snap.get("status") == "已发布":
                if current is None or int(snap.get("id", 0)) > int(current.get("id", 0)):
                    current = snap
        return current

    def _record_failure(
        self,
        metric_code: str,
        month: str,
        *,
        metric: dict[str, Any] | None = None,
        dataset_code: str | None = None,
        reason: str,
    ) -> dict[str, Any]:
        rows = store.rows(MODULE)
        entry = {
            "id": _next_id(rows),
            "快照编号": _next_code(rows, "快照编号", "MRUN"),
            "指标编号": metric_code,
            "统计月份": month,
            "口径版本": str(metric.get("口径版本") or "") if metric else "",
            "输入批次": "",
            "数据集编号": dataset_code or "",
            "指标金额": None,
            "交易笔数": None,
            "计算时间": _now(),
            "失败原因": reason,
            "status": "计算失败",
            "快照状态": "计算失败",
            "pending": True,
            "abnormal": True,
        }
        rows.append(entry)
        return entry

    def _next_correction_batch(self) -> str:
        count = sum(
            1
            for row in store.rows(TXN_MODULE)
            if str(row.get("输入批次", "")).startswith("BATCH-CORR-")
        )
        return f"BATCH-CORR-{count + 1:04d}"

    def _evaluate_alerts(self, snapshot: dict[str, Any]) -> list[dict[str, Any]]:
        """按刚发布的快照判定生效中的告警规则，并写明与上次判定的差异。"""
        metric_code = str(snapshot.get("指标编号"))
        month = str(snapshot.get("统计月份"))
        eval_rows = store.rows(EVAL_MODULE)
        created: list[dict[str, Any]] = []
        for rule in store.rows("alert"):
            if rule.get("status") != ALERT_ACTIVE_STATUS:
                continue
            if str(rule.get("监控指标")) != metric_code:
                continue
            parsed = _parse_threshold(str(rule.get("阈值条件") or ""))
            if parsed is None:
                continue
            op, value = parsed
            amount = float(snapshot.get("指标金额") or 0)
            triggered = _compare(amount, op, value)
            result = "已触发" if triggered else "未触发"
            prev = self._latest_eval(str(rule.get("规则编号")), month)
            if prev is None:
                note = f"首次判定：金额 {_fmt_amount(amount)}，阈值 {op}{_fmt_amount(value)}，结论{result}"
            elif prev.get("判定结果") != result:
                note = (
                    f"金额 {_fmt_amount(prev.get('指标金额'))}→{_fmt_amount(amount)}"
                    f"（批次 {prev.get('输入批次')}→{snapshot.get('输入批次')}），"
                    f"由{prev.get('判定结果')}转为{result}"
                )
            else:
                note = (
                    f"金额 {_fmt_amount(prev.get('指标金额'))}→{_fmt_amount(amount)}"
                    f"（批次 {prev.get('输入批次')}→{snapshot.get('输入批次')}），维持{result}"
                )
            entry = {
                "id": _next_id(eval_rows),
                "判定编号": _next_code(eval_rows, "判定编号", "AEVL"),
                "规则编号": str(rule.get("规则编号")),
                "指标编号": metric_code,
                "统计月份": month,
                "快照编号": snapshot.get("快照编号"),
                "输入批次": snapshot.get("输入批次"),
                "指标金额": snapshot.get("指标金额"),
                "阈值条件": str(rule.get("阈值条件") or ""),
                "判定结果": result,
                "变化说明": note,
                "判定时间": _now(),
                "status": "已记录",
                "pending": False,
                "abnormal": triggered,
            }
            eval_rows.append(entry)
            created.append(entry)
        return created

    def _latest_eval(self, rule_code: str, month: str) -> dict[str, Any] | None:
        latest: dict[str, Any] | None = None
        for row in store.rows(EVAL_MODULE):
            if str(row.get("规则编号")) == rule_code and str(row.get("统计月份")) == month:
                if latest is None or int(row.get("id", 0)) > int(latest.get("id", 0)):
                    latest = row
        return latest
