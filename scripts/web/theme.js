// SPDX-License-Identifier: MIT
// Classic (non-module) script, loaded in <head> before the stylesheets apply, so
// the page never flashes in the wrong mode. The stored choice is "auto", "light"
// or "dark"; auto follows the system. app.js keeps the class in sync afterwards.
// A page address with ?theme=light or ?theme=dark forces that mode for this load
// without saving it (the static demo on the website; same rule as logic.js themeOverride).
(function () {
  var mode = 'auto'
  var forced = null
  try { forced = new URLSearchParams(window.location.search).get('theme') } catch (e) { forced = null }
  if (forced === 'light' || forced === 'dark') {
    mode = forced
  } else {
    try {
      var stored = window.localStorage.getItem('bridge-cockpit.theme')
      if (stored === 'light' || stored === 'dark') mode = stored
    } catch (e) { /* storage blocked: follow the system */ }
  }
  var dark = mode === 'dark'
  if (mode === 'auto') {
    try { dark = window.matchMedia('(prefers-color-scheme: dark)').matches } catch (e) { dark = false }
  }
  var root = document.documentElement
  root.classList.toggle('dark', dark)
  root.classList.toggle('light', !dark)
  root.setAttribute('data-theme-mode', mode)
})()
