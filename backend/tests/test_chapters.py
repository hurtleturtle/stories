"""The on-disk chapter store: how scraped chapters are kept and recovered."""

import json

import pytest

from story_scraper.chapters import MANIFEST, ChapterRecord, ChapterStore


def record(n: int, **overrides) -> ChapterRecord:
    fields = {
        "n": n,
        "url": f"https://example.com/{n}",
        "sha256": f"hash-{n}",
        "chapter": str(n),
        "next": f"https://example.com/{n + 1}",
    }
    return ChapterRecord(**{**fields, **overrides})


def manifest_lines(directory) -> list[str]:
    return (directory / MANIFEST).read_text().split("\n")


def store_with(directory, count: int, fingerprint: str = "fp") -> ChapterStore:
    store = ChapterStore(directory, fingerprint)
    for n in range(1, count + 1):
        store.add(record(n), f"<div>chapter {n}</div>")
    return store


def test_a_new_store_is_empty(tmp_path):
    store = ChapterStore(tmp_path / "work", "fp")

    assert (store.count, store.last, store.done) == (0, None, False)
    assert list(store.fragments()) == []
    assert (tmp_path / "work").is_dir()


def test_chapters_are_kept_in_order(tmp_path):
    store = store_with(tmp_path, 3)

    assert store.count == 3
    assert store.last == record(3)
    assert list(store.fragments()) == [f"<div>chapter {n}</div>" for n in (1, 2, 3)]
    assert store.urls() == {"https://example.com/1", "https://example.com/2", "https://example.com/3"}


def test_each_chapter_is_on_disk_as_soon_as_it_is_added(tmp_path):
    store = ChapterStore(tmp_path, "fp")

    store.add(record(1), "<div>one</div>")

    assert (tmp_path / "chapter-000001.html").read_text() == "<div>one</div>"
    assert json.loads(manifest_lines(tmp_path)[1])["url"] == "https://example.com/1"
    assert not list(tmp_path.glob("*.part"))


def test_chapters_must_be_added_in_sequence(tmp_path):
    store = store_with(tmp_path, 1)

    with pytest.raises(ValueError, match="Expected chapter 2"):
        store.add(record(5), "x")
    with pytest.raises(ValueError, match="Expected chapter 2"):
        store.add(record(1), "x")


def test_the_first_chapter_with_a_hash_is_the_one_reported(tmp_path):
    store = ChapterStore(tmp_path, "fp")
    store.add(record(1, sha256="same"), "a")
    store.add(record(2, sha256="other"), "b")
    store.add(record(3, sha256="same"), "c")

    assert store.chapter_with_hash("same") == 1
    assert store.chapter_with_hash("other") == 2
    assert store.chapter_with_hash("unseen") is None


def test_a_new_instance_picks_up_where_the_last_left_off(tmp_path):
    store_with(tmp_path, 3)

    reopened = ChapterStore(tmp_path, "fp")

    assert reopened.count == 3
    assert reopened.last == record(3)
    assert reopened.chapter_with_hash("hash-2") == 2
    assert list(reopened.fragments()) == [f"<div>chapter {n}</div>" for n in (1, 2, 3)]
    reopened.add(record(4), "<div>chapter 4</div>")
    assert ChapterStore(tmp_path, "fp").count == 4


def test_a_finished_story_stays_finished(tmp_path):
    store = store_with(tmp_path, 2)
    store.mark_done()
    store.mark_done()  # harmless to repeat

    reopened = ChapterStore(tmp_path, "fp")

    assert reopened.done
    assert reopened.count == 2
    assert manifest_lines(tmp_path).count(json.dumps({"done": True})) == 1


def test_stored_chapters_of_a_different_scrape_are_discarded(tmp_path):
    store_with(tmp_path, 2, fingerprint="story-a")

    other = ChapterStore(tmp_path, "story-b")

    assert (other.count, other.done) == (0, False)
    assert not list(tmp_path.glob("chapter-*"))
    assert ChapterStore(tmp_path, "story-b").count == 0


def test_an_unreadable_manifest_starts_afresh(tmp_path):
    store_with(tmp_path, 2)
    (tmp_path / MANIFEST).write_text("this is not json\n")

    assert ChapterStore(tmp_path, "fp").count == 0
    assert not list(tmp_path.glob("chapter-*"))


