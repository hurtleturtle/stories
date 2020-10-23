# stories
Download web-based serial stories, convert them to an ebook and send them to kindle.

## scripts
Store custom scripts for browser-based reading in here.

## styles
Store CSS here

## templates
Store argument templates in YAML format in this folder. The following arguments are commonly used:
- container (mandatory)
  - A CSS selector (usually) describing the <p> tags containing your story text
- next (mandatory)
  - A CSS selector describing how to find the hyperlink for the next chapter
- detect_title (optional)
  - A CSS selector to locate the chapter title
- style (optional)
  - Path to a CSS file with the style to apply to the HTML story
- scripts (optional)
  - Scripts to be added to the <head> tag
  - Note that these should be supplied as a list
