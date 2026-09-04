from pathlib import Path

from story_scraper.resolve import resolve_config
from story_scraper.templates import find_template, iter_templates, load_template

TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "templates"


def test_find_template_by_bare_name():
    assert find_template("royalroad", TEMPLATE_DIR) == TEMPLATE_DIR / "royalroad.yml"


def test_find_template_missing_returns_none():
    assert find_template("does-not-exist", TEMPLATE_DIR) is None


def test_load_royalroad_template():
    data = load_template(TEMPLATE_DIR / "royalroad.yml")
    assert data["container"] == "div.chapter-content"
    assert data["detect_title"] == "div.fic-header h1"


def test_iter_templates_loads_all_seven():
    templates = iter_templates(TEMPLATE_DIR)
    assert set(templates) == {
        "kiss",
        "kobotochan",
        "lightnovelbox",
        "readnovelfull",
        "readnovelfull_browser",
        "royalroad",
        "wuxiaworld",
    }


def test_resolve_config_template_can_override_title_and_type():
    """Regression test: the old CLI could never let a template override
    --title or --type because both had truthy argparse defaults."""
    config = resolve_config(
        "https://example.com/chapter-1",
        template={"title": "Templated Title", "type": "mobi"},
        overrides={"title": None, "ebook_type": None},
    )
    assert config.title == "Templated Title"
    assert config.ebook_type == "mobi"


def test_resolve_config_explicit_override_wins_over_template():
    config = resolve_config(
        "https://example.com/chapter-1",
        template={"container": "div.template-container"},
        overrides={"container": "div.explicit-container"},
    )
    assert config.container == "div.explicit-container"


def test_resolve_config_next_alias():
    config = resolve_config(
        "https://example.com/chapter-1", template={"next": "a#next_chap"}
    )
    assert config.next_selector == "a#next_chap"
