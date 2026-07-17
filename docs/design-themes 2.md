# Developing themes

TBC separates visual design from the web interface through a theme API that follows the same
packaging model as camera plugins. A theme is a self-contained package of metadata and a
stylesheet that may be built in or imported as a ZIP file. The web interface contains no
hard-coded colors or layout rules; it references only the currently active theme.

TBC includes two themes: `standard`, the original light theme and current default, and
`midnight`, a dark theme with a blue accent.

## Theme package

A theme ZIP contains its files directly at the archive root or inside exactly one common
directory:

```text
acme-design.zip
├── manifest.json
└── static/
    └── styles.css
```

`manifest.json` is the authoritative configuration:

```json
{
  "schema_version": 1,
  "key": "acme",
  "label": "Acme Design",
  "version": "1.0.0",
  "description": "An example theme",
  "stylesheet": "styles.css"
}
```

`stylesheet` points to a file relative to `static/` inside the package. Unlike a camera
plugin, a theme package contains only stylesheets (`.css`), metadata (`.json`, `.md`), and
images (`.png`, `.jpg`, `.jpeg`, `.svg`, `.webp`, `.ico`), with no executable code. Importing
a theme is therefore considerably less risky than importing a camera plugin.

Built-in themes are completely contained in `app/tbc/design_themes/<key>/`, including their
full stylesheets, and are as self-contained as externally installed themes.

## Active theme

TBC stores the active theme for each installation in the database (`ui_settings` table,
default `standard`). Every rendered page automatically includes the active stylesheet through
`/design/{key}/static/{path}`. Like `/static`, this route is accessible without signing in so
that the login page is styled correctly.

## Importing, activating, and exporting

Administrators open `Admin → Themes` and import a theme ZIP. TBC validates the manifest,
paths, file types, file count, and extracted size (maximum 5 MB archive and 10 MB extracted),
then installs the theme atomically. An existing external theme with the same key is updated.
Built-in themes cannot be overwritten or removed.

The same page can activate a theme with the **Activate** button or export it as a ZIP. The
active theme cannot be removed. `TBC_THEME_MODULES_PATH` configures the external theme
directory (default `/data/design-themes`), which resides in the persistent `/data` volume in
the Docker setup.

Instead of uploading a ZIP manually, a theme can be installed directly from a public GitHub
repository under `Admin → External sources`; see [plugin-sources.md](plugin-sources.md).
Themes contain no executable code, so the plugin-test function does not apply to them.

## Security

A theme package contains no executable code, only stylesheets, metadata, and images. ZIP
validation prevents path and file-type attacks. Even so, import themes only from trusted
sources because a stylesheet can alter the entire interface.
