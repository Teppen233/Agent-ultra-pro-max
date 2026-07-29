"""Mailbox 测试 —— 验证 Agent 间消息的路由、幂等、过期和持久化。"""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


def make_team_message(**overrides):
    """创建合法的 TeamMessage 测试数据。"""
    from reviewcrew.schemas import TeamMessage

    defaults = {
        "id": "msg-001",
        "run_id": "run-test",
        "sequence": 1,
        "timestamp": datetime.now(timezone.utc),
        "sender": "defect-1",
        "recipient": "verifier",
        "kind": "candidate_finding",
        "payload": {"finding_id": "f-001"},
    }
    defaults.update(overrides)
    return TeamMessage(**defaults)


@pytest.mark.asyncio
async def test_mailbox_routes_private_message_once(tmp_path: Path):
    """私信必须精确投递到指定收件人，重复消息幂等处理。"""
    from reviewcrew.team.mailbox import Mailbox

    mailbox = Mailbox(tmp_path)
    await mailbox.start()

    message = make_team_message(recipient="verifier", kind="candidate_finding")
    await mailbox.publish(message)
    await mailbox.publish(message)  # 重复发送

    received = await mailbox.receive_one("verifier", timeout=1.0)
    assert received is not None
    assert received.id == message.id
    assert mailbox.delivered_count(message.id, role="verifier") == 1

    await mailbox.close()


@pytest.mark.asyncio
async def test_mailbox_expired_message_not_delivered(tmp_path: Path):
    """已过期的消息不应被投递，receive_one 超时返回 None。"""
    from reviewcrew.team.mailbox import Mailbox

    mailbox = Mailbox(tmp_path)
    await mailbox.start()

    expired = make_team_message(
        id="msg-expired",
        recipient="verifier",
        kind="verification_request",
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=10),
    )
    await mailbox.publish(expired)

    # 过期消息被跳过，超时应返回 None
    received = await mailbox.receive_one("verifier", timeout=1.0)
    assert received is None

    await mailbox.close()


@pytest.mark.asyncio
async def test_mailbox_broadcast_delivered_to_subscribers(tmp_path: Path):
    """广播消息应投递给所有已订阅的角色。"""
    from reviewcrew.team.mailbox import Mailbox

    mailbox = Mailbox(tmp_path)
    await mailbox.start()

    # 注册角色
    for role in ["defect", "intent", "verifier"]:
        mailbox.register(role)

    broadcast = make_team_message(
        id="msg-bc",
        recipient="*",
        kind="budget_warning",
        payload={"remaining_seconds": 120},
    )
    await mailbox.publish(broadcast)

    for role in ["defect", "intent", "verifier"]:
        received = await mailbox.receive_one(role, timeout=1.0)
        assert received is not None
        assert received.id == "msg-bc"

    await mailbox.close()


@pytest.mark.asyncio
async def test_mailbox_agent_cannot_read_others_private(tmp_path: Path):
    """Agent 不能读取其他 Agent 的私信。"""
    from reviewcrew.team.mailbox import Mailbox

    mailbox = Mailbox(tmp_path)
    await mailbox.start()

    private = make_team_message(
        id="msg-private",
        sender="defect-1",
        recipient="verifier",
        kind="candidate_finding",
    )
    await mailbox.publish(private)

    # intent 不应收到该消息
    received = await mailbox.receive_one("intent", timeout=1.0)
    assert received is None

    await mailbox.close()


@pytest.mark.asyncio
async def test_mailbox_persists_to_jsonl(tmp_path: Path):
    """消息必须持久化到 mailbox.jsonl。"""
    from reviewcrew.team.mailbox import Mailbox

    mailbox = Mailbox(tmp_path)
    await mailbox.start(run_id="run-test")

    message = make_team_message()
    await mailbox.publish(message)
    await mailbox.close()

    mailbox_file = tmp_path / "run-test" / "mailbox.jsonl"
    assert mailbox_file.exists()
    content = mailbox_file.read_text().strip()
    assert "msg-001" in content


@pytest.mark.asyncio
async def test_mailbox_correlation_id_tracking(tmp_path: Path):
    """关联消息的 correlation_id 应正确维护。"""
    from reviewcrew.team.mailbox import Mailbox

    mailbox = Mailbox(tmp_path)
    await mailbox.start()

    request = make_team_message(
        id="msg-req",
        recipient="defect-1",
        kind="verification_request",
    )
    response = make_team_message(
        id="msg-resp",
        recipient="verifier",
        kind="evidence_response",
        correlation_id="msg-req",
    )
    await mailbox.publish(request)
    await mailbox.publish(response)

    # 收件人接收消息
    r1 = await mailbox.receive_one("defect-1", timeout=1.0)
    r2 = await mailbox.receive_one("verifier", timeout=1.0)
    assert r1 is not None
    assert r2 is not None
    # 验证关联关系
    assert mailbox.get_correlation("msg-resp") == "msg-req"

    await mailbox.close()
