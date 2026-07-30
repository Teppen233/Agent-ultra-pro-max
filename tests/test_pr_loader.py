"""GitHub PR 与本地 Git 加载测试。"""

import subprocess
from pathlib import Path

import httpx
import pytest

from reviewcrew.config import Config
from reviewcrew.github.pr_loader import PRLoadError, load_pr
from reviewcrew.schemas import ReviewRequest


SIMPLE_DIFF = """diff --git a/app.py b/app.py
index 1111111..2222222 100644
--- a/app.py
+++ b/app.py
@@ -1 +1 @@
-VALUE = 1
+VALUE = 2
"""


@pytest.mark.asyncio
async def test_load_github_pr_returns_pr_data(respx_mock) -> None:
    """公开 GitHub PR 应被转换成统一 PRData。"""

    endpoint = "https://api.github.com/repos/acme/demo/pulls/7"
    route = respx_mock.get(endpoint)
    route.side_effect = [
        httpx.Response(
            200,
            json={
                "title": "更新配置",
                "body": "修正默认值",
                "user": {"login": "alice"},
                "base": {"sha": "base123"},
                "head": {"sha": "head123"},
            },
        ),
        httpx.Response(200, text=SIMPLE_DIFF),
    ]

    result = await load_pr(
        ReviewRequest(pr_url="https://github.com/acme/demo/pull/7"),
        Config(),
    )

    assert result.repository == "acme/demo"
    assert result.head_sha == "head123"
    assert result.files[0].path == "app.py"


@pytest.mark.asyncio
async def test_load_github_pr_omits_authorization_for_blank_token(
    monkeypatch: pytest.MonkeyPatch,
    respx_mock,
) -> None:
    """空白 Token 不能生成无效的 GitHub 授权头。"""

    monkeypatch.setenv("REVIEWCREW_GITHUB_TOKEN", "   ")
    endpoint = "https://api.github.com/repos/acme/demo/pulls/7"
    route = respx_mock.get(endpoint)
    route.side_effect = [
        httpx.Response(
            200,
            json={
                "title": "更新配置",
                "body": "修正默认值",
                "user": {"login": "alice"},
                "base": {"sha": "base123"},
                "head": {"sha": "head123"},
            },
        ),
        httpx.Response(200, text=SIMPLE_DIFF),
    ]

    await load_pr(
        ReviewRequest(pr_url="https://github.com/acme/demo/pull/7"),
        Config.from_env(),
    )

    assert all("authorization" not in call.request.headers for call in route.calls)


@pytest.mark.asyncio
async def test_load_local_repo_returns_diff(tmp_path: Path) -> None:
    """本地模式应解析两个引用之间的真实 Git diff。"""

    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "测试用户"], cwd=tmp_path, check=True)
    (tmp_path / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "app.py"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "初始"], cwd=tmp_path, check=True, capture_output=True)
    base = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, check=True, capture_output=True, text=True
    ).stdout.strip()
    (tmp_path / "app.py").write_text("VALUE = 2\n", encoding="utf-8")
    subprocess.run(["git", "add", "app.py"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "修改"], cwd=tmp_path, check=True, capture_output=True)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, check=True, capture_output=True, text=True
    ).stdout.strip()

    result = await load_pr(
        ReviewRequest(repo_path=str(tmp_path), base_ref=base, head_ref=head),
        Config(),
    )

    assert result.provider == "local"
    assert result.files[0].hunks[0].changed_lines == [1]


@pytest.mark.asyncio
async def test_load_local_repo_rejects_missing_ref(tmp_path: Path) -> None:
    """无效引用应返回中文可操作错误。"""

    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)

    with pytest.raises(PRLoadError, match="无法解析 Git 引用"):
        await load_pr(
            ReviewRequest(repo_path=str(tmp_path), base_ref="missing", head_ref="other"),
            Config(),
        )
