---
name: Home OS
description: A shared household app laid like a Brazilian hydraulic-tile kitchen wall.
colors:
  glaze-green: "#17634f"
  glaze-green-deep: "#0c3a2e"
  glaze-green-soft: "#dcebe3"
  glaze-green-ink: "#0f4f3f"
  cement-ground: "#eceeea"
  cement-surface: "#fbfcfa"
  grout: "#cdd5ce"
  grout-soft: "#e1e6e1"
  ink: "#14231e"
  ink-muted: "#4a5d56"
  ochre: "#c8952b"
  ochre-ink: "#7f5c13"
  fired-clay: "#a3372f"
  night-ground: "#0e1613"
  night-surface: "#16211d"
  night-glaze: "#4fa07e"
typography:
  heading:
    fontFamily: "Bricolage Grotesque Variable, Figtree Variable, system-ui, sans-serif"
    fontWeight: 700
    letterSpacing: "-0.02em"
  body:
    fontFamily: "Figtree Variable, Segoe UI, system-ui, sans-serif"
    fontWeight: 400
    lineHeight: 1.55
  label:
    fontFamily: "Figtree Variable, Segoe UI, system-ui, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 650
rounded:
  tile: "2px"
  control: "6px"
  wall: "4px"
spacing:
  grout: "3px"
  tile-pad: "16px"
  tile-pad-wide: "22px"
components:
  button-primary:
    backgroundColor: "{colors.glaze-green}"
    textColor: "#ffffff"
    rounded: "{rounded.control}"
    height: "42px"
  button-soft:
    backgroundColor: "{colors.glaze-green-soft}"
    textColor: "{colors.glaze-green-ink}"
    rounded: "{rounded.control}"
  tile:
    backgroundColor: "{colors.cement-surface}"
    rounded: "{rounded.tile}"
    padding: "16px"
  nav-bar:
    backgroundColor: "{colors.glaze-green-deep}"
    textColor: "#ffffff"
---

# Design System: Home OS

## Overview

**Creative North Star: "The Kitchen Wall"**

Every group of content is a tile pressed into grout, and every area of the house owns a hydraulic-tile motif (arcos, losango, flor, catavento, estrela, olho). The mood is matte and domestic: unglazed cement, pigment, and a thin joint between neighbours, never gloss. Ordinary controls stay ordinary Mantine components so a family member never has to learn anything; the character lives in tiles, bands and the one signature gesture of a finished item turning over.

**Key Characteristics:**
- Restrained palette: one green pigment, cement neutrals, ochre for attention, fired clay for errors.
- Phone first: the primary navigation is a deep-green bottom bar, becoming a sidebar from 64em.
- Money is written as sentences with one large figure, plus a ten-tile budget meter.
- Motion states change only: page change, tile flip, toast stack, nav icon gesture; all respect reduced motion.

## Colors

Strategy: Restrained. Green carries primary actions, current location and "done"; everything else is cement.

- **Glaze green** (#17634f): primary action, selection, completed state. Deep variant (#0c3a2e) is the navigation and toast ground.
- **Cement ground / surface** (#eceeea / #fbfcfa): page and tile. Dark scheme inverts to #0e1613 / #16211d with a lighter green (#4fa07e).
- **Grout** (#cdd5ce): the 3px joint between tiles and every hairline.
- **Ochre** (#c8952b): overdue and partial states; **fired clay** (#a3372f): errors, debts, unpaid.

## Typography

Bricolage Grotesque for headings and large money figures; Figtree for everything else. Headings use a fixed rem scale (2rem, 1.375rem, 1.0625rem), tightened tracking, balanced wrapping. Money and quantities use tabular numerals.

## Layout

One 3px grout grid (`.tile-wall`) holds tiles (`.tile`). Phone: a single column in a deliberate reading order; at 64em modules split into a main column and a side column with a fixed 248px sidebar. Page max width 1180px. Section chips on phones jump between a long module's sections and hide on wide screens.

## Elevation & Depth

Flat. Depth comes from grout lines and tonal steps, never from gloss, gradients or inset highlights. Only floating toasts cast a soft shadow.

## Shapes

Tiles are nearly square-cornered (2px) inside a 4px wall; controls 6px. Motifs are flat SVG on a 40-unit tile, drawn with three roles (base, glaze, ochre) so they recolor per scheme and context.

## Components

- **Tile / TileSection:** titled content group; one per concern.
- **PageHeader:** motif tile, h1, a "barrado" band of that area's tiles beneath.
- **FlipTile:** list-row marker; turns over to a green check when the item is done.
- **TileMeter:** ten cells for budget used; ochre when over budget.
- **Navigation:** one list that is a bottom bar on phones and a sidebar on desktop; an active pill slides between areas and icons act out a small gesture on hover.
- **EmptyState:** a small wall with one tile still to be laid.
- **Toaster:** confirmations stack at the bottom and fan out on hover; errors stay inline.

## Do's and Don'ts

**Do** keep each new area on its own motif; keep confirmations in toasts and errors next to the field; hide write actions from viewers.
**Don't** add gloss, gradients or hard shadows; don't use pattern behind body text; don't put motifs on every tile, they belong to headers, bands, empty states and the sign-in wall.

*Not canonized:* the ochre "Atrasada · Concluir" label combines state and action in one button and is a copy compromise, not a pattern.