def test_an_empty_manifest_starts_afresh(tmp_path):
    store_with(tmp_path, 2)
    (tmp_path / MANIFEST).write_text("")

    assert ChapterStore(tmp_path, "fp").count == 0


def test_a_last_manifest_entry_cut_short_is_dropped_and_repaired(tmp_path):
    """A crash mid-write leaves a torn last line. Everything before it is fine."""
    store_with(tmp_path, 2)
    with (tmp_path / MANIFEST).open("a") as manifest:
        manifest.write('{"n": 3, "url": "https://exam')  # no newline: cut off

    reopened = ChapterStore(tmp_path, "fp")

    assert reopened.count == 2
    # Repaired on disk, so the next chapter starts on a fresh line.
    reopened.add(record(3), "<div>chapter 3</div>")
    again = ChapterStore(tmp_path, "fp")
    assert again.count == 3
    assert list(again.fragments())[-1] == "<div>chapter 3</div>"


def test_a_missing_final_newline_is_repaired(tmp_path):
    store_with(tmp_path, 2)
    path = tmp_path / MANIFEST
    path.write_text(path.read_text().rstrip("\n"))

    reopened = ChapterStore(tmp_path, "fp")
    reopened.add(record(3), "<div>chapter 3</div>")

    assert ChapterStore(tmp_path, "fp").count == 3


def test_a_chapter_file_written_before_its_manifest_entry_is_overwritten(tmp_path):
    """The chapter file goes down first; a crash before the manifest line leaves
    an orphan, which the next attempt simply replaces."""
    store = store_with(tmp_path, 1)
    (tmp_path / "chapter-000002.html").write_text("orphan from a crash")

    reopened = ChapterStore(tmp_path, "fp")
    assert reopened.count == 1
    reopened.add(record(2), "<div>chapter 2</div>")

    assert list(ChapterStore(tmp_path, "fp").fragments())[1] == "<div>chapter 2</div>"
    assert store.count == 1


def test_a_last_entry_whose_chapter_file_is_missing_is_dropped(tmp_path):
    store_with(tmp_path, 3)
    (tmp_path / "chapter-000003.html").unlink()

    assert ChapterStore(tmp_path, "fp").count == 2


def test_a_missing_chapter_file_before_the_end_means_starting_afresh(tmp_path):
    store_with(tmp_path, 3)
    (tmp_path / "chapter-000001.html").unlink()

    assert ChapterStore(tmp_path, "fp").count == 0
    assert not list(tmp_path.glob("chapter-*"))


def test_a_corrupt_entry_in_the_middle_means_starting_afresh(tmp_path):
    store_with(tmp_path, 3)
    lines = manifest_lines(tmp_path)
    lines[2] = "garbage"
    (tmp_path / MANIFEST).write_text("\n".join(lines))

    assert ChapterStore(tmp_path, "fp").count == 0


@pytest.mark.parametrize("bad_line", ["[1, 2]", "5", '{"unexpected": true}', '{"n": 1}'])
def test_entries_of_the_wrong_shape_are_not_trusted(tmp_path, bad_line):
    store_with(tmp_path, 1)
    with (tmp_path / MANIFEST).open("a") as manifest:
        manifest.write(bad_line + "\n")

    reopened = ChapterStore(tmp_path, "fp")

    assert reopened.count == 1  # the bad last line is dropped


def test_entries_out_of_order_are_not_trusted(tmp_path):
    store_with(tmp_path, 3)
    lines = manifest_lines(tmp_path)
    lines[2], lines[3] = lines[3], lines[2]
    (tmp_path / MANIFEST).write_text("\n".join(lines))

    assert ChapterStore(tmp_path, "fp").count == 0


def test_a_chapter_recorded_after_the_end_marker_is_not_trusted(tmp_path):
    store = store_with(tmp_path, 1)
    store.mark_done()
    (tmp_path / "chapter-000002.html").write_text("x")
    with (tmp_path / MANIFEST).open("a") as manifest:
        manifest.write(json.dumps(record(2).__dict__) + "\n")
        manifest.write(json.dumps(record(3).__dict__) + "\n")

    assert ChapterStore(tmp_path, "fp").count == 0
