from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_touch_layout_content_controls_are_at_least_44_pixels_tall() -> None:
    styles = (PROJECT_ROOT / "web" / "src" / "styles.css").read_text(encoding="utf-8")

    expected_rule = """@media (max-width: 980px) {
  .app-shell .content-wrap :is(button, input, select, textarea, summary),
  .focused-dialog :is(button, input, select, textarea, summary) {
    min-height: 44px;
  }"""

    assert expected_rule in styles
