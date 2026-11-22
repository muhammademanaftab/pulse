import importlib.util
import tempfile
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "rules", Path("skills/rules/rules.py")
)
rules = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rules)

def test_collects_only_rule_bullets():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        month = root / "2026-11"
        month.mkdir()
        note = month / "2026-11-22.md"
        note.write_text(
            """## Work log
### **Web App**
- Rule: Use Python 3.12 for scripts.
- Learned: The deployment uses Linux.
### **Other Project**
- Rule: Ignore this project.
""",
            encoding="utf-8",
        )
        result = rules.collect_rules(tmp, "Web App")
        assert result == [{
            "date": "2026-11-22",
            "rule": "Use Python 3.12 for scripts."
        }]

def test_empty_notes():
    with tempfile.TemporaryDirectory() as tmp:
        assert rules.collect_rules(tmp, "Web App") == []

test_collects_only_rule_bullets()
test_empty_notes()
print("PASS: rules collector tests")
