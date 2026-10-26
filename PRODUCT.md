# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Families and couples sharing one home. Non-technical adults who split the household's money, groceries and chores. They reach for Home OS on a phone, in short bursts, in the middle of the task itself: at the supermarket shelf, in the kitchen after a purchase, on the couch closing the month. Desktop use exists (planning budgets, registering products) but is secondary.

## Product Purpose

One shared operating space for a household: finances (expenses, splits, payments, monthly budget, member balances), shopping (product catalog, shared lists, purchase receipts that update stock and finances in one step), inventory, chores (one-off tasks and recurring routines with dated occurrences), and an optional ChatGPT-backed assistant that reads product labels. Success is a household where nobody has to ask "who owes what", "what do we need" or "whose turn is it".

## Positioning

The modules are wired together: a confirmed purchase updates inventory and records the expense once; the dashboard summarizes money, pending groceries and due chores for the same household. It is a self-hosted, single-household space, not a social app.

## Operating Context

- Session-cookie auth with CSRF; registration requires 6+ alphanumeric password characters.
- A user belongs to at most one active household. Owners issue single-use invitation tokens (7-day expiry); others paste a token to join.
- Roles: owner, member, viewer. Viewers are read-only everywhere.
- Money is integer cents (BRL). Dates and chore times follow the household timezone (default America/Sao_Paulo).

## Capabilities and Constraints

- Backend: Django/DRF under `/api/v1`. Frontend: React + TypeScript + Vite, tested with Vitest + Testing Library.
- Language: Brazilian Portuguese only.
- Assistant availability depends on server configuration; the UI must explain each unavailable state honestly.

## Brand Commitments

- Name: Home OS.
- Green is the brand's color family (user-confirmed, keep it).
- Voice: warm, plain, short Portuguese; no jargon toward family members.

## Evidence on Hand

No real household data, testimonials or screenshots are shipped. Never fabricate amounts, names or usage claims in the UI.

## Product Principles

1. The phone at the moment of the task is the primary scene; every frequent action is one or two taps away.
2. Shared truth over personal views: everyone in the house sees the same numbers.
3. Honest states: loading, empty, error and read-only are explained, never hidden.
4. Calm, not busy: the home is already noisy.

## Accessibility & Inclusion

Keyboard focus visible, reduced motion respected, touch targets sized for one-handed phone use, WCAG AA contrast.
