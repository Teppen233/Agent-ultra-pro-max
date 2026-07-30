"""事件存储和订阅测试。"""

import asyncio
import importlib

import pytest

from reviewcrew.events import EventStore


def test_events_receive_monotonic_sequence(tmp_path) -> None:
    """同一运行的事件序号必须严格递增并可重新读取。"""

    store = EventStore(tmp_path)
    run_id = store.create_run()

    first = store.emit(run_id, "review.started", {})
    second = store.emit(run_id, "stage.started", {"stage": "loading_pr"})

    assert [first.sequence, second.sequence] == [1, 2]
    assert store.read(run_id) == [first, second]


def test_reserved_run_can_be_claimed_once_and_rejects_duplicate_or_dirty_directory(tmp_path) -> None:
    """预留目录只能原子 claim 一次，重复和非预留目录必须中文拒绝。"""

    store = EventStore(tmp_path)
    reserved = store.create_run()
    store.claim_run(reserved)
    with pytest.raises(RuntimeError, match="运行.*已"):
        store.claim_run(reserved)

    dirty = "run-dirty"
    dirty_dir = tmp_path / dirty
    dirty_dir.mkdir()
    (dirty_dir / "result.json").write_text("{}", encoding="utf-8")
    with pytest.raises(RuntimeError, match="预留"):
        store.claim_run(dirty)


def test_new_event_store_continues_existing_sequence_without_reset(tmp_path) -> None:
    """同一已 claim 运行由新 EventStore 追加事件时序号继续递增。"""

    first_store = EventStore(tmp_path)
    run_id = first_store.create_run()
    first = first_store.emit(run_id, "review.started", {})
    second_store = EventStore(tmp_path)
    second = second_store.emit(run_id, "review.completed", {"status": "completed"})

    assert first.sequence == 1
    assert second.sequence == 2


def test_tool_event_exposes_summary_but_removes_sensitive_fields(tmp_path) -> None:
    """工具公开事件只能保留固定摘要字段，不能落盘内部输入。"""

    store = EventStore(tmp_path)
    run_id = store.create_run()

    event = store.emit(
        run_id,
        "tool.completed",
        {
            "actor": "context_builder",
            "actor_type": "system",
            "tool_name": "context.search_symbol",
            "target": "OptimizedCursorPaginator",
            "summary": "检查 3 个文件，发现 2 处引用",
            "duration_ms": 184,
            "result_count": 2,
            "prompt": "不得公开",
            "reasoning": "不得公开",
            "api_key": "不得公开",
            "raw_response": "不得公开",
            "unexpected": "也不得公开",
        },
    )

    assert event.data == {
        "actor": "context_builder",
        "actor_type": "system",
        "tool_name": "context.search_symbol",
        "status": "completed",
        "target": "OptimizedCursorPaginator",
        "summary": "检查 3 个文件，发现 2 处引用",
        "duration_ms": 184,
        "result_count": 2,
        "context_id": None,
        "agent_id": None,
    }
    assert store.read(run_id)[0].data == event.data


def test_all_event_types_remove_nested_tokens_and_raw_model_fields(tmp_path) -> None:
    """旧事件也必须在统一边界移除嵌套令牌、授权头和模型原始字段。"""

    store = EventStore(tmp_path)
    run_id = store.create_run()

    event = store.emit(
        run_id,
        "stage.failed",
        {
            "stage": "loading_pr",
            "reason": "HTTPError",
            "github_token": "secret",
            "headers": {"Authorization": "Bearer secret"},
            "details": {"raw_response": "secret", "safe": "可公开"},
        },
    )

    assert event.data == {
        "stage": "loading_pr",
        "reason": "HTTPError",
        "headers": {},
        "details": {"safe": "可公开"},
    }


