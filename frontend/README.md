# Voice banking frontend

## Run locally

Copy `.env.example` to `.env.local`, then run `npm install` and `npm run dev` from `frontend/`.
The example includes the public ElevenLabs agent ID. Use localhost or HTTPS and allow
microphone access when prompted. This connection expects a public agent; an authenticated
agent requires a backend-issued conversation token. Never put an ElevenLabs API key in a
`VITE_` variable.

Voice sessions explicitly use the SDK's WebSocket transport so microphone capture and
the live volume meter use its browser Web Audio input pipeline.

## Microphone controls

- Tap **Talk** to connect. While listening, the rings expand with your microphone volume.
- Tap **Done talking** to mute your input and hand over the turn. ElevenLabs detects the
  resulting silence according to the agent's turn-taking settings; the tap does not force
  an immediate server response or disconnect the conversation.
- The microphone moves while waiting. During the reply, the rings follow the agent's audio.
- The mic opens again after the reply. Tap **Talk again** while waiting to resume input,
  or **Talk to interrupt** during the reply to open the mic and speak.
- Reduced-motion settings disable movement while retaining audio level feedback through opacity.

`VITE_USE_FAKE_API=true` keeps banking endpoints in demo mode even with a live voice agent.
For backend integration, set it to `false`, set `VITE_API_BASE` to the backend URL, and
configure the agent's MCP server to use that same backend's public `/mcp` endpoint.
Production builds load `.env.production`, which contains only the public agent ID,
the Render backend URL, and `VITE_USE_FAKE_API=false`. Keep these defaults in the repo
so moving hosting accounts does not silently switch the app into demo mode. Hosting
environment variables can override them; remove stale demo values from the new project.
Never add secret keys to this file. Restart Vite or rebuild after changing configuration.

Run `npm test`, `npm run build`, and `npm run lint` to verify changes.

## Vite toolchain

This template provides a minimal setup to get React working in Vite with HMR and some Oxlint rules.

Currently, two official plugins are available:

- [@vitejs/plugin-react](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react) uses [Oxc](https://oxc.rs)
- [@vitejs/plugin-react-swc](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react-swc) uses [SWC](https://swc.rs/)

## React Compiler

The React Compiler is not enabled on this template because of its impact on dev & build performances. To add it, see [this documentation](https://react.dev/learn/react-compiler/installation).

## Expanding the Oxlint configuration

If you are developing a production application, we recommend enabling type-aware lint rules by installing `oxlint-tsgolint` and editing `.oxlintrc.json`:

```json
{
  "$schema": "./node_modules/oxlint/configuration_schema.json",
  "plugins": ["react", "typescript", "oxc"],
  "options": {
    "typeAware": true
  },
  "rules": {
    "react/rules-of-hooks": "error",
    "react/only-export-components": ["warn", { "allowConstantExport": true }]
  }
}
```

See the [Oxlint rules documentation](https://oxc.rs/docs/guide/usage/linter/rules) for the full list of rules and categories.
