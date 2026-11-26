# Troubleshooting

Find the message you see, then follow its steps. If nothing helps, [open an issue](https://github.com/why-so-savvy/camlink-edid/issues/new/choose) and paste the text from the app's **Activity** box.

## Opening the app

**"Windows protected your PC"**
Click **More info**, then **Run anyway**. The app is not signed with a paid certificate.
To check the file first, see [Verify a download](BUILDING.md#verify-a-download).

**My antivirus deleted or blocked the file**
One-file Python apps are sometimes flagged by mistake. Check the file as described in [Verify a download](BUILDING.md#verify-a-download), then allow it in your antivirus.
Alternatively, [run the app from source](BUILDING.md#run-from-source), which uses no .exe.

**Nothing happens when I double-click**
Wait a few seconds: the first start unpacks the app. If still nothing appears, run it from source to see any error.

## Messages at the top of the window

**Connect your Cam Link**
No Cam Link was found. Plug it into a **USB 3** port, wait a few seconds and click **Refresh**.

**Can't read the card**
Usually Elgato Camera Hub, Elgato Studio or 4K Capture Utility is still running. Close it completely, including the icon next to the clock (check Task Manager if unsure), and click **Refresh**.
OBS and other capture apps can stay open.

**Connect it to a USB 3 port**
The card is running in USB 2 mode, where the app does not work and 1440p60 capture is not possible anyway. Use a USB 3 port (often blue) and a USB 3 cable. Avoid hubs.

**This Cam Link is not supported**
Your card is a different revision. The app will not change it. See [I have a different Cam Link](../README.md#i-have-a-different-cam-link).

**Custom EDID**
The slot this app uses already contains a different entry, perhaps from another tool. The app will not overwrite it. Use **Restore backup...** to go back to a known state.

**EDID not recognised**
The card's list is not valid. This can happen if USB was unplugged while writing. Unplug USB for 5 seconds, plug it back in and click **Refresh**. If the message stays, use **Restore backup...** and choose your oldest backup.

## While writing

**Nothing was written**
The app stopped before writing anything, so your card is unchanged. The message tells you why. For example, *"The card's EDID changed since this window opened"* means you should close the guide and click **Refresh**.

**Write stopped**
A safety check stopped the write. Usually nothing was stored: the card only saves after the last of 32 pieces.

1. Unplug USB for 5 seconds and plug it back in.
2. Click **Refresh** and look at the state.
3. If it is not what you expect, use **Restore backup...** with the file named in the message.

Please report it. It may be the first test of a new firmware version.

**Check after writing failed** or **Not stored as expected**
The card reports something other than what was written. Follow the same three steps as for *Write stopped*.

**I closed the guide before the USB check**
Nothing is wrong. Unplug USB for 5 seconds, plug it back in and click **Refresh** to confirm the state.

## After the change

**The PS5 still says 1440p is not supported**

1. In the app, check that the label next to 2560 × 1440 at 60 Hz says **Offered**.
2. Unplug and replug the HDMI cable, or restart the PS5, so it reads the list again.
3. On the PS5, go to Settings > Screen and Video > Video Output > Resolution and choose **1440p**.
4. Make sure HDCP is off: Settings > System > HDMI > Enable HDCP. Capture cards cannot capture HDCP-protected output.

**The capture app still shows 1920 × 1080**
In the capture app, open the Cam Link's properties and choose **2560 × 1440** at **60 FPS**. Also check that the PS5 really outputs 1440p.

**No picture at all**
Undo the change. It works without HDMI: open the app and click **Remove 1440p60**.

## Backups

Backups are saved in `C:\Users\<you>\camlink-edid-backups`. Each `.bin` file has a `.json` file next to it with its date and checksum.
The oldest file is the list your card had before you first used the app. Keep a copy of it somewhere safe.

## Command line

The command line (`python camlink-edid.py`) prints the same messages. Its exit codes:

| Code | Meaning |
|---|---|
| `0` | Success, or nothing to do |
| `1` | Stopped before writing: the card is unchanged |
| `2` | Problem during or after a write: follow the printed steps |
