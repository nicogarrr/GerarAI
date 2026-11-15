# Web Components Orientation

Web Components are Custom Elements, Shadow DOM, and HTML Templates: the platform primitives for reusable, framework-agnostic components whose markup and styles are encapsulated from the document. Use them for design systems, embeddable widgets, and self-contained UI.

The rules below are cross-cutting. Retrieve the specific guide for the task at hand; each restates the context it needs and documents the APIs and pitfalls unique to it.

## Decide whether you even need a custom element

Reach for a custom element only when you need encapsulated behavior, lifecycle, or a reusable JS-backed API on a tag. Do **not** build one when:

- A plain HTML element with CSS would do. A styled `<button>` or `<details>` is more accessible and cheaper than a re-implementation.
- The thing is purely presentational with no behavior. A class on a native element is more performant, and scopable with `@layer` or `@scope`.
- You only need style scoping on the server with no interactivity; a scoped stylesheet or Declarative Shadow DOM (without an upgrade) may be enough.

[External command example omitted from offline reference.]

[External command example omitted from offline reference.]

## Match the tool to the codebase

Whether something *should* be a custom element depends on what the project already uses. Agents tend to over-abstract and reach for a new element too eagerly — when in doubt, the lighter option (native element, CSS, a server template) is usually right, and you can promote to a custom element later if reuse or behavior actually demands it. Heuristics, in rough priority:

- **The codebase already has a component model (React, Vue, Svelte, …).** Default to that framework's component for in-app UI. Reach for a custom element only when the thing must escape or outlive the framework: a design-system primitive shared across apps or frameworks, a widget dropped into markup the framework doesn't control, or output that must work as plain HTML (email, CMS, SSR fragments). Don't stand up a parallel component system for ordinary in-app views.
- **No tooling, mostly static markup.** Prefer plain HTML + CSS, or a server template/partial. A custom element earns its keep only where you genuinely need behavior, lifecycle, or a JS-backed API on the tag — not merely to share markup, which a server include or `<template>` does without shipping any JS.
- **Static site generator with islands of interactivity.** Render the markup statically; reserve the custom element for the interactive part. For "lots of markup, a little interactivity," keep the markup in Light DOM (or Declarative Shadow DOM) and let a small custom element progressively enhance it, rather than re-rendering everything from JS.
- **You could push a built-in element further instead.** Taking a native element as far as it goes (CSS, a few listeners, the occasional pseudo-element) is usually preferable to a custom element, because you keep the platform's accessibility and behavior for free. Cross over to a custom element when the workarounds stop being maintainable — when you'd be fighting the element's built-in behavior, or the authoring experience becomes worse than a clean component API would be. Needing a little JS on a built-in element is not, by itself, a reason to replace it.

## Cross-cutting rules

These hold across every guide below:

- **MANDATORY**: the tag name must be kebab-case with at least one hyphen (e.g. `my-element`). This is what distinguishes custom elements from current and future built-ins.
- **MANDATORY**: call `super()` first in the constructor, before touching `this`; calling it after any statement that reads or writes `this` throws.
- **MANDATORY**: use semantic elements (`<button>`, `<nav>`, `<ul>`) inside shadow templates. Most accessibility failures in shadow trees come from non-semantic markup; a slot does not change the role of what it projects.
- **MANDATORY**: ARIA `id` references (`aria-labelledby`, `aria-describedby`, `aria-controls`) cannot cross a shadow boundary; the referencing element and the `id` it points to must live in the same tree.
- **MANDATORY**: attach shadow roots with `attachShadow({ mode: 'open' })` (or `shadowrootmode="open"` for Declarative Shadow DOM); `mode: 'closed'` hides `element.shadowRoot` from page scripts, test harnesses, and automated accessibility checkers that walk shadow trees.
- Avoid *customized built-in elements* (`extends HTMLButtonElement` with `is="…"`); Safari has permanently declined to ship them.

## Use-case guide matrix

Identify the task and retrieve its guide:

| If you need to… | Retrieve |
| :--- | :--- |
[External command example omitted from offline reference.]
[External command example omitted from offline reference.]
[External command example omitted from offline reference.]
[External command example omitted from offline reference.]
[External command example omitted from offline reference.]
[External command example omitted from offline reference.]
