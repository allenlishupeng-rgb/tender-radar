from datetime import datetime
import json

from config.settings import DATA_DIR


FAILURE_STATE_PATH = DATA_DIR / "source_failure_state.json"
SUCCESS_STATUSES = {"成功", "无结果"}
FAILURE_STATUSES = {"访问失败/受限", "失败"}
IGNORED_FAILURE_STATUSES = {"已禁用", "示例源跳过"}


def load_source_failure_state(path=FAILURE_STATE_PATH) -> dict:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return {}


def save_source_failure_state(state: dict, path=FAILURE_STATE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def source_status_failed(status: dict) -> bool:
    status_text = status.get("status", "")
    return status_text in FAILURE_STATUSES


def apply_source_failure_alerts(statuses: list[dict], source_configs: list[dict], state_path=FAILURE_STATE_PATH) -> list[dict]:
    source_by_name = {source.get("name", ""): source for source in source_configs}
    state = load_source_failure_state(state_path)
    now = datetime.now().isoformat(timespec="seconds")

    for status in statuses:
        source_name = status.get("source", "")
        config = source_by_name.get(source_name, {})
        risk_level = config.get("risk_level", "")
        threshold = int(config.get("failure_alert_threshold", 3) or 3)
        status["risk_level"] = risk_level
        status["source_weight"] = config.get("source_weight", 1)
        status["failure_alert_threshold"] = threshold

        if status.get("status") in IGNORED_FAILURE_STATUSES:
            continue

        record = state.get(source_name, {"failure_streak": 0})
        if status.get("status") in SUCCESS_STATUSES:
            record["failure_streak"] = 0
        elif source_status_failed(status):
            record["failure_streak"] = int(record.get("failure_streak") or 0) + 1
        record["last_status"] = status.get("status", "")
        record["last_count"] = int(status.get("count") or 0)
        record["updated_at"] = now
        state[source_name] = record

        status["failure_streak"] = int(record.get("failure_streak") or 0)
        if risk_level == "高" and status["failure_streak"] >= threshold:
            status["alert"] = f"高风险源已连续 {status['failure_streak']} 次访问失败或受限，建议继续默认不选并复核接口。"

    save_source_failure_state(state, state_path)
    return statuses
