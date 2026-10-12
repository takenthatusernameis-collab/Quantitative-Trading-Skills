---
name: webapp-testing
description: >-
  Toolkit for interacting with and testing local web applications using
  Playwright. Supports verifying frontend functionality, debugging UI behavior,
  capturing browser screenshots, and viewing browser logs.
metadata:
  category: development
  source:
    repository: 'https://github.com/ComposioHQ/awesome-claude-skills'
    path: webapp-testing
    license_path: webapp-testing/LICENSE.txt
    commit: be2a406907dbc61b73e6827ded415c96139d13a2
---

# Web Application Testing

To test local web applications, write native Python Playwright scripts.

**Helper Scripts Available**:
- `scripts/with_server.py` - Manages server lifecycle (supports multiple servers)

**Always run scripts with `--help` first** to see usage. DO NOT read the source until you try running the script first and find that a customized solution is abslutely necessary. These scripts can be very large and thus pollute your context window. They exist to be called directly as black-box scripts rather than ingested into your context window.

## Decision Tree: Choosing Your Approach

```
User task → Is it static HTML?
    ├─ Yes → Read HTML file directly to identify selectors
    │         ├─ Success → Write Playwright script using selectors
    │         └─ Fails/Incomplete → Treat as dynamic (below)
    │
    └─ No (dynamic webapp) → Is the server already running?
        ├─ No → Run: python scripts/with_server.py --help
        │        Then use the helper + write simplified Playwright script
        │
        └─ Yes → Reconnaissance-then-action:
            1. Navigate and wait for networkidle
            2. Take screenshot or inspect DOM
            3. Identify selectors from rendered state
            4. Execute actions with discovered selectors
```

## Example: Using with_server.py

To start a server, run `--help` first, then use the helper:

**Single server:**
```bash
python scripts/with_server.py --server "npm run dev" --port 5173 -- python your_automation.py
```

**Multiple servers (e.g., backend + frontend):**
```bash
python scripts/with_server.py \
  --server "cd backend && python server.py" --port 3000 \
  --server "cd frontend && npm run dev" --port 5173 \
  -- python your_automation.py
```

To create an automation script, include only Playwright logic (servers are managed automatically):
```python
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True) # Always launch chromium in headless mode
    page = browser.new_page()
    page.goto('http://localhost:5173') # Server already running and ready
    page.wait_for_load_state('networkidle') # CRITICAL: Wait for JS to execute
    # ... your automation logic
    browser.close()
```

## Reconnaissance-Then-Action Pattern

1. **Inspect rendered DOM**:
   ```python
   page.screenshot(path='/tmp/inspect.png', full_page=True)
   content = page.content()
   page.locator('button').all()
   ```

2. **Identify selectors** from inspection results

3. **Execute actions** using discovered selectors

## Common Pitfall

❌ **Don't** inspect the DOM before waiting for `networkidle` on dynamic apps
✅ **Do** wait for `page.wait_for_load_state('networkidle')` before inspection

## Best Practices

- **Use bundled scripts as black boxes** - To accomplish a task, consider whether one of the scripts available in `scripts/` can help. These scripts handle common, complex workflows reliably without cluttering the context window. Use `--help` to see usage, then invoke directly.
- Use `sync_playwright()` for synchronous scripts
- Always close the browser when done
- Use descriptive selectors: `text=`, `role=`, CSS selectors, or IDs
- Add appropriate waits: `page.wait_for_selector()` or `page.wait_for_timeout()`

## Reference Files

- **examples/** - Examples showing common patterns:
  - `element_discovery.py` - Discovering buttons, links, and inputs on a page
  - `static_html_automation.py` - Using file:// URLs for local HTML
  - `console_logging.py` - Capturing console logs during automation

---

## Test Coverage

This skill bundles a standard-library unit-test suite (no third-party test
framework) under `tests/`, following the pattern established by
`skills/quantitative-backtesting/tests/`. Run the test file directly with Python:

```bash
python3 skills/webapp-testing/tests/test_with_server.py
```

- `test_with_server.py` - Server lifecycle management tests:
  - `is_server_ready` polls TCP ports correctly, handles success, failure, and timeout cases
  - `main` validates argument parsing: mismatched server/port counts, missing command
  - `main` starts single server, waits for readiness, runs command, cleans up on success
  - `main` starts multiple servers in sequence, waits for each, runs command, cleans up all
  - `main` handles server startup failure: terminates process and exits with error code
  - `main` handles server termination timeout: calls terminate, then kill, then wait
  - `main` propagates command exit code when the user command fails
  - `main` strips the `--` separator correctly from command arguments
  - `main` passes `--timeout` parameter to `is_server_ready`

---
