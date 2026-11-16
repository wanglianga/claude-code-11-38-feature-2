"""模型 → dict 序列化辅助。"""

import enum
from datetime import datetime


def to_dict(obj, extra: dict | None = None) -> dict:
    out = {}
    for col in obj.__table__.columns:
        val = getattr(obj, col.name)
        if isinstance(val, enum.Enum):
            val = val.value
        elif isinstance(val, datetime):
            val = val.isoformat()
        out[col.name] = val
    if extra:
        out.update(extra)
    return out
