# Researching your card with an AI assistant

The Cam Link EDID app only supports the **Cam Link 4K Rev.2** (USB ID `0FD9:007B`).
If you have a different revision, the app will refuse to change it, and it should.
Its commands were proven on one model only, and sending them to a different chip is guesswork.

Guesswork is also not needed. Everything this project learned is written down, and a capable AI assistant can use those notes to help you investigate **your own** card, step by step. This project was built that way: a person who is not an electronics engineer, working with an AI coding assistant under strict safety rules.

> [!WARNING]
> This is **research, not a one-click fix**. It can take hours. It may end with "not possible without extra hardware". A careless write can leave a card without picture until it is restored.
> Only continue if you are comfortable with that, and never skip the rules below.

## What an AI assistant is good and bad at here

| Good at | Bad at |
|---|---|
| Reading these docs and explaining them to you | Knowing your hardware without evidence |
| Decoding an EDID file and checking its sums | Guessing unknown commands (it will sound confident anyway) |
| Reading a USB capture and spotting repeated patterns | Telling a "locked" device from its own bug |
| Writing small read-only scripts | Stopping on its own when it is unsure |
| Keeping a log of what was tried and why | |

Ask it to label every claim as **verified**, **uncertain** or **hypothesis**, and to show its evidence.

## The rules

Give these to your assistant at the start. If it is a coding agent (Claude Code, Codex, Cursor and similar), save [templates/AGENT-RULES.md](templates/AGENT-RULES.md) in your working folder as `CLAUDE.md` or `AGENTS.md`, so it reads the rules automatically.

1. **Read-only first.** Never send anything to the card unless you have seen Elgato's own software send *exactly* that command, and it only reads.
2. **No firmware.** No firmware updates, flashing, resets or "mode" commands. Never use tools made for another Cam Link revision.
3. **You approve every write.** Before each write, the assistant states which bytes change, what the effect is and how to undo it. Then it waits for your "yes" to that one operation.
4. **Back up first.** Save the card's original EDID before any change, and keep a copy on a second drive or in the cloud.
5. **One small step at a time.** Start with a harmless test write, such as changing only the manufacture-week byte. Confirm it survives unplugging USB, then make the real change.
6. **Doubt your own code before blaming the device.** In this project, two swapped bytes in a message made every write silently fail. That looked exactly like "the firmware blocks writes". If something "doesn't work", recheck the message format against real captures before trying anything new.
7. **Stop when unsure.** No guessing formats and no trying random addresses. "We don't know yet" is a valid result.
8. **Keep a log** of every step, every piece of evidence and every decision.

## A plan that worked for the Rev.2

Adapt it for your card. Each step only continues if the previous one gave clear evidence.

1. **Identify the card.** Open Device Manager > Cameras > Cam Link 4K > Properties > Details > *Hardware Ids*. Note `VID_0FD9&PID_xxxx`. Compare it with the table in the [README](../README.md#i-have-a-different-cam-link).
2. **List what the card offers.** Read its USB descriptors with [Microsoft USBView](https://learn.microsoft.com/windows-hardware/drivers/debugger/usbview). The Rev.2 has a HID interface with a vendor usage page (`0xFFA0`). That is the "control channel".
3. **Watch Elgato's software.** Record USB traffic with Wireshark and USBPcap while Camera Hub runs normally. Do not start a firmware update. On the Rev.2, Camera Hub reads the EDID as 32 small HID requests of 8 bytes each, at address `0xA0`.
4. **Compare with the Rev.2 protocol** in [HOW-IT-WORKS.md](HOW-IT-WORKS.md). If your capture shows the same read requests, reading your EDID the same way is very likely safe.
5. **Read and back up your EDID.** Decode it, for example with `python camlink-edid.py decode your-file.bin`. Check whether there is an unused descriptor slot, and what pixel-clock limit the card declares.
6. **Plan the change offline.** Choose a free slot, a timing within the card's declared limits, and the correct checksum. Have a second tool or person check it.
7. **Write only with evidence for the write format,** which Elgato's software does not show during normal use. On the Rev.2 it came from analysing how Elgato's software builds its messages. Do a harmless test write first, unplug USB, read again, and only then do the real change.
8. **Test with the console**, then **share your result** in an issue so others benefit.

**A lead for the Rev.3 (`0FD9:00A1`):** Elgato's own library sends Rev.3 cards down the same EDID code path as Rev.2 cards. That is promising, but it is a hypothesis, not proof. Start at step 1 like everyone else.

## Starter prompt

Copy this into your assistant and fill in the brackets:

```text
I own an Elgato Cam Link 4K with USB ID 0FD9:[your PID]. I want my PS5 to offer 1440p at 60 Hz.

The open-source project https://github.com/why-so-savvy/camlink-edid solved this for the
Rev.2 (USB ID 0FD9:007B) by adding one detailed timing descriptor to the card's EDID.
Its docs/HOW-IT-WORKS.md describes the hardware and the HID protocol, and
docs/AI-ASSISTED-RESEARCH.md lists the safety rules.

Help me find out whether a similar approach can work for my card. Follow the safety rules
strictly: read-only first, nothing sent to the card that Elgato's own software does not send,
no firmware changes, and my explicit approval before any write. Label each claim as
verified, uncertain or hypothesis. Start by telling me what information you need from me.
```

## Sharing what you found

Open an issue with your USB ID, firmware version (shown in Camera Hub), what you tried and the result, even if it is "not possible".
Don't attach USB captures or logs from Elgato's software: they can contain your card's serial number. Describe the patterns instead.
