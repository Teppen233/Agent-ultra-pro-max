from __future__ import annotations

from reviewcrew.pipeline.diff_parser import parse_diff


def test_parse_modify_add_and_delete() -> None:
    raw = """diff --git a/a.py b/a.py
--- a/a.py
+++ b/a.py
@@ -1,1 +1,1 @@
-old
+new
diff --git a/new.py b/new.py
--- /dev/null
+++ b/new.py
@@ -0,0 +1,1 @@
+value = 1
diff --git a/gone.py b/gone.py
--- a/gone.py
+++ /dev/null
@@ -1,1 +0,0 @@
-gone = True
"""
    diffs = parse_diff(raw)
    assert [item.change_type for item in diffs] == ["modify", "add", "delete"]


def test_filters_lock_generated_and_whitespace() -> None:
    lock = """diff --git a/yarn.lock b/yarn.lock
--- a/yarn.lock
+++ b/yarn.lock
@@ -1 +1 @@
-a
+b
"""
    generated = """diff --git a/gen.py b/gen.py
--- a/gen.py
+++ b/gen.py
@@ -0,0 +1,2 @@
+# generated file
+value = 1
"""
    whitespace = """diff --git a/a.py b/a.py
--- a/a.py
+++ b/a.py
@@ -1 +1 @@
-x = 1
+x=1
"""
    assert parse_diff(lock) == []
    assert parse_diff(generated) == []
    assert parse_diff(whitespace) == []


def test_parse_rename() -> None:
    raw = """diff --git a/old.py b/new.py
similarity index 90%
rename from old.py
rename to new.py
--- a/old.py
+++ b/new.py
@@ -1 +1 @@
-old = 1
+new = 1
"""
    [diff] = parse_diff(raw)
    assert diff.change_type == "rename"
    assert diff.old_path == "old.py"
    assert diff.path == "new.py"
