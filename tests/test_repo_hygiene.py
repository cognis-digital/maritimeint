"""Repo-hygiene checks: package metadata, CI/labeler config, and the demo runner."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as fh:
        return fh.read()


class TestPackageMetadata:
    def test_version_exposed(self):
        import maritimeint
        assert isinstance(maritimeint.TOOL_VERSION, str) and maritimeint.TOOL_VERSION

    def test_tool_name(self):
        import maritimeint
        assert maritimeint.TOOL_NAME == "maritimeint"

    def test_version_file_matches(self):
        import maritimeint
        vfile = _read("VERSION").strip()
        # VERSION file and package version should agree (allow a leading 'v')
        assert vfile.lstrip("v") == maritimeint.TOOL_VERSION.lstrip("v")


class TestLabelerV5:
    """Migrated actions/labeler v5: each label maps to a list of match rules
    using `changed-files` / `any-glob-to-any-file`, not the bare v4 glob list."""

    def test_labeler_present(self):
        assert os.path.exists(os.path.join(REPO, ".github", "labeler.yml"))

    def test_uses_v5_schema(self):
        text = _read(".github", "labeler.yml")
        try:
            import yaml  # PyYAML is optional; fall back to a text check without it
        except ImportError:
            # v5 rules use the changed-files / any-glob-to-any-file form
            assert "changed-files" in text
            assert "any-glob-to-any-file" in text
            return
        data = yaml.safe_load(text)
        for label, rules in data.items():
            assert isinstance(rules, list), f"{label} must be a list of rules (v5)"
            assert any("changed-files" in r for r in rules if isinstance(r, dict)), \
                f"{label} must use the v5 changed-files form"

    def test_label_workflow_pins_v5(self):
        text = _read(".github", "workflows", "label.yml")
        assert "actions/labeler@v5" in text


class TestCIConfig:
    def test_ci_runs_pytest(self):
        assert "pytest" in _read(".github", "workflows", "ci.yml")

    def test_codeql_present(self):
        assert os.path.exists(os.path.join(REPO, ".github", "workflows", "codeql.yml"))


class TestDemoRunner:
    def test_run_all_lists_scenarios(self):
        sys.path.insert(0, os.path.join(REPO, "demos"))
        import run_all
        assert len(run_all.SCENARIOS) >= 5

    def test_all_scenario_modules_exist(self):
        sys.path.insert(0, os.path.join(REPO, "demos"))
        import run_all
        for name in run_all.SCENARIOS:
            assert os.path.exists(os.path.join(REPO, "demos", name + ".py")), name
