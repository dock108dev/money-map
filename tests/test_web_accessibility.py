import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_touch_layout_content_controls_are_at_least_44_pixels_tall() -> None:
    entrypoint = PROJECT_ROOT / "web" / "src" / "styles.css"
    imports = re.findall(r'@import "([^"\n]+)";', entrypoint.read_text(encoding="utf-8"))
    assert imports
    styles = "".join((entrypoint.parent / path).read_text(encoding="utf-8") for path in imports)

    expected_rule = """@media (max-width: 980px) {
  .app-shell .content-wrap :is(button, input, select, textarea, summary),
  .focused-dialog :is(button, input, select, textarea, summary) {
    min-height: 44px;
  }"""

    assert expected_rule in styles
