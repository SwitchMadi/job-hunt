"""Convert Slack message timestamps to integer epoch milliseconds."""


def slack_ts_to_epoch_ms(ts: str) -> int:
    """
    Slack `ts` is Unix time as seconds with fractional part (e.g. "1735689600.000200").
    """
    if not ts:
        return 0
    try:
        return int(round(float(ts) * 1000))
    except (TypeError, ValueError):
        return 0
