# How this project came together

## The problem

I capture my PS5 with an Elgato Cam Link 4K. It worked at 1080p60, but I wanted 1440p60: a sharper picture for my 1080p monitor, without AI upscaling.
The PS5 refused, saying the connected HDMI device did not support 1440p.

A first experiment showed the card was not the limit. A PC graphics card, using a Windows override (CRU) that adds a 1440p entry to the card's EDID as Windows sees it, sent 1440p60 through the same Cam Link, and the capture app received it.
So the hardware could do it. The PS5 simply wasn't being told.

## Constraints I set

- **No new hardware.** HDMI "EDID emulator" dongles exist, but the goal was to use what I had.
- **Safety first.** No firmware flashing without a proven way back. Every write to the card is approved separately, with a backup and an undo plan.
- **Evidence over guesses.** Every claim is labelled verified, uncertain or hypothesis, and decisions are logged.

## What I did

1. **Research and read-only checks.** I identified the exact model by USB ID (`0FD9:007B`, the "Rev.2", internally an ITE video chip plus a small Nuvoton microcontroller). I confirmed that existing community tools only covered the first-generation card.
2. **Offline analysis of the official firmware files.** These show that the microcontroller acts as the EDID memory the PS5 reads, and that it can store a new EDID permanently.
3. **Watching Elgato's own software.** A USB capture of Camera Hub revealed how it *reads* the EDID over a HID control channel: 32 requests of 8 bytes.
4. **Rebuilding the write message.** Camera Hub never writes the EDID of this card, so the format had to come from studying how Elgato's software library builds its messages.
5. **A detour.** The first write attempts had no effect. That looked like "the firmware blocks writes", so the card's microcontroller firmware was updated through Elgato's own updater. Still no effect.
6. **The real cause.** While tracing a different idea, it turned out two fields in our own message were swapped (`09 0A` instead of `0D 06`). The card had been politely rejecting every chunk all along. One corrected test write, which changed only the manufacture date, worked and survived unplugging.
7. **The real change.** I added a single 2560 × 1440 @ 59.95 Hz timing to an unused slot. The PS5 accepted 1440p60, and the capture app showed native 2560 × 1440 at 60 fps.

**Lesson:** when something "doesn't work", check your own assumptions before blaming the device. The "locked firmware" conclusion was wrong, and only careful re-checking against real captures revealed it.

## Turning it into a tool others can use

- **One shared, tested core** (`operations.py`), used by both the command line and the window.
- **Safety built in:**
  - the tool refuses any other model and any EDID it does not recognise;
  - it makes a verified backup first;
  - it checks every chunk while writing, and stops before the card commits anything;
  - it verifies after a power cycle.
- **Automated tests** against a simulated card that reproduces the real device's behaviour, including rejecting malformed messages.
- **Verified on real hardware:** a full remove-and-add round trip, with the PS5 confirmed afterwards.
- **A one-file Windows app,** built by GitHub from the public source with a build-provenance attestation, so anyone can check where it came from.

## How it was built

I am not an electronics engineer. I did this with an AI coding assistant (Claude Code), working under written safety rules: read-only research first, no unknown commands, and my explicit approval before every write.
The same rules are in [templates/AGENT-RULES.md](templates/AGENT-RULES.md), so owners of other Cam Link revisions can use the [same approach](AI-ASSISTED-RESEARCH.md).

## What's next

- Results from more Rev.2 cards, especially ones still on factory firmware.
- Support for the Rev.3, if its owners can collect the evidence. Elgato's library treats it like the Rev.2.
