"""PR Loader 测试 —— 验证 GitHub 和本地仓库两种模式的数据加载。"""

from pathlib import Path

import httpx
import pytest
from reviewcrew.schemas import ReviewRequest


# ---- Fixtures ----

GITHUB_PR_FIXTURE = {
    "number": 7,
    "title": "修复 SQL 注入漏洞",
    "body": "增加了输入过滤和参数化查询",
    "head": {"sha": "head123456"},
    "base": {"sha": "base654321"},
    "user": {"login": "dev-user"},
    "head": {"repo": {"full_name": "acme/demo"}, "sha": "head123456"},
    "base": {"repo": {"full_name": "acme/demo"}, "sha": "base654321"},
    "state": "open",
}


GITHUB_DIFF_FIXTURE = """diff --git a/src/login.py b/src/login.py
index abc..def 100644
--- a/src/login.py
+++ b/src/login.py
@@ -10,3 +10,4 @@ def authenticate(username, password):
-    query = "SELECT * FROM users WHERE name='" + username + "'"
+    query = "SELECT * FROM users WHERE name=?"
+    cursor.execute(query, (username,))
"""


# ---- GitHub Loader ----

@pytest.mark.asyncio
async def test_load_github_pr_returns_pr_data(respx_mock):
    """GitHub PR URL 应正确返回 PRData。"""
    from reviewcrew.config import Config
    from reviewcrew.github.pr_loader import load_pr

    config = Config.from_env()

    # Mock GitHub API — 更具体的 diff mock 放在前面
    respx_mock.get(
        "https://api.github.com/repos/acme/demo/pulls/7",
        headers={"Accept": "application/vnd.github.v3.diff"},
    ).mock(return_value=httpx.Response(200, text=GITHUB_DIFF_FIXTURE))

    respx_mock.get(
        "https://api.github.com/repos/acme/demo/pulls/7"
    ).mock(return_value=httpx.Response(200, json=GITHUB_PR_FIXTURE))

    result = await load_pr(
        ReviewRequest(pr_url="https://github.com/acme/demo/pull/7"), config
    )
    assert result.provider == "github"
    assert result.head_sha == "head123456"
    assert result.title == "修复 SQL 注入漏洞"
    assert len(result.files) == 1


@pytest.mark.asyncio
async def test_load_github_pr_handles_404(respx_mock):
    """GitHub PR 不存在时应抛出中文错误。"""
    from reviewcrew.config import Config
    from reviewcrew.github.pr_loader import load_pr

    config = Config.from_env()

    respx_mock.get(
        "https://api.github.com/repos/acme/demo/pulls/999"
    ).mock(return_value=httpx.Response(404))

    with pytest.raises(Exception, match="PR 不存在|404|找不到"):
        await load_pr(
            ReviewRequest(pr_url="https://github.com/acme/demo/pull/999"), config
        )


# ---- 本地 Loader ----

@pytest.mark.asyncio
async def test_load_local_repo_rejects_missing_path():
    """本地仓库路径不存在时应抛出中文错误。"""
    from reviewcrew.config import Config
    from reviewcrew.github.pr_loader import load_pr

    config = Config.from_env()

    with pytest.raises(Exception, match="不存在|找不到|路径"):
        await load_pr(
            ReviewRequest(
                repo_path="/nonexistent/path",
                base_ref="main",
                head_ref="feature/x",
            ),
            config,
        )


@pytest.mark.asyncio
async def test_load_local_repo_rejects_missing_refs(tmp_path: Path):
    """本地仓库 ref 不存在时应抛出中文错误。"""
    import subprocess
    from reviewcrew.config import Config
    from reviewcrew.github.pr_loader import load_pr

    config = Config.from_env()

    # 初始化一个 git 仓库
    repo_dir = tmp_path / "test_repo"
    repo_dir.mkdir()
    subprocess.run(["git", "init"], cwd=repo_dir, capture_output=True)
    (repo_dir / "dummy.txt").write_text("test\n")
    subprocess.run(["git", "add", "."], cwd=repo_dir, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=repo_dir,
        capture_output=True,
        env={
            "GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "test@test.com",
            "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "test@test.com",
        },
    )
    # 获取实际分支名
    branch_result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=repo_dir, capture_output=True, text=True
    )
    base_branch = branch_result.stdout.strip()

    with pytest.raises(Exception, match="不存在|找不到|ref|引用"):
        await load_pr(
            ReviewRequest(
                repo_path=str(repo_dir),
                base_ref=base_branch,
                head_ref="nonexistent-branch",
            ),
            config,
        )


@pytest.mark.asyncio
async def test_load_local_repo_with_git_diff(tmp_path: Path):
    """本地仓库使用 git diff 应正确加载 PRData。"""
    import subprocess
    from reviewcrew.config import Config
    from reviewcrew.github.pr_loader import load_pr

    config = Config.from_env()
    repo_dir = tmp_path / "test_repo"

    # 初始化仓库并创建 base 提交
    repo_dir.mkdir()
    env = {
        "GIT_AUTHOR_NAME": "test",
        "GIT_AUTHOR_EMAIL": "test@test.com",
        "GIT_COMMITTER_NAME": "test",
        "GIT_COMMITTER_EMAIL": "test@test.com",
    }
    subprocess.run(["git", "init"], cwd=repo_dir, capture_output=True)
    (repo_dir / "hello.py").write_text("print('hello')\n")
    subprocess.run(["git", "add", "."], cwd=repo_dir, capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=repo_dir, capture_output=True, env=env)
    # 获取当前分支名
    branch_result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=repo_dir, capture_output=True, text=True
    )
    base_branch = branch_result.stdout.strip() or "main"

    # 创建 head 分支并修改
    subprocess.run(["git", "checkout", "-b", "feature/x"], cwd=repo_dir, capture_output=True)
    (repo_dir / "hello.py").write_text("print('hello world')\n")
    subprocess.run(["git", "add", "."], cwd=repo_dir, capture_output=True)
    subprocess.run(["git", "commit", "-m", "change"], cwd=repo_dir, capture_output=True, env=env)

    result = await load_pr(
        ReviewRequest(
            repo_path=str(repo_dir),
            base_ref=base_branch,
            head_ref="feature/x",
        ),
        config,
    )
    assert result.provider == "local"
    assert len(result.files) == 1
    assert result.files[0].path == "hello.py"
    assert result.base_sha != result.head_sha


# ---- URL 解析 ----

def test_parse_github_pr_url():
    """GitHub PR URL 应正确解析 owner/repo/number。"""
    from reviewcrew.github.pr_loader import parse_pr_url

    owner, repo, number = parse_pr_url(
        "https://github.com/acme/demo/pull/7"
    )
    assert owner == "acme"
    assert repo == "demo"
    assert number == 7


def test_parse_github_pr_url_with_query():
    """带查询参数的 PR URL 应正确解析。"""
    from reviewcrew.github.pr_loader import parse_pr_url

    owner, repo, number = parse_pr_url(
        "https://github.com/acme/demo/pull/7?tab=commits"
    )
    assert owner == "acme"
    assert repo == "demo"
    assert number == 7


def test_parse_github_pr_url_invalid():
    """无效的 PR URL 应抛出异常。"""
    from reviewcrew.github.pr_loader import parse_pr_url

    with pytest.raises(ValueError):
        parse_pr_url("https://gitlab.com/acme/demo/merge_requests/1")
