# BTA — Beyond

**Social media automation studio.** An automated AI TikTok Live streamer: it
reads your live chat, thinks and speaks with Gemini's native-audio Live API,
and animates a VTube Studio avatar in time with its own voice.

---

## The pipeline

```
TikTok Live chat          Director              Gemini Live API
 (TikTokLive)   ──────▶  filter, rate-limit ──▶ native audio out
                         batch, prioritize            │
                                                      │ 24 kHz PCM
                                                      ▼
                                              SpeechPlayer
                                          (real-time pacing)
                                              │           │
                          audio device ◀──────┘           └──────▶ lip-sync
                     (virtual cable → OBS)                         envelope
                                                                      │
                                                       VTube Studio ◀─┘
                                                    (parameter injection)
```

| Module | What it does |
|---|---|
| `bta/sources/tiktok.py` | Captures comments, gifts, follows and shares from a live room |
| `bta/director.py` | Decides what is worth reacting to — filtering, cooldowns, batching, idle chatter |
| `bta/brain/` | Gemini Live session: persona, native audio, reconnection, session resumption |
| `bta/audio/` | Real-time playback and the lip-sync envelope derived from the same frames |
| `bta/avatar/vtube.py` | VTube Studio API client: auth handshake and parameter injection |
| `bta/commerce.py` | Adapter onto `fulfillment/` — turns gifts and purchases into orders |
| `fulfillment/` | Order capture, inventory, fulfillment triggers (see its own README) |
| `bta/pipeline.py` | Wires it together and supervises every task |

### How lip sync actually works

The VTube Studio API accepts **numeric parameter values only — there is no
endpoint that takes audio.** So the avatar cannot be fed the voice stream
directly. Instead `SpeechPlayer` pulls one 20 ms frame at a time and hands it
to the sound device *and* the envelope follower in the same step, then pushes
the resulting `MouthOpen` / `MouthSmile` values over the API at 60 fps. Because
both come from the same frame at the same moment, the mouth matches what the
viewer hears.

---

## Setup

**1. Install**

