from ..domain.models import Risk, Tool


def allow(tool: Tool, allow_external_writes: bool) -> tuple[bool, str]:
    if tool.risk is Risk.DESTRUCTIVE:
        return False, "destructive tools are disabled"
    if tool.risk is Risk.READ:
        return True, "read-only"
    if tool.risk is Risk.WRITE and allow_external_writes:
        return True, "operator policy allows writes"
    return False, "human approval required"
