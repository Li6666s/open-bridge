<!-- SPDX-License-Identifier: MIT -->
# Vendored: htm + Preact standalone bundle

The cockpit (`scripts/web/`) renders with Preact and htm, without a
build step and without loading anything from a CDN at run time. This folder holds
the one third-party file it needs, byte for byte as published.

| File | `htm-preact-3.1.1.module.js` |
|---|---|
| Source | `https://unpkg.com/htm@3.1.1/preact/standalone.module.js` |
| Package | htm 3.1.1 (`preact/standalone.module.js`: htm with Preact 10 and its hooks inlined) |
| Size | 13194 bytes |
| sha256 | `72284e8e9079c87817145df1110f74e8a2aa040b2fc384922e18dfcb46fc1fd7` |
| Fetched | 2026-10-09 |
| Exports | `h, html, render, Component, createContext, useState, useReducer, useEffect, useLayoutEffect, useRef, useImperativeHandle, useMemo, useCallback, useContext, useDebugValue, useErrorBoundary` |

## Licenses

- htm: Apache License 2.0, Copyright 2018 Google Inc. (https://github.com/developit/htm)
- Preact: MIT License, Copyright (c) 2015 to present Jason Miller (https://github.com/preactjs/preact)

The bundle is kept unchanged, so it carries no SPDX header of this repository; these
two licenses apply to it.

## Updating

1. Fetch the new version into a temp file, never straight over this one:
   `curl -sSfL -o /tmp/htm-preact.js https://unpkg.com/htm@<version>/preact/standalone.module.js`
2. Check what it exports (`grep -o 'export{[^}]*}' /tmp/htm-preact.js`) against the
   names `scripts/web/app.js` and `scripts/web/components.js` import.
3. Copy it here as `htm-preact-<version>.module.js`, update the two import lines, this
   table, and `VENDOR_SHA256` / `VENDOR_BYTES` in `scripts/tests/bridge_cockpit_frontend.test.mjs`.
4. Run `node scripts/tests/bridge_cockpit_frontend.test.mjs` and look at the page in
   light and dark mode before committing.
