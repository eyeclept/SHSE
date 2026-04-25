# Claude Code port kit

This folder is a **minimal, runnable Flask skeleton** for the SHSE port.
It shows the pattern Claude Code should imitate across every screen.

## What's here

```
handoff/
├── app.py                          Flask skeleton. Home route is wired;
│                                   everything else stubs abort(501) with
│                                   a TODO pointer to the prototype file.
├── static/
│   └── css/
│       └── tokens.css              All CSS custom properties + primitive
│                                   classes (.shse-btn, .shse-pill, etc.)
│                                   ported verbatim from src/theme.jsx.
└── templates/
    ├── base.html                   Skeleton with <html data-theme>,
    │                               Google Fonts, tokens.css, flash
    │                               messages, and {% block %} slots.
    ├── _icons.html                 Jinja macros for every icon +
    │                               the SHSE glyph + full logo.
    └── home.html                   Fully-ported home page. USE THIS
                                    AS THE PATTERN for every other
                                    screen.
```

## How to run

```
pip install flask
cd handoff
FLASK_APP=app.py flask run
```

Open http://127.0.0.1:5000/ — you should see the home page, pixel-identical
to the prototype's home artboard.

## The porting pattern (follow for every screen)

1. **Read the React source** in `../src/screens/<screen>.jsx`.
2. **Create `templates/<screen>.html`** extending `base.html`.
3. **Replace `{ }` prop interpolation with `{{ }}` Jinja.** React's
   `<ShseLogo size={76} />` becomes `{{ icon.logo(76) }}`.
4. **Replace event handlers with form posts or HTMX.** The prototype's
   `onClick={() => setRoute(…)}` becomes an `<a href>` or
   `hx-post="/path"` on an element with `hx-target`.
5. **Match inline `style={{…}}` verbatim.** The exception: extract
   anything that's reused 3+ times into a class in `tokens.css`.
6. **Add a route in `app.py`** that passes the same shape of context
   the React component received as props.
