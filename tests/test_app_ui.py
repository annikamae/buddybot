from pathlib import Path

from streamlit.testing.v1 import AppTest


def test_motion_and_sound_controls_render_without_app_errors(tmp_path, monkeypatch):
    monkeypatch.setenv("BUDDY_DATA_DIR", str(tmp_path))
    app_path = Path(__file__).resolve().parents[1] / "main.py"

    app = AppTest.from_file(str(app_path), default_timeout=30).run()

    assert not app.exception
    assert any(toggle.label == "Soft interface sounds" for toggle in app.toggle)
    html_blocks = [element.value for element in app.html]
    initial_starfield = next(
        block for block in html_blocks if "buddy-starfield" in block
    )
    assert any("buddy-avatar-float" in block for block in html_blocks)

    next(
        button for button in app.button if "New conversation" in button.label
    ).click().run()

    assert not app.exception
    updated_starfield = next(
        element.value for element in app.html if "buddy-starfield" in element.value
    )
    assert updated_starfield != initial_starfield
