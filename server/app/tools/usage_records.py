"""
设备使用记录查询工具
根据用户ID和时间范围返回模拟的清扫数据
在实际生产环境中，此处应对接真实的设备遥测数据库
"""
import hashlib
import random
from datetime import datetime, timedelta

from langchain_core.tools import tool

from ..common.logger import get_logger

logger = get_logger(__name__)


def _generate_deterministic_seed(user_id: str) -> int:
    """基于用户ID生成确定性随机种子，使同一用户的数据保持一致"""
    hash_bytes = hashlib.md5(user_id.encode()).digest()
    return int.from_bytes(hash_bytes[:4], "big")


def _parse_date_range(start_date: str, end_date: str) -> tuple[datetime, datetime, int]:
    """
    解析日期范围，支持多种格式
    返回 (start_datetime, end_datetime, days_diff)
    """
    formats = [
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%Y年%m月%d日",
        "%Y%m%d",
    ]

    start_dt = None
    end_dt = None

    for fmt in formats:
        try:
            start_dt = datetime.strptime(start_date.strip(), fmt)
            break
        except ValueError:
            continue

    for fmt in formats:
        try:
            end_dt = datetime.strptime(end_date.strip(), fmt)
            break
        except ValueError:
            continue

    if not start_dt:
        start_dt = datetime.now() - timedelta(days=7)
    if not end_dt:
        end_dt = datetime.now()

    days = max(1, (end_dt - start_dt).days)
    return start_dt, end_dt, days


