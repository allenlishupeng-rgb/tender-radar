def friendly_error_message(error: Exception | str) -> str:
    text = str(error)
    if "10053" in text or "ConnectionAborted" in text:
        return "对方网站中断了连接，已跳过。本次没有从该来源获取到新线索。"
    if "10054" in text or "ConnectionReset" in text:
        return "对方网站重置了连接，已跳过。本次没有从该来源获取到新线索。"
    if "Read timed out" in text or "timed out" in text:
        return "对方网站响应超时，已跳过。本次没有从该来源获取到新线索。"
    if "robots.txt" in text:
        return "robots.txt 不允许访问该页面，已按合规要求跳过。"
    if "频繁访问" in text:
        return "网站提示访问过于频繁，已按合规要求停止本次请求。"
    if not text:
        return "本次没有从该来源获取到新线索。"
    return text[:180]
