---
name: Blue
description: A daylit analyst workspace for reviewing message evidence and recording human decisions.
colors:
  accent: "#2455ed"
  accent-hover: "#1943c9"
  accent-soft: "#eaf0ff"
  page: "#f5f7fb"
  surface: "#ffffff"
  surface-raised: "#edf1f8"
  ink: "#121c35"
  muted: "#596780"
  border: "#e4e9f2"
  high: "#b42338"
  high-bg: "#fceef0"
  medium: "#95611b"
  medium-bg: "#fff4e1"
  low: "#247351"
  low-bg: "#eaf5ef"
  evidence: "#ffebad"
  evidence-ink: "#443416"
  selected-row: "#eef3ff"
  hover-row: "#f6f8fd"
typography:
  headline:
    fontFamily: "Manrope, -apple-system, BlinkMacSystemFont, sans-serif"
    fontSize: "clamp(25px, 2.6vw, 38px)"
    fontWeight: 700
    lineHeight: 1.2
    letterSpacing: "-0.035em"
  title:
    fontFamily: "Manrope, -apple-system, BlinkMacSystemFont, sans-serif"
    fontSize: "17px"
    fontWeight: 600
    lineHeight: 1.5
    letterSpacing: "-0.025em"
  panel-title:
    fontFamily: "Manrope, -apple-system, BlinkMacSystemFont, sans-serif"
    fontSize: "20px"
    fontWeight: 600
    lineHeight: 1.5
    letterSpacing: "-0.025em"
  body:
    fontFamily: "Manrope, -apple-system, BlinkMacSystemFont, sans-serif"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.5
  message:
    fontFamily: "Manrope, -apple-system, BlinkMacSystemFont, sans-serif"
    fontSize: "13px"
    fontWeight: 400
    lineHeight: 1.65
  label:
    fontFamily: "Manrope, -apple-system, BlinkMacSystemFont, sans-serif"
    fontSize: "12px"
    fontWeight: 600
    lineHeight: 1.5
  score:
    fontFamily: "Manrope, -apple-system, BlinkMacSystemFont, sans-serif"
    fontSize: "37px"
    fontWeight: 500
    lineHeight: 1.5
    letterSpacing: "-0.04em"
  mono:
    fontFamily: "Consolas, monospace"
    fontSize: "0.8125rem"
    lineHeight: 1.5
rounded:
  control: "8px"
  panel: "12px"
  dialog: "14px"
  badge: "5px"
  toast: "10px"
spacing:
  compact: "8px"
  field: "12px"
  toolbar: "16px"
  workspace-gap: "18px"
  panel: "22px"
  section: "24px"
  desktop-gutter: "32px"
components:
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.surface}"
    typography: "{typography.label}"
    rounded: "{rounded.control}"
    padding: "10px 14px"
  button-primary-hover:
    backgroundColor: "{colors.accent-hover}"
  button-secondary:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    typography: "{typography.label}"
    rounded: "{rounded.control}"
    padding: "10px 14px"
  button-secondary-hover:
    backgroundColor: "{colors.surface-raised}"
  input:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "9px 12px"
  navigation-active:
    backgroundColor: "{colors.accent-soft}"
    textColor: "{colors.accent}"
    rounded: "{rounded.control}"
    padding: "10px 12px"
  workspace-status:
    backgroundColor: "{colors.accent-soft}"
    textColor: "{colors.accent}"
    rounded: "20px"
    padding: "5px 10px"
  panel:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.panel}"
    padding: "{spacing.panel}"
  evidence-quote:
    backgroundColor: "{colors.page}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "12px"
---

# Design System: Blue

## Overview

**Creative North Star: "The Daylit Analyst Workspace"**

Blue is an operating workspace: a cool ground, white review surfaces, dark ink and a precise royal-blue accent. Message content, source context and review actions share one calm working field. This light direction replaces the previous dark orange identity.

A folded lowercase b is the signature, shared by the vector mark and a lit extruded 3D form. Dimensional branding stays beside the analyst's work or inside a short, skippable entrance; review surfaces remain mostly flat. The generated concept supplies composition reference only; actual application data and implemented components define the shipped system.

**Key Characteristics:**
- Cool daylight surfaces and restrained royal-blue emphasis.
- Self-hosted Manrope with Cyrillic, Cyrillic extended and Latin glyph coverage.
- Dense message review with adjacent evidence and explicit human judgment.
- Finite animation, keyboard controls and a usable non-WebGL path.

## Colors

Cool neutrals support royal-blue navigation and actions; risk and evidence use separate semantic treatments.

### Primary
- **Royal Blue** (`accent`): primary actions, active navigation, links, focus outlines, the b mark and source nodes.
- **Deep Royal Blue** (`accent-hover`): primary-action hover.
- **Pale Blue** (`accent-soft`): active navigation, pagination and workspace mode.

### Secondary
- **Risk Red**, **Risk Ochre**, **Risk Green** (`high`, `medium`, `low`): labeled risk states and legend dots, with their corresponding pale background tokens on supporting risk surfaces.
- **Evidence Yellow / Evidence Ink** (`evidence`, `evidence-ink`): literal matching message excerpts, separate from severity.

### Neutral
- **Cool Ground** (`page`): application ground and inset evidence blocks.
- **White Sheet** (`surface`): navigation, panels and fields; also foreground on filled blue actions.
- **Raised Cool Neutral** (`surface-raised`): secondary-control hover.
- **Deep Ink**, **Slate Text**, **Fine Divider** (`ink`, `muted`, `border`): primary text, secondary text and boundaries.
- **Selected Row / Hover Row** (`selected-row`, `hover-row`): table state fills.

