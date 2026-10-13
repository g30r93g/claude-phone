# Build notes

What it took to get each piece working on an Apple Silicon Mac (macOS 27), and why. `scripts/build-asterisk.sh`
and `asterisk/*.tmpl` already apply all of this; read it when something breaks.

## 1. Asterisk: native build (no Homebrew formula; Docker not needed)

Asterisk 22 LTS from https://downloads.asterisk.org, built against Homebrew's openssl@3. Each fix below was needed:

1. `./configure --with-jansson-bundled --with-pjproject-bundled PJPROJECT_CONFIGURE_OPTS="--with-ssl=$O" CPPFLAGS="-I$O/include" LDFLAGS="-L$O/lib"` with `O=/opt/homebrew/opt/openssl@3`.
2. **makeopts:** configure appends a bare `--with-ssl`, which pjproject reads as prefix "yes" and builds
   without TLS, so res_pjsip fails to load (`symbol not found: _pjsip_tls_transport_restart`).
   Rewrite the `PJPROJECT_CONFIGURE_OPTS` line with the real openssl path.
3. **main/Makefile:** upstream hard-codes `PJ_TARGET := aarch64-apple-darwin25.2.0`; it must match
   `aarch64-apple-darwin$(uname -r)` (the names in `third-party/pjproject/source/pjlib/lib/`).
4. **res/res_http_websocket.c:** macOS has no `TCP_KEEPIDLE`; define it as `TCP_KEEPALIVE`.
5. **menuselect:** disable res_geolocation and res_pjsip_geolocation (GNU-ld-only trick) and app_voicemail;
   enable res_mwi_external, res_mwi_external_ami and res_ari_mailboxes so ARI drives the message light.
6. `make -k install`: pjproject's install step fails trying `mkdir /opt/pjproject`. Harmless: it is
   statically linked into libasteriskpj.dylib.
7. **Regenerate docs** after a full build (`rm doc/core-en_US.xml && make doc/core-en_US.xml`, copy into
   `<astdatadir>/documentation/`). Without it Stasis fails to start ("Cannot update type
   'declined_message_types'… no existing documentation").
8. **astrundir must be a short path** (`/tmp/cphone`): macOS unix sockets are capped at 104 characters and
   a long path gives a misleading "Address already in use" on asterisk.ctl.
9. **RTP must be bound to IPv4** on every endpoint, or calls connect with no audio coming back
   ("RTCP RR transmission error … Invalid argument": macOS rejects IPv4 sendto on the default socket).
   Each endpoint gets `media_address=<Mac's IP>`, `bind_rtp_to_media_address=yes`, `rtp_ipv6=no`.
10. If pjproject needs reconfiguring, `touch third-party/pjproject/Makefile.rules`.

The first start after a build takes about 45 s while macOS scans the new libraries.

## 2. Typing into iTerm2: AppleScript

iTerm2's Python API isn't needed. Find the session by `unique id` (the part of `ITERM_SESSION_ID` after
the colon), `write text txt newline no`, wait 0.3 s, then send a carriage return. An idle Claude Code
session submits at once; a busy one queues the text until its turn ends. Answers are typed rather than
sent over Claude Code's cross-session messaging because they must arrive as genuine user turns.

## 3. Session identity

Hooks inherit the terminal's environment, so `ITERM_SESSION_ID` is visible to them. A stdio MCP server
receives `CLAUDE_CODE_SESSION_ID`, `ITERM_SESSION_ID` and `CLAUDE_PROJECT_DIR`, which is how a tool call
is tied to its tab. Tool calls carry no subagent id, hence the optional `from_agent` input.
The SessionEnd hook has a 1.5 s default timeout, so it is a single SQLite delete.

## 4. Timeouts

Claude Code moves MCP calls that run longer than 120 s to the background
(`CLAUDE_CODE_MCP_AUTO_BACKGROUND_MS`). The budget is ring 25 s + answer 60 s + transcription under 1 s.

## 5. Yealink T31P

- Remote phonebook XML: `<YealinkIPPhoneDirectory><DirectoryEntry><Name/><Telephone/></DirectoryEntry>`.
- Distinctive rings: `Alert-Info: <http://127.0.0.1>;info=Ring3`.
- Message light: with MWI subscription off (the default) the phone accepts unsolicited NOTIFY.
- Do Not Disturb rejects with 480; 480/486/603 are treated as "not answered".
- The screen shows 17 characters of caller ID before scrolling.

## 6. Speech

- **whisper.cpp** (`brew install whisper-cpp`): whisper-server keeps the model loaded. Live repo and branch
  names are passed as the prompt, or names like "lemon stand" come back as near-misses.
  large-v3-turbo matched or beat base.en on every real clip at about 0.3 s each; 8 kHz phone audio is fine.
- **Text to speech:** macOS `say` works out of the box (UK voices: Daniel, Shelley, Fiona…); ElevenLabs is optional.
