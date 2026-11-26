# Troubleshooting

Exit code `1` always means the tool stopped **before** writing, so the card is unchanged. Exit code `2` means something went wrong during or after a write. Follow the printed steps and do not keep retrying.

## Messages

**"Another program is using the Cam Link control interface"**
Close Elgato Camera Hub, Elgato Studio and 4K Capture Utility, including their system-tray icons. Check Task Manager if you are unsure. Capture applications such as OBS normally use the video interface, not the control interface, so they do not block the tool.

**"No Cam Link 4K Rev.2 (USB 0FD9:007B) control interface found"**
Run `python camlink-edid.py detect`.
- If it shows `0FD9:0085`, the card is in USB 2 mode. Use a USB 3 port and cable.
- If it shows another USB ID, your card is a different revision and is not supported.
- If it shows nothing, check the cable and Device Manager.

**"two consecutive reads of the EDID differ"**
The USB connection is not stable. Try another port or cable, avoid hubs, and run `status` again. Nothing was written.

**"The card's current EDID is not one this tool recognises"**
- If a write was just interrupted, unplug USB for 5 seconds, plug it back in and run `status`.
- If another tool changed the EDID, put back a backup with `restore`. `add` deliberately refuses to modify an EDID it does not understand.

**"WRITE STOPPED at offset 0x.."**
A safety check stopped the write.
- If the message says it stopped **before the last chunk**, the stored EDID should be unchanged. Unplug USB for 5 seconds, plug it back in and run `status` to confirm.
- If the **last chunk** was involved, the card may have stored the new EDID. Run `status` after a replug, and `restore` your backup if the state is unexpected.

Please open an issue with the full output. This is exactly the kind of result we need from untested firmware.

**"VERIFICATION FAILED" or "not what was written"**
The card holds something other than what was written. Replug USB, run `status`, then restore the backup named in the output:

```powershell
python camlink-edid.py restore "C:\Users\<you>\camlink-edid-backups\camlink-edid-<date>-before-add.bin"
```

## The PS5 still says the device does not support 1440p

1. Run `status`. It must say "1440p60 mode present".
2. Unplug and replug the HDMI cable so that the PS5 reads the EDID again. Restarting the PS5 also works.
3. In Settings > Screen and Video > Video Output, try 1440p or Automatic.
4. Make sure HDCP is off (Settings > System > HDMI > Enable HDCP). Capture cards cannot record HDCP-protected output.

## The capture application still shows 1920x1080

Select the 2560x1440, 60 fps format in the application's device settings, and check that the PS5 is really outputting 1440p. The card only delivers 1440p when the source sends it.

## No picture at all after a change

Undo over USB. HDMI is not needed for that:

```powershell
python camlink-edid.py remove
```

## Where are my backups?

They are in `%USERPROFILE%\camlink-edid-backups`, unless you used `--backup-dir`. Each `.bin` file has a `.json` file next to it with its SHA-256, date and state. The oldest file is the EDID your card had before you first used the tool. Keep a copy of it somewhere else.
