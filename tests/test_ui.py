"""HTML building blocks: escaping, initials, score bands."""

import ui


def test_everything_is_escaped_once():
    html = ui.mentor_card({"name": "<script>x</script>", "title": "A &amp; B", "bio": "<b>bold</b>",
                           "expertise": ["<i>"], "status": "Available", "availability_hours": 6})
    assert "<script>" not in html and "<b>" not in html and "<i>" not in html
    assert "&lt;script&gt;" in html
    assert "A &amp; B" in html and "&amp;amp;" not in html  # API text arrives escaped: not double-escaped


def test_initials_skip_titles_and_punctuation():
    assert ui.initials("Dr. Elena Vance") == "EV"
    assert ui.initials("Dr. L. Wong") == "LW"
    assert ui.initials("Priya") == "P"
    assert ui.initials("") == "?"


def test_avatar_colour_is_stable_per_name():
    assert ui.avatar("Sarah Chen") == ui.avatar("Sarah Chen")


def test_score_bands_match_the_evaluation_thresholds():
    assert [ui.score_band(s)[1] for s in (0, 49, 50, 79, 80, 100)] == \
           ["Weak", "Weak", "Possible", "Possible", "Strong", "Strong"]


def test_grade_meters():
    html = ui.grade_meters({"domain_fit": 5, "need_fit": 3, "market_fit": 1})
    assert html.count("●") == 15 and "Domain" in html
    assert "unavailable" in ui.grade_meters(None)


def test_every_coloured_rule_sets_text_and_background():
    # Guards the dark-mode bug: a rule with a background must also set a text colour
    import re
    for rule in re.findall(r"\.[\w-]+\s*\{[^}]*\}", ui.CSS):
        if "background" in rule:
            assert "color:" in rule.replace("background", ""), rule