**The Action and Evidence Rule.** Blue marks navigation, actions and source identity. Risk colors describe labeled risk; yellow marks evidence text.

## Typography

**Display and Body Font:** Manrope with the platform sans-serif fallback in the tokens. Local assets supply weights (400, 500, 600, 700), including Cyrillic and Cyrillic extended. Some Kazakh glyphs use the system fallback; these assets do not supply complete Kazakh coverage.
**Mono Font:** Consolas with monospace fallback, confined to technical content.

### Hierarchy
- **Headline:** responsive page headings; use the normative headline token.
- **Title / Panel Title:** section headings and larger inbox/focus titles.
- **Body / Message:** body copy and multiline previews; table previews clamp to two lines while full text remains accessible.
- **Label:** action labels and compact supporting headings. Navigation uses regular text (13px), with active items at weight (600).
- **Score:** evidence score with tabular numbers; mobile reduces it to (32px).
- **Brand entrance:** lowercase Manrope, weight (600), size `clamp(70px, 13vw, 138px)`, line-height (1.1), tracking (-0.04em). This is a brand treatment, not a page-heading scale.

**The One Text Voice Rule.** Use Manrope throughout the workspace and wordmark; reserve monospace for technical content and tabular numerals for comparable values.

## Layout

Desktop uses a fixed sidebar (216px), context bar (55px), and fluid main area capped at (1560px), with main padding (36px 32px 20px). The inbox pairs a flexible review sheet with an evidence panel (330px) across a gap (18px). The graph pairs its stage with a results list (300px).

At or below (1250px), the sidebar narrows to (184px), evidence stacks and uses two columns internally, and graph results stack. At or below (800px), the sidebar becomes a top brand row and horizontally scrollable icon-and-text navigation; sidebar 3D is removed. At or below (560px), filters, evidence and graph results use one column and the table becomes readable message blocks. At (1600px) and above, main padding becomes (44px 48px 24px) and inbox gap becomes (24px). Base styles also adapt detail and analysis layouts at (1000px) and (700px).

Compact control spacing sits inside larger section separation. Evidence and long source strings wrap; preview truncation always retains access to the complete message.

## Elevation & Depth

Depth comes mainly from borders, white sheets and tonal insets. Review panels have no ambient card shadow. Toasts use `0 12px 28px #121c3526`; modal help uses a dim backdrop (`#10204755`). The b signature uses lit, beveled geometry with a glossy blue physical material.

**The Reserved Depth Rule.** Keep review surfaces flat; reserve dimensional material for the b signature and genuine spatial source membership.

Route entries animate opacity (0.75 to 1) and translation (8px to 0) over (250ms), using `cubic-bezier(0.16, 1, 0.3, 1)`. Controls transition colors and borders over (150ms ease-out). The skippable brand entrance completes after (2100ms); reduced motion shows a short static state. The sidebar mark's animation loop stops after (4400ms). Hidden/offscreen scenes skip animated rendering, DPR is capped at (1.5), and graph views render on interaction.

## Shapes

Controls have gently rounded corners; review sheets use larger panel corners. Dialogs and toasts use their established radii. Mode pills are fully rounded; source avatars are circular. Risk is text with a small dot. The folded b and diamond source marker supply distinctive geometry.

## Components

### Buttons
Compact and direct. Primary actions use blue with white labels; secondary actions use white with a fine divider border. Frontmatter owns padding and typography. Default minimum height is (40px), icon gap (8px). Primary hover darkens; secondary hover gains a cool fill. Keyboard focus uses a blue outline (2px), offset (4px). Disabled opacity is (0.4); fine-pointer activation translates down (1px).

### Inputs / Fields
White, fine bordered and softly rounded, minimum height (40px). Search combines an inline SVG icon and borderless nested input; the outer border becomes (`#8798b5`) on focus. Open filters expand in normal flow.

### Navigation / Chips
Icons accompany full text labels. Active routes use pale-blue fill and blue text; hover uses page ground and ink. The mode chip combines text with a blue dot. Inbox tabs use a blue underline and small count inset. Risk always retains its text label.

### Cards / Containers
White sheets with fine dividers and panel corners. Evidence uses source metadata, a score, an inset original-message quote, reasons and a direct review link. Highlights retain original wording. Keep the human-review disclaimer attached to this context.

### Source Membership Graph
Royal-blue source objects connect only to actual message members. Lit risk-node materials and a gray unscored state belong to the spatial view. A source filter, pointer selection, rotate/zoom/reset buttons and equivalent message-link list expose the same data. The vector mark remains available without WebGL.

**The Actual Membership Rule.** An edge means a message belongs to a source; it must never imply an inferred account relationship or a fraud verdict.

## Do's and Don'ts

### Do:
- **Do** use the cool ground, white sheets and blue actions consistently across routes.
- **Do** keep message evidence, source context, risk labels and human review readable together.
- **Do** retain keyboard controls, source/message lists, reduced motion and vector fallbacks alongside 3D.
- **Do** show actual application counts and distinguish synthetic demonstration scores from evaluated model results.

### Don't:
- **Don't** reuse the discarded dark orange identity for new Blue surfaces.
- **Don't** turn the workspace into a landing-first 3D spectacle or repeat the entrance during SPA navigation.
- **Don't** introduce decorative glass cards, neon glow or stock robot imagery.
- **Don't** invent AI performance metrics, graph relationships or legal verdicts.
