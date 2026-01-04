from truenas_mcp_server.http_api.tool_gating import FilterContext, TaskTypeFilter, Tool


def _make_tool(name: str, task_types: list[str]) -> Tool:
    return Tool(
        name=name,
        description=f"{name} description",
        method="rpc",
        path=f"/tools/{name}",
        request_schema=None,
        response_schema={"type": "object"},
        task_types=task_types,
    )


def test_task_type_filter_accepts_alias_header() -> None:
    filter_instance = TaskTypeFilter({"storage-ops": ["list_pools"]})
    context = FilterContext(task_type="storage", request_id="req-1")
    tools = {
        "list_pools": _make_tool("list_pools", ["storage-ops"]),
        "create_user": _make_tool("create_user", ["user-ops"]),
    }

    filtered = filter_instance.apply(tools, context)

    assert set(filtered.keys()) == {"list_pools"}


def test_task_type_filter_normalizes_mixed_case_aliases() -> None:
    filter_instance = TaskTypeFilter({"user-ops": ["create_user"]})
    context = FilterContext(task_type="User_Ops", request_id="req-2")
    tools = {
        "create_user": _make_tool("create_user", ["user-ops"]),
        "list_pools": _make_tool("list_pools", ["storage-ops"]),
    }

    filtered = filter_instance.apply(tools, context)

    assert set(filtered.keys()) == {"create_user"}
