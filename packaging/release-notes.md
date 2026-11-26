**Download `CamLinkEDID.exe` below**, then follow the [step-by-step guide](https://github.com/why-so-savvy/camlink-edid#step-by-step).

- Works only with the Elgato Cam Link 4K **Rev.2** (USB ID `0FD9:007B`). The app checks this for you.
- Windows may show "Windows protected your PC". Click **More info**, then **Run anyway**. The file is not signed with a paid certificate. GitHub built it from the public source code of this release.
- To check the file is genuine, compare its SHA-256 with `CamLinkEDID.exe.sha256`:

  ```powershell
  Get-FileHash .\CamLinkEDID.exe -Algorithm SHA256
  ```

  With the GitHub CLI you can also verify where it was built:
  `gh attestation verify CamLinkEDID.exe --repo why-so-savvy/camlink-edid`

See [CHANGELOG.md](https://github.com/why-so-savvy/camlink-edid/blob/main/CHANGELOG.md) for what changed.
