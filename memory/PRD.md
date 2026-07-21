# SimpleDice — Product Requirements Document

## Original Problem Statement
> A crypto dice gambling site. I want it to look and feel like an archived website that I had to shutdown years ago called simpledice.com. Some other similar dice sites are windice.io, duckdice.com, trustdice.win.

User uploaded screenshots of the original SimpleDice.com — purple/lavender theme, 7-segment LED digital dice display (green for wins, red for losses), stat cards (multiplier / chance / payout), under/over toggles, chance slider, big ROLL button, bet amount pill controls, and tabs for RECENT / MY BETS / HIGH ROLLERS.

## User Personas
- **Casual player** — wants to roll fast, feel the win/loss dopamine, chat with others.
- **Provably-fair enthusiast** — wants to verify each roll (server seed hash / client seed / nonce) and rotate seeds.
- **Nostalgic returning user** — recognises the SimpleDice look from ~2013-2015 era.

## Core Requirements (static)
1. Provably-fair dice engine using HMAC-SHA256(server_seed, client_seed:nonce) → 0.00–99.99.
2. 1% house edge → payout multiplier = 99 / win_chance.
3. Play-money / demo balances (BTC, LTC, DOGE, ETH). No real crypto in MVP.
4. JWT-based auth (email + password + username).
5. Faucet endpoint with cooldown to top up demo coins.
6. Live-updating "All Bets" feed, personal bet history, high-rollers leaderboard.
7. Community chat sidebar.
8. Seed rotation UI showing hashed server seed, client seed, nonce, and previous-seed reveal.
9. UI matches the SimpleDice reference screenshots: purple header, white content panels with rounded corners, 7-segment LED display for the roll, stat pill cards, under/over buttons, slider, big roll button, bet amount pill.

## What's Been Implemented (Feb 2026)
- **Backend** (`/app/backend/server.py`):
  - JWT auth: `/api/auth/register`, `/api/auth/login`, `/api/auth/me`.
  - Dice engine: `POST /api/dice/roll` — provably fair, updates balance, saves bet.
  - Faucet: `POST /api/faucet/claim` (5 min cooldown).
  - Seeds: `POST /api/seeds/rotate` (reveals previous server_seed).
  - Bets: `GET /api/bets/all`, `/api/bets/mine`, `/api/bets/high-rollers`.
  - Chat: `GET /api/chat/messages`, `POST /api/chat/messages`.
  - Leaderboard: `GET /api/leaderboard`.
  - Config: `GET /api/config`.
- **Frontend** (React + Tailwind + shadcn):
  - `/` — Home dashboard: header, dice game, provably-fair panel, bets tabs table, chat sidebar.
  - `/login`, `/register`.
  - Custom 7-segment display using DS-Digital font w/ ghost "88.88" segments underneath.
  - Purple/lavender palette matching original SimpleDice screenshots.
  - Roll history strip, MULTIPLIER/CHANCE/PAYOUT cards, UNDER/OVER buttons, chance slider, ROLL button, +/- min/max bet pill.
  - Coin selector dropdown (BTC/LTC/DOGE/ETH) with per-coin balances.
  - Faucet button in header + user menu.
  - Live-updating bets tables (polls every 4s).
  - Chat sidebar with polling every 5s.
  - Provably-fair collapsible panel with rotate seeds action.

## Prioritised Backlog

### P0 (must-have for launch feel)
- [x] Core dice game + provably fair
- [x] Auth + balances + faucet
- [x] Live bet feed + chat
- [ ] End-to-end testing pass

### P1 (nice-to-have next)
- [ ] Auto-roll (currently placeholder button)
- [ ] Bonus/boost mode
- [ ] Leaderboards page (weekly / all-time)
- [ ] Sound effects on win/loss (toggleable)
- [ ] Tournaments (per screenshot #4 "RECHARGE / TOURNAMENTS")
- [ ] User profile page with wagered/profit stats
- [ ] Rain / tip other users in chat

### P2 (later)
- [ ] Real crypto wallet integration (deposits/withdrawals)
- [ ] Additional games (limbo, plinko, crash)
- [ ] Referral / affiliate system
- [ ] Mobile app / PWA polish

## Next Tasks
1. Run testing agent to validate the full backend + frontend flow.
2. Fix any critical issues from testing.
3. Iterate on user feedback re: exact SimpleDice look/feel details (colors, spacing, animations).
