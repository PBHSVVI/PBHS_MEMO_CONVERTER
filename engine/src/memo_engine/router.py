class RoutingNotReady(RuntimeError):
    pass


def route_task(task: dict):
    raise RoutingNotReady("AI routing begins in Phase 3, not Phase 0")
