"""测试静态审查引擎 —— 验证规则命中。"""
import os
import subprocess
from pathlib import Path

from reviewcrew.diff.parser import parse_unified_diff
from reviewcrew.schemas import PRData
from reviewcrew.pipeline.static_reviewer import run_static_review

# 创建测试仓库
repo = Path("/tmp/test-sec-review")
repo.mkdir(parents=True, exist_ok=True)
os.chdir(str(repo))

# 初始化
subprocess.run(["git", "init"], capture_output=True)
subprocess.run(["git", "checkout", "-b", "main"], capture_output=True)

# 初版代码（无问题）
(repo / "app.py").write_text("print('hello')\n")
subprocess.run(["git", "add", "."], capture_output=True)
subprocess.run(
    ["git", "commit", "-m", "init"],
    capture_output=True,
    env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t.com",
         "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t.com"},
)

# 有问题版本
(repo / "app.py").write_text("""import sqlite3

DB_PASSWORD = "admin123456"
API_KEY = "sk-abcdefghijklmnop"

def login(username, password):
    query = "SELECT * FROM users WHERE name='" + username + "'"
    return db.execute(query)

def process(data):
    try:
        return data["val"] / 0
    except:
        pass

def read_file(path):
    f = open(path)
    return f.read()
""")

subprocess.run(["git", "add", "app.py"], capture_output=True)
subprocess.run(
    ["git", "commit", "-m", "add vulnerabilities"],
    capture_output=True,
    env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t.com",
         "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t.com"},
)

# 获取 diff
r = subprocess.run(["git", "diff", "HEAD~1..HEAD"], capture_output=True, text=True)
diff_text = r.stdout

files = parse_unified_diff(diff_text)
pr = PRData(
    provider="local", repository="test", title="Test", description="",
    base_sha="a", head_sha="b", files=files, raw_diff=diff_text,
)

findings, hits = run_static_review(pr)
print(f"\n命中规则: {hits}")
for f in findings:
    print(f"  [{f.severity}] {f.title} - {f.file}:{f.line_start}")
    print(f"    描述: {f.description}")