```bash
python3 -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Audio playback needs the PortAudio system library:

| Platform | Command |
|---|---|
| macOS | `brew install portaudio` |
| Debian/Ubuntu | `sudo apt install libportaudio2` |
| Windows | already included with the `sounddevice` wheel |

Without it the app still runs and writes a `.wav` file instead.

**2. Configure**

```bash
cp .env.example .env
```

Only two values are required:

```ini
GEMINI_API_KEY=...        # https://aistudio.google.com/apikey
TIKTOK_HANDLE=@yourhandle
```

**3. Route the audio into your stream**

Install a virtual audio cable, then set `AUDIO_DEVICE` to it:

| Platform | Virtual cable |
|---|---|
| Windows | [VB-Audio Virtual Cable](https://vb-audio.com/Cable/) → `CABLE Input` |
| macOS | [BlackHole](https://existential.audio/blackhole/) → `BlackHole 2ch` |
| Linux | `pactl load-module module-null-sink sink_name=bta` |

```bash
python run.py --list-devices     # find the exact name
```

In OBS, add an **Audio Input Capture** source pointing at that cable.

**4. Check everything before going live**

```bash
python run.py --check
```

This verifies config, the audio device, TikTok reachability, the VTube Studio
handshake (your avatar's mouth will move) and a real Gemini Live round-trip.

---

## Running

```bash
python run.py                 # go live
python run.py --console       # rehearse with typed chat, no TikTok needed
python run.py --check         # preflight only
python run.py --no-vts        # voice only, no avatar
python run.py --list-devices  # audio outputs
```

`--console` is the fastest way to hear the voice and watch the avatar without
being live. Type `alice: what game is this?` and press Enter.

---

## Tuning

Everything below is optional and lives in `.env`.

| Setting | Effect |
|---|---|
| `GEMINI_VOICE` | `Puck`, `Charon`, `Kore`, `Fenrir`, `Aoede`, `Leda`, `Orus`, `Zephyr` |
| `PERSONA_NAME` / `PERSONA_EXTRA` | Who the streamer is and how it behaves |
| `PERSONA_FILE` | Longer character brief, loaded from a file |
| `DIRECTOR_MAX_BATCH` | How many chat messages get bundled into one response |
| `DIRECTOR_USER_COOLDOWN` | Seconds before the same viewer can trigger another reply |
| `DIRECTOR_IDLE_PROMPT_AFTER` | Seconds of silence before it speaks unprompted |
| `DIRECTOR_BLOCKED_WORDS` | Messages containing these are dropped entirely |
| `AUDIO_LIPSYNC_DELAY_MS` | Raise if the lips move *before* the voice is heard |
| `VTS_MOUTH_OPEN_PARAM` | Change if your model uses custom parameter names |

The model ID is left blank by default: the Live API model names are preview
builds that Google rotates, so the app tries a fallback list and uses whichever
one connects. Pin one with `GEMINI_MODEL` if you prefer.

---

## Staying on the right side of the platforms

Two accounts are at risk here: your TikTok account, and your Gemini API key.
Most of this is on by default, but the parts that need a human are listed at
the end.

**Turn on TikTok's AI-generated content label before you go live.** Undisclosed
synthetic media breaches TikTok's synthetic media policy. The app reminds you
at startup; `SAFETY_REMIND_AI_LABEL=false` silences it once it is habit.

**It will not reply faster than a human could read.** Every reply waits
`DIRECTOR_RESPONSE_DELAY_MIN`–`MAX` seconds (3–6 by default), randomized so
the cadence is not metronomic. Instant or perfectly regular replies are the
clearest spam-bot signal there is. `DIRECTOR_MAX_TURNS_PER_MINUTE` (8) is a
hard ceiling that also keeps you under Gemini's rate limits during a burst.

**It will not loop the same filler line.** Idle prompts rotate through the
whole set before repeating, and never fire twice in a row.

**Trolls are filtered before they reach Gemini.** `bta/safety.py` drops
prompt-injection attempts ("ignore all previous instructions", "developer
mode", "reveal your prompt") and a blocklist covering self-harm baiting,
sexual content, weapons and drug instructions, and hate framing. Simple
evasion — `k.y.s`, `kyyyys`, `k y s` — is normalized away. Bait that never
reaches the model is bait the model never has to refuse, which keeps your
provider safety metrics clean.

The default list is deliberately tight: filtering every mild swear would make
the stream lifeless, and a boring bot is its own kind of failure. Put slurs and
anything stream-specific in a `SAFETY_BLOCKLIST_FILE` rather than in the repo.

**The streamer gets cut off if it says something bad.** Native audio starts
playing before a full response exists, so there is no reviewing it first. The
transcript is checked as it arrives and playback is dropped mid-word if it
trips the list — turning a sentence the audience hears into a syllable. This
is a backstop, not the main defence; the inbound filter and the persona rules
are.

**Provider-side filtering is not yours to configure here.** A Live session
opened with a `GEMINI_API_KEY` has no safety-settings field — sending one is
rejected outright and the streamer never connects, so the app only sends
`SAFETY_HARM_BLOCK_THRESHOLD` when running against Vertex AI. Google still
filters server-side at its own default posture; you simply cannot tighten or
loosen it from a Developer API key. That is exactly why the guards above are
not decoration: on the documented setup, they are the filtering you control.

`python run.py --check` reports all of this, and actually fires injection and
bait probes through the guard rather than just saying it is configured.

### What still needs you

- **Toggle the TikTok AI label.** Nothing in the code can do this for you.
- **Watch your first few streams.** Do not walk away until you have seen how
  it handles a real chat, including a real troll. Run with `AUDIO_SINK=null`
  to watch transcripts in the log without broadcasting while you tune.
- **Read the log.** Dropped messages are logged with the reason, and an
  output cut is logged at ERROR. Both tell you whether your settings are too
  loose or too tight.

## Selling during a stream

Set `COMMERCE_ENABLED=true` and declare stock plus a gift mapping:

```ini
COMMERCE_STOCK=tee-blk-l:40
COMMERCE_SKU_NAMES=tee-blk-l:black tee
COMMERCE_GIFT_SKUS=Galaxy:tee-blk-l
```

Now a viewer sending a Galaxy claims a tee: stock is reserved, the order is
fulfilled (TikTok already took their money), and the streamer thanks them by
name. If it is sold out they hear a warm apology instead. Try it without going
live — `python run.py --console`, then `!buy alice: tee-blk-l x2`.

`bta/commerce.py` is the only place the two halves meet; `fulfillment/`
imports nothing from `bta/`, so both stay independently testable.

**A gift is not automatically a product.** Nothing is inferred — a gift places
an order only if you mapped it, because guessing would reserve real stock
against a joke.

### Variants go in the SKU

Each variant is its own SKU with its own stock line:

```ini
COMMERCE_STOCK=tee-blk-l:40,tee-blk-m:25
COMMERCE_SKU_NAMES=tee-blk-l:large black tee,tee-blk-m:medium black tee
COMMERCE_GIFT_SKUS=Galaxy:tee-blk-l,Rose:tee-blk-m
```

`tee-blk-l` and `tee-blk-m` are separate products; selling out of one leaves
the other untouched. The SKU is an opaque identifier — nothing parses it, so
any naming scheme works.

This falls out of a real constraint: a TikTok gift carries no size or colour,
so a gift can only ever claim one **fully-specified** SKU. There is no way for
a viewer to pick a size from chat. If you sell four sizes, that is four gifts
or four SKUs reachable another way.

Two things this makes worth doing:

- **Set `COMMERCE_SKU_NAMES`.** With variants in the SKU, an unnamed product
  gets read aloud as "tee blk l". Preflight warns about any you missed.
- **Run `python run.py --check`.** A gift mapped to a SKU that is not stocked
  is refused at startup rather than mid-stream — otherwise the typo only
  surfaces once a viewer has already spent money, and they are deliberately
  told nothing, because an unknown SKU is an operator fault rather than a
  stock-out.

Two behaviours worth setting deliberately:

- `COMMERCE_AUTO_FULFILL_GIFTS` (default on). Stock is two-phase: capture
  *reserves*, fulfil *depletes*. A gift is already paid for, so it is fulfilled
  at once. Turn this off and something must later fulfil or cancel each order,
  or the stock is held forever.
- `COMMERCE_RELEASE_HOLDS_ON_END` (default off). Decides whether a buyer whose
  stream dropped keeps their unit. There is no safe default, so it is explicit.

For an overlay or dashboard, subscribe rather than poll:

```python
pipeline.commerce.subscribe(lambda order, change: overlay.push(order))
```

## Development

```bash
pip install -r requirements-dev.txt
python -m pytest              # 302 tests, no network or API key needed
```

Tests run entirely offline (`tests/fulfillment/` belongs to the fulfillment
module). Do not add `tests/__init__.py` or a second `conftest.py` under
`tests/` — either one breaks the shared fixture imports.

`tools/mock_vts.py` is a stand-in VTube Studio server implementing the real
protocol — you can also run it directly to try the pipeline on a machine with
no VTube Studio installed:

```bash
python -m tools.mock_vts --port 8001 --verbose
```

---

## Behaviour worth knowing

- **Chat is filtered, not transcribed.** URLs, repeated-character spam, blocked
  words, duplicate lines and rapid-fire messages from one viewer are dropped
  before they ever reach the model.
- **It will not talk over itself.** A new turn only starts once the previous
  one has finished playing.
- **Prompt injection is expected.** Viewer messages are framed as data and the
  persona is told to ignore instructions coming from chat.
- **Long streams are handled.** Live sessions are time-limited, so the app
  keeps a session-resumption handle and reconnects transparently; context
  compression keeps a multi-hour stream from hitting the context limit.
- **A bad API key stops immediately** with a clear message rather than
  retrying forever. Network problems retry with backoff.

## Security

`.env` and `.vts_token` are gitignored. `TIKTOK_SESSION_ID`, if you set it, is
a login credential — treat it like a password.

---

## Roadmap

- [x] TikTok Live automated streaming engine
- [x] Gemini native-audio brain and voice
- [x] VTube Studio avatar animation
- [x] Order capture & fulfillment integration (`fulfillment/` + `bta/commerce.py`)
- [ ] Live product showcase & pinning
- [ ] Dashboard & scheduling UI
- [ ] Analytics & reporting

> **BTA** stands for *Beyond* — automation that goes beyond the manual grind.
