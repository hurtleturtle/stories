"""Command-line entry point, kept for standalone use of the scraper."""

from __future__ import annotations

import logging
from argparse import ArgumentParser, Namespace
from pathlib import Path

from story_scraper.config import Settings
from story_scraper.converter import convert
from story_scraper.mailer import SmtpConfig, send_ebook
from story_scraper.resolve import resolve_config
from story_scraper.scraper import Story
from story_scraper.templates import find_template, load_template


def parse_args(argv: list[str] | None = None) -> Namespace:
    parser = ArgumentParser(description="Scrape a web serial into an ebook")
    story = parser.add_argument_group("story")
    actions = parser.add_argument_group("actions")

    story.add_argument("-u", "--url", required=True, help="URL of first chapter")
    story.add_argument("-i", "--input-template", help="Name of a template in templates/")
    story.add_argument("-t", "--title", help="Ebook title")
    story.add_argument("-c", "--container", help="Chapter container CSS selector")
    story.add_argument("-n", "--next", dest="next_selector", help="Next chapter CSS selector")
    story.add_argument("-d", "--detect-title", help="CSS selector for chapter title")
    story.add_argument("-s", "--scripts", help="Comma-separated scripts to add to <head>")
    story.add_argument("--style", help="Stylesheet filename")
    story.add_argument("--type", dest="ebook_type", help="Ebook type, e.g. epub or mobi")
    story.add_argument("--num-chapters", type=int, help="Stop after this many chapters")
    story.add_argument("-v", dest="verbosity", action="count", default=0)

    actions.add_argument("--no-download", action="store_true")
    actions.add_argument("--no-convert", action="store_true")
    actions.add_argument("--no-email", action="store_true")

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbosity else logging.INFO)
    settings = Settings()

    template_dir = Path(__file__).resolve().parents[2] / "templates"
    template: dict = {}
    if args.input_template:
        path = find_template(args.input_template, template_dir)
        if not path:
            raise SystemExit(f"Template {args.input_template!r} not found in {template_dir}")
        template = load_template(path)

    overrides = {
        "title": args.title,
        "container": args.container,
        "next_selector": args.next_selector,
        "detect_title": args.detect_title,
        "scripts": args.scripts.split(",") if args.scripts else None,
        "style": args.style,
        "ebook_type": args.ebook_type,
        "num_chapters": args.num_chapters,
        "verbosity": args.verbosity,
    }
    config = resolve_config(args.url, template, overrides)

    output_dir = Path(settings.story_folder)
    ebook_name = f"{config.resolved_filename()}.{config.ebook_type}"
    ebook_file = output_dir / config.ebook_type / ebook_name

    with Story(config, progress=lambda n, u: logging.info("Chapter %d: %s", n, u)) as story:
        if not args.no_download:
            html_file = story.write(output_dir / "html")
        else:
            html_file = output_dir / "html" / f"{config.resolved_filename()}.html"

    if not args.no_convert:
        convert(html_file, ebook_file, config.title)

    if not args.no_email:
        if not (settings.email_from and settings.email_to and settings.email_password):
            raise SystemExit("EMAIL_FROM, EMAIL_TO and EMAIL_PASSWORD must be set to send email")
        smtp = SmtpConfig(
            from_addr=settings.email_from,
            to_addr=settings.email_to,
            password=settings.email_password,
            host=settings.smtp_host,
            port=settings.smtp_port,
        )
        send_ebook(config.title, ebook_file, smtp)


if __name__ == "__main__":
    main()
