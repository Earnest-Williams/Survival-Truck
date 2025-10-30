Textual Guide for Survival Truck

This guide defines mandatory rules, patterns, and style conventions for all Textual UI code in this repository. It is optimized for correctness under Textual CSS and for automated enforcement by Codex.
0) Codex Directives (enforceable)
Never introduce grid-row, grid-column, row, or column in any CSS.
Always place widgets by compose() order; only adjust area using row-span / column-span.
Only use supported properties listed in §6.
Replace min-content / max-content with auto.
Do not use :root, custom CSS variables, web fonts, or browser CSS layout properties.
1) Core Layout & Structure
Compose-Driven Layout. Visual placement is determined by compose() order; spans adjust coverage.
Area
Do
Do Not
Layout containers
layout: grid (default). Use vertical / horizontal / none only for simple stacks.
—
Child placement
Use compose order. Adjust with row-span, column-span.
Do not use grid-row, grid-column, row, column.
Grid definition
grid-size: <cols> <rows>, grid-columns, grid-rows, grid-gutter.
Do not use browser syntax (grid-template-*).
Row sizes
auto, 1fr, 2fr…
Do not use min-content / max-content.
Colors
Hex (e.g., #141414, #c0c0c0).
Do not use :root or custom variables.
Messages
Subclass Message; call super().__init__() with no args; use message.sender.
Do not pass sender to Message.__init__.
2) Project Style: Minimal Dark Theme
Use this baseline. Keep panels flat, borders minimal, spacing consistent.
2.1 Global Base
* {
    border: none;
    background: #141414;  /* dark surface */
    color: #c0c0c0;       /* light text */
}
2.2 App Chrome & Screen
Header, Footer {
    background: #1c1c1c;
    color: #7a7a7a;
    text-style: bold;  /* supported */
}

Screen {
    layout: grid;
    grid-rows: auto 1fr auto;  /* header, body, footer */
}
2.3 Dashboard Body Grid (#body)
#body {
    layout: grid;
    grid-size: 2 5;             /* 2 columns × 5 rows */
    grid-columns: 3fr 2fr;      /* 60% map, 40% side panels */
    grid-rows: auto auto auto auto 1fr;  /* 4 autos, bottom fills */
    grid-gutter: 1;
    padding: 1;
    /* height: 1fr;  optional; remove if content should drive height */
}
2.4 Panel Spacing & Accents
/* Consistent panel padding */
HexMapView, #status, #diplomacy, #truck, #controls, TurnLogWidget {
    padding: 1;
}

/* Map occupies left col rows 1–4 */
HexMapView {
    row-span: 4;
}

/* Log spans both columns on final row; single accent divider */
TurnLogWidget {
    column-span: 2;
    border-top: tall #4db6ac;
}
3) Compose Order (Default Dashboard)
Textual grids place children by compose order. For the 2×5 dashboard:
HexMapView() — left column, rows 1–4 (row-span: 4)
StatusPanel(id="status") — right column, row 1
DiplomacyView(id="diplomacy") — right column, row 2
TruckLayoutView(id="truck") — right column, row 3
ControlPanelWidget(id="controls") — right column, row 4
TurnLogWidget() — bottom row, spans both columns (column-span: 2)
If you change #body grid geometry, update this sequence accordingly.
4) Textual Message Pattern
Use message.sender. Do not pass a sender to Message.__init__.
from textual.message import Message
from textual.widget import Widget

class ControlPanelWidget(Widget):
    class PlanUpdated(Message):
        def __init__(self) -> None:
            super().__init__()

    def refresh_from_panel(self) -> None:
        self.refresh()
        self.post_message(self.PlanUpdated())

# Handler example
def on_control_panel_widget_plan_updated(self, message: ControlPanelWidget.PlanUpdated) -> None:
    control = message.sender  # the ControlPanelWidget
    # react to changes...
5) Review Checklist (Pre-Commit)
Before committing any UI changes, every developer must ensure these conditions are met.
Layout Syntax Check: No forbidden CSS properties (grid-row, grid-column, row, column) in any .py CSS blocks or .tcss files.
Sizing Consistency: No fractional row/column sizing uses min-content or max-content. Use auto or 1fr/2fr.
Explicit Layout: All major containers explicitly set layout and grid properties as needed.
Spanning Correctness: Only row-span / column-span are used for spanning.
Message Protocol: Message subclasses call super().__init__() with no arguments.
Style Integrity: Colors and accents adhere to the Minimal Dark Theme guidelines (#141414, #1c1c1c, #4db6ac).
Run Test: poetry run survival-truck launches with zero CSS parser errors.
6) Supported Property Reference (Whitelist)
These are the only Textual CSS properties permitted in this repository.
Category
Properties Allowed
Selectors
*, widget classes (e.g., HexMapView), IDs (#status), Header, Footer.
Layout & Grid
layout, grid-size, grid-columns, grid-rows, grid-gutter, row-span, column-span.
Box Model
padding (integer only).
Visuals
border, border-top (with supported styles: none, thin, tall, heavy), background, color.
Text
text-style (bold, italic, reverse, underline).
Note: Keep height/width explicit only when absolutely necessary. Prefer grid sizing (fr units).
7) Anti-Pattern Greps (for Codex / CI)
These patterns should trigger an automated build failure if detected in CSS files or inline styles.
Rule
Forbidden Pattern (Regex)
Forbidden Placement
\bgrid-row\b, \bgrid-column\b, \b[^-]row:\s*\d, \bcolumn:\s*\d
Forbidden Sizing
\bmin-content\b, \bmax-content\b
Forbidden Browser Grid
`\bgrid-template-(rows
Forbidden Root/Variables
^:root\s*{, \bvar\(
Forbidden Semicolon
; (in Python files)
8) Troubleshooting
Issue
Cause / Solution
"Invalid CSS property 'grid-row'..."
Remove them; use compose order + spans.
"Invalid value 'min-content' in grid-rows"
Replace with auto.
Borders still visible
Add border: none; to the specific selector; ensure no widget CSS re-enables it.
Messages crash with TypeError
Remove sender argument from Message.__init__; use message.sender.
Last updated: 2025-10-29
