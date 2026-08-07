# Agent Tower

A policy gateway between a business AI agent and every tool it can touch.

The agent has no direct tool access. Its only path out is `POST /gateway/execute`,
where a deterministic kernel tags data by origin, evaluates a gate rule, and
returns `ALLOW`, `NEED_APPROVAL`, or `DENY`. Uncertainty denies.

Design: `../docs/superpowers/specs/2026-08-06-agent-tower-design.md`

## Run

```bash
./run.sh          # http://localhost:8100
```
