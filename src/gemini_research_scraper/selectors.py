"""Every selector used against gemini.google.com, in one place.

Gemini's DOM is an Angular app with generated class names and changes without
notice, so each UI element is described by an ordered list of *candidates*.
The automation tries them in order and uses the first one that is visible.

Candidate forms:
    ("css",  "<css selector>")
    ("role", "<aria role>", "<accessible-name regex, case-insensitive>")
    ("text", "<visible-text regex, case-insensitive>")

If Gemini ships a UI change, fixing this file (usually by prepending a new
candidate) should be the only work required.
"""

Candidate = tuple  # ("css", sel) | ("role", role, name_re) | ("text", text_re)

# --- Login state -----------------------------------------------------------

SIGN_IN_BUTTON: list[Candidate] = [
    ("role", "link", r"^sign in$"),
    ("role", "button", r"^sign in$"),
    ("css", "a[href*='accounts.google.com/ServiceLogin']"),
]

# --- Prompt composer -------------------------------------------------------

PROMPT_INPUT: list[Candidate] = [
    ("css", "div.ql-editor[contenteditable='true']"),
    ("css", "rich-textarea div[contenteditable='true']"),
    ("css", "div[contenteditable='true'][role='textbox']"),
]

SEND_BUTTON: list[Candidate] = [
    ("css", "button[aria-label='Send message']"),
    ("css", "button.send-button"),
    ("role", "button", r"^(send message|send|submit)$"),
    ("css", "button[aria-label*='Send']"),
]

# --- Deep Research mode ----------------------------------------------------

# Sometimes exposed directly as a chip next to the composer…
DEEP_RESEARCH_CHIP: list[Candidate] = [
    ("role", "button", r"^deep research$"),
    ("css", "button[aria-label='Deep Research']"),
]

# …otherwise behind the "Tools" menu in the composer.
TOOLS_BUTTON: list[Candidate] = [
    ("css", "button[aria-label='Tools']"),
    ("role", "button", r"^tools$"),
    ("css", "toolbox-drawer button"),
]

DEEP_RESEARCH_MENU_ITEM: list[Candidate] = [
    ("role", "menuitem", r"deep research"),
    ("role", "menuitemradio", r"deep research"),
    ("role", "menuitemcheckbox", r"deep research"),
    ("role", "option", r"deep research"),
    ("text", r"^\s*deep research\s*$"),
]

# Evidence that the mode actually engaged (a label/chip near the composer).
DEEP_RESEARCH_ACTIVE: list[Candidate] = [
    ("css", "button[aria-pressed='true'][aria-label*='Deep Research']"),
    ("text", r"deep research"),
]

# --- Plan approval ---------------------------------------------------------

START_RESEARCH_BUTTON: list[Candidate] = [
    ("role", "button", r"^start research$"),
    ("css", "button[aria-label='Start research']"),
    ("role", "button", r"start research"),
]

# --- Progress / completion -------------------------------------------------

RESEARCH_IN_PROGRESS: list[Candidate] = [
    ("text", r"(researching|browsing the web|analyzing (results|websites)|"
             r"i('|’)ve completed \d|working on it|just a few more)"),
    ("css", "deep-research-tracker"),
    ("css", "progress-indicator"),
]

RESEARCH_COMPLETE: list[Candidate] = [
    ("role", "button", r"^export$"),
    ("css", "button[aria-label='Export']"),
    ("role", "button", r"(export to docs|open in docs|create doc)"),
    ("css", "button[data-test-id='export-button']"),
]

RESEARCH_FAILED: list[Candidate] = [
    ("text", r"(something went wrong|couldn('|’)t complete|unable to complete"
             r"|research was (stopped|cancelled))"),
]

# --- Report extraction -----------------------------------------------------

# The finished report usually opens in an "immersive" side panel; if none of
# the panel selectors match, the last chat message is used as a fallback.
REPORT_CONTAINER: list[Candidate] = [
    ("css", "deep-research-immersive-panel"),
    ("css", "immersive-panel"),
    ("css", "[class*='immersive-editor']"),
    ("css", "message-content"),  # .last is applied by the extractor
]

REPORT_TITLE: list[Candidate] = [
    ("css", "deep-research-immersive-panel h1"),
    ("css", "immersive-panel h1"),
    ("css", "[data-test-id='report-title']"),
]
