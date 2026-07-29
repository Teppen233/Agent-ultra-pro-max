"""Agent Team Mailbox 测试。"""

from datetime import UTC, datetime, timedelta

import pytest

from reviewcrew.schemas import TeamMessage
from reviewcrew.team.blackboard import EvidenceBlackboard
from reviewcrew.team.mailbox import Mailbox
from reviewcrew.team.publisher import MessagePublisher


def make_message(
    *,
    message_id: str = "msg-1",
    recipient: str = "verifier",
    kind: str = "candidate_finding",
    expires_at: datetime | None = None,
) -> TeamMessage:
    """构造类型化团队消息。"""

    return TeamMessage(
        id=message_id,
        run_id="run-1",
        sequence=1,
        timestamp=datetime.now(UTC),
        sender="defect",
        recipient=recipient,
        kind=kind,
        expires_at=expires_at,
        payload={"finding_id": "finding-1"},
    )


@pytest.mark.asyncio
async def test_mailbox_routes_private_message_once(tmp_path) -> None:
    """重复发布同一消息时，目标 Agent 只能收到一次。"""

    mailbox = Mailbox(tmp_path, "run-1")
    message = make_message()

    await mailbox.publish(message)
    await mailbox.publish(message)

    received = await mailbox.receive_one("verifier", timeout=0.1)
    assert received.id == message.id
    assert mailbox.delivered_count(message.id) == 1


@pytest.mark.asyncio
async def test_mailbox_drops_expired_message(tmp_path) -> None:
    """过期补证消息不得进入收件箱。"""

    mailbox = Mailbox(tmp_path, "run-1")
    expired = make_message(
        kind="verification_request",
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )

    assert await mailbox.publish(expired) is False
    with pytest.raises(TimeoutError):
        await mailbox.receive_one("verifier", timeout=0.01)


@pytest.mark.asyncio
async def test_mailbox_broadcasts_to_subscribers(tmp_path) -> None:
    """广播消息应进入所有已注册角色的收件箱。"""

    mailbox = Mailbox(tmp_path, "run-1")
    mailbox.register("defect")
    mailbox.register("intent")
    message = make_message(recipient="*")

    await mailbox.publish(message)

    assert (await mailbox.receive_one("defect", timeout=0.1)).id == message.id
    assert (await mailbox.receive_one("intent", timeout=0.1)).id == message.id


def test_blackboard_applies_message_idempotently() -> None:
    """共享黑板重复应用消息时不得重复保存事实。"""

    blackboard = EvidenceBlackboard("run-1")
    message = make_message()

    blackboard.apply(message)
    blackboard.apply(message)

    assert len(blackboard.messages) == 1


@pytest.mark.asyncio
async def test_publisher_persists_redacted_candidate_but_delivers_full_payload(tmp_path) -> None:
    """磁盘审计消息必须脱敏，但 Verifier 的内存队列仍需完整 Finding。"""

    mailbox = Mailbox(tmp_path, "run-redacted")
    mailbox.register("verifier")
    blackboard = EvidenceBlackboard("run-redacted")
    publisher = MessagePublisher(mailbox=mailbox, blackboard=blackboard)
    payload = {
        "finding": {
            "id": "finding-1",
            "title": "公开标题",
            "reasoning_summary": "私密思维链 sensitive-chain",
            "description": "不得保存完整 Prompt 或模型响应 sensitive-response",
        }
    }

    await publisher.publish(
        sender="defect:ctx-1",
        recipient="verifier",
        kind="candidate_finding",
        key="candidate:finding-1",
        payload=payload,
    )

    delivered = await mailbox.receive_one("verifier", timeout=0.1)
    persisted = (tmp_path / "run-redacted" / "mailbox.jsonl").read_text(encoding="utf-8")
    assert delivered.payload["finding"]["reasoning_summary"] == "私密思维链 sensitive-chain"
    assert blackboard.messages[0].payload["finding"]["reasoning_summary"] == "私密思维链 sensitive-chain"
    for forbidden in ("reasoning_summary", "sensitive-chain", "Prompt", "响应", "sensitive-response", "思维链"):
        assert forbidden not in persisted