def test_tool_activity_completes_only_after_real_handle_completion(tmp_path) -> None:
    """工具发布器必须先记录开始，真实动作完成后才能记录成功。"""

    activity_module = importlib.import_module("reviewcrew.tool_activity")
    store = EventStore(tmp_path)
    run_id = store.create_run()
    publisher = activity_module.ToolActivityPublisher(store, run_id)

    handle = publisher.started(
        actor="context_builder",
        actor_type="system",
        tool_name="context.search_symbol",
        target="CursorPaginator",
        context_id="ctx-auth",
    )

    assert [event.type for event in store.read(run_id)] == ["tool.started"]
    handle.complete("检查 3 个文件，发现 2 处引用", result_count=2)
    events = store.read(run_id)
    assert [event.type for event in events] == ["tool.started", "tool.completed"]
    assert events[-1].data["duration_ms"] >= 0
    assert events[-1].data["result_count"] == 2


def test_tool_activity_degradation_is_not_published_as_a_tool_failure(tmp_path) -> None:
    """无法执行的可选能力必须以降级，而非真实失败，对外发布。"""

    activity_module = importlib.import_module("reviewcrew.tool_activity")
    store = EventStore(tmp_path)
    run_id = store.create_run()
    publisher = activity_module.ToolActivityPublisher(store, run_id)

    publisher.degraded(
        actor="github_pr_loader",
        actor_type="system",
        tool_name="git.load_diff",
        target="acme/repo#7",
        summary="GitHub 模式未提供本地仓库，已降级为远程差异。",
    )

    event = store.read(run_id)[0]
    assert event.type == "tool.degraded"
    assert event.data["status"] == "degraded"


def test_tool_event_clips_public_target_and_summary_instead_of_rejecting(tmp_path) -> None:
    """超长公开字符串应按契约裁剪，不能让事件持久化失败。"""

    store = EventStore(tmp_path)
    run_id = store.create_run()

    event = store.emit(
        run_id,
        "tool.failed",
        {
            "actor": "context_builder",
            "actor_type": "system",
            "tool_name": "context.read_file",
            "target": "x" * 400,
            "summary": "降级" * 400,
        },
    )

    assert len(event.data["target"]) == 240
    assert len(event.data["summary"]) == 500


@pytest.mark.parametrize(
    ("event_type", "payload", "expected"),
    [
        (
            "plan.published",
            {
                "risk_tags": ["authorization"],
                "context_ids": ["ctx-auth"],
                "shards": {"defect": ["ctx-auth"]},
                "budget_seconds": 240,
                "summary": "优先检查资源归属校验",
                "prompt": "不得公开",
                "raw_response": "不得公开",
                "unexpected": "不得公开",
            },
            {
                "risk_tags": ["authorization"],
                "context_ids": ["ctx-auth"],
                "shards": {"defect": ["ctx-auth"]},
                "budget_seconds": 240,
                "summary": "优先检查资源归属校验",
            },
        ),
        (
            "mailbox.message",
            {
                "sender": "defect:ctx-auth",
                "recipient": "verifier",
                "kind": "candidate_finding",
                "correlation_id": "finding-auth",
                "summary": "发布 high 候选 src/auth.py:10",
                "reasoning": "不得公开",
                "payload": {"full_source": "不得公开"},
            },
            {
                "sender": "defect:ctx-auth",
                "recipient": "verifier",
                "kind": "candidate_finding",
                "correlation_id": "finding-auth",
                "summary": "发布 high 候选 src/auth.py:10",
            },
        ),
    ],
)
def test_plan_and_mailbox_events_use_dedicated_public_whitelists(
    tmp_path,
    event_type,
    payload,
    expected,
) -> None:
    """计划与协作摘要必须使用各自白名单，不能借工具字段透传内部载荷。"""

    store = EventStore(tmp_path)
    run_id = store.create_run()

    event = store.emit(run_id, event_type, payload)

    assert event.data == expected


@pytest.mark.asyncio
async def test_subscriber_receives_new_event(tmp_path) -> None:
    """订阅者应收到订阅后产生的新事件。"""

    store = EventStore(tmp_path)
    run_id = store.create_run()
    iterator = store.subscribe(run_id)
    pending = asyncio.create_task(anext(iterator))
    await asyncio.sleep(0)

    emitted = store.emit(run_id, "agent.started", {"agent": "defect"})

    assert await asyncio.wait_for(pending, timeout=1) == emitted