@tool
def query_usage_records(user_id: str, start_date: str, end_date: str) -> str:
    """
    查询指定用户在指定时间范围内的设备使用记录。
    返回清扫时长、清扫面积、故障记录、耗材损耗等数据。

    使用场景：
    - 用户查询自己的清扫历史
    - 生成清扫报告时需要统计数据
    - 查看耗材使用情况

    Args:
        user_id: 用户唯一标识（通过 get_user_id 工具获取）
        start_date: 查询起始日期，格式 YYYY-MM-DD（如 2026-06-01）
        end_date: 查询结束日期，格式 YYYY-MM-DD（如 2026-07-08）
    """
    logger.info(f"查询使用记录: user={user_id[:20]}..., {start_date} ~ {end_date}")

    # 解析日期
    start_dt, end_dt, days = _parse_date_range(start_date, end_date)

    # 基于用户ID生成确定性随机数据
    seed = _generate_deterministic_seed(user_id)
    rng = random.Random(seed)

    # 基础数据（随天数变化）
    daily_avg_area = 60 + rng.randint(-20, 40)  # 日均清扫面积
    daily_avg_time = 45 + rng.randint(-15, 30)  # 日均清扫时长（分钟）
    sessions_per_day = 1.0 + rng.random() * 0.5  # 日均清扫次数

    total_area = round(daily_avg_area * days * (0.8 + rng.random() * 0.4), 1)
    total_time = round(daily_avg_time * days * (0.8 + rng.random() * 0.4) / 60, 1)
    total_sessions = max(1, int(sessions_per_day * days))

    # 累计使用时长（假设设备已使用 180-720 天）
    total_days_used = 180 + rng.randint(0, 540)
    cumulative_hours = round(total_days_used * daily_avg_time / 60 * (0.7 + rng.random() * 0.3), 1)

    # --- 基于知识库 v5.0 的真实产品线（含上市时间） ---
    models_pool = [
        {"name": "SmartClean S1", "firmware": "v1.8.3", "launch": "2024-03"},
        {"name": "SmartClean S2", "firmware": "v2.2.1", "launch": "2025-05"},
        {"name": "SmartClean S1 Pro", "firmware": "v2.4.1", "launch": "2024-06"},
        {"name": "SmartClean X1", "firmware": "v3.0.5", "launch": "2024-09"},
        {"name": "SmartClean X1 Pro Max", "firmware": "v3.1.0", "launch": "2024-11"},
        {"name": "SmartClean X2 Lite", "firmware": "v2.8.0", "launch": "2025-08"},
        {"name": "SmartClean T3", "firmware": "v2.0.5", "launch": "2024-04"},
        {"name": "SmartClean T5", "firmware": "v3.5.1", "launch": "2026-01"},
        {"name": "SmartClean G2", "firmware": "v4.0.2", "launch": "2024-07"},
        {"name": "SmartClean G3", "firmware": "v4.2.0", "launch": "2025-10"},
    ]
    picked = rng.choice(models_pool)
    model = picked["name"]
    firmware = picked["firmware"]

    # --- 基于知识库错误码（E01-E15 + W01-W06）的真实故障记录 ---
    error_options = [
        ("无", 0.50),
        ("E01-主刷缠绕(已修复)", 0.06),
        ("E04-尘盒未安装(已修复)", 0.06),
        ("E07-传感器脏污(已修复)", 0.05),
        ("E08-充电异常(已修复)", 0.04),
        ("E10-WiFi断连(已恢复)", 0.04),
        ("E15-过热保护(已恢复)", 0.03),
        ("W01-尘盒已满(已清理)", 0.07),
        ("W02-HEPA滤网即将到期", 0.06),
        ("W03-边刷磨损", 0.04),
        ("W05-电池健康度低于80%", 0.03),
        ("W06-固件更新可用", 0.02),
    ]
    codes, weights = zip(*error_options)
    recent_error = rng.choices(list(codes), weights=list(weights), k=1)[0]

    # --- 耗材使用（基于知识库配件表） ---
    # 有主刷/边刷的机型：S1/S2/S1 Pro/X1/X1 Pro Max/X2 Lite/T5/G2/G3
    # T3 无主刷/边刷；有集尘袋的：S1 Pro(选配)/X1(选配)/X1 Pro Max/X2 Lite/T5
    has_brush = "T3" not in model
    has_bag = any(m in model for m in ["X1 Pro Max", "X2 Lite", "T5"]) or (
        any(m in model for m in ["S1 Pro", "X1"]) and rng.random() > 0.5
    )
    main_brush_hours = round(cumulative_hours * (0.8 + rng.random() * 0.4), 1) if has_brush else 0
    side_brush_hours = round(cumulative_hours * (0.8 + rng.random() * 0.4), 1) if has_brush else 0
    filter_hours = round(cumulative_hours * (0.65 + rng.random() * 0.35), 1)
    dust_bag_pct = round(20 + rng.random() * 60, 1) if has_bag else 0

    # 电池健康度（2-3年寿命，按使用天数线性衰减 + 随机波动）
    battery_health = round(max(65, 100 - (total_days_used / 365) * 10 + rng.uniform(-5, 3)), 1)

    # 常用模式（与知识库一致：标准/强力/静音/快速）
    mode_names = ["标准模式", "强力模式", "静音模式", "快速清扫"]
    weights_raw = [40 + rng.randint(0, 20), 15 + rng.randint(0, 20), 10 + rng.randint(0, 10), 0]
    weights_raw[3] = max(0, 100 - sum(weights_raw[:3]))
    mode_dist = {name: f"{w}%" for name, w in zip(mode_names, weights_raw)}

    # 组装返回结果
    report = f"""## 📊 设备使用记录

**查询范围**: {start_dt.strftime('%Y-%m-%d')} ~ {end_dt.strftime('%Y-%m-%d')}（共 {days} 天）
**设备型号**: {model}
**固件版本**: {firmware}

### 当前查询区间统计
| 指标 | 数值 |
|------|------|
| 累计清扫时长 | {total_time} 小时 |
| 累计清扫面积 | {total_area} 平方米 |
| 清扫次数 | {total_sessions} 次 |
| 平均单次清扫面积 | {round(total_area / total_sessions, 1)} 平方米 |
| 平均单次清扫时长 | {round(total_time * 60 / total_sessions, 1)} 分钟 |

### 设备全局统计
| 指标 | 数值 |
|------|------|
| 累计使用天数 | {total_days_used} 天 |
| 累计清扫总时长 | {cumulative_hours} 小时 |
| 电池健康度 | {battery_health}% |
| 近期故障 | {recent_error} |

### 常用模式分布
| 模式 | 占比 |
|------|------|
| 标准模式 | {mode_dist['标准模式']} |
| 强力模式 | {mode_dist['强力模式']} |
| 静音模式 | {mode_dist['静音模式']} |
| 快速清扫 | {mode_dist['快速清扫']} |

### 耗材使用情况
| 耗材 | 已用时长 | 建议更换周期 |
|------|----------|-------------|
| 主刷 | {main_brush_hours} 小时 | 300 小时 |
| 边刷 | {side_brush_hours} 小时 | 200 小时 |
| 滤网 | {filter_hours} 小时 | 150 小时 |
| 尘袋 | 已用 {dust_bag_pct}% | 100% 容量 |

---
> 💡 提示：以上为模拟数据，实际使用数据请连接设备后查看。
"""
    return report
