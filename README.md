# Paladin Laser Controller v1.2.0

A desktop controller for the Coherent Paladin Scan modelocked laser system. It turns the Rev. AA manual's RS-232 command set into a monitored dashboard, guarded laser/shutter controls, guided diagnostics, a searchable command reference, and a raw terminal for unusual cases.

The app includes a simulator. Use it to learn the workflow and verify the UI before connecting real equipment.

## Download for Windows 10 or 11

This is a standalone 64-bit Windows app. Python does not need to be installed.

1. Download [PaladinLaserController.exe](https://github.com/GauravTathed/Paladin-Laser-Controller/releases/latest/download/PaladinLaserController.exe) or the [Windows ZIP](https://github.com/GauravTathed/Paladin-Laser-Controller/releases/latest/download/Paladin-Door-Feed-Windows.zip).
2. Save the file, then double-click `PaladinLaserController.exe`.
3. For a safe first test, select **SIMULATOR**, leave the baud rate at **9600**, and click **Connect**.
4. For the real controller, connect the RS-232 adapter, click **Refresh**, select its COM port, and click **Connect**.

The executable is not digitally signed, so Windows SmartScreen may show an **Unknown publisher** warning. Confirm that the file came from this repository and, if desired, verify its SHA-256 checksum in PowerShell before selecting **More info > Run anyway**:

```powershell
Get-FileHash .\PaladinLaserController.exe -Algorithm SHA256
```

Compare the result with [SHA256SUMS.txt](https://github.com/GauravTathed/Paladin-Laser-Controller/releases/latest/download/SHA256SUMS.txt) from the same release.

This build is a 64-bit Windows GUI executable with a declared minimum Windows version of 6.0, so it is compatible with 64-bit Windows 10 and Windows 11. The app was packaged on Windows as a single file with PyInstaller and includes its Python runtime and dependencies.

## Safety boundary

This software is a convenience interface, not a safety system. The Paladin is a Class 4 laser. Hardware interlocks, the physical key switch, beam containment, approved eyewear, controlled-area procedures, and trained operators remain mandatory.

The app adds workflow guards but cannot prove that the optical area is safe:

- `L=1` is enabled only when the last reported operating state is `11` (Standby), as required by the manual.
- `S=1` is enabled only in state `8` (Normal operation) or `14` (Alignment mode ready).
- `?LF` entries are labeled as history rather than presented as an active fault; live power warnings still take precedence.
- The prominent safe-stop action sends `S=0` before `L=0`.
- Power changes are enabled only during state `11` (Standby) or `12` (Warm-up). The valid power range is model-specific and remains controller-enforced.
- Service, calibration, current, temperature, SBR-shift, `RESET`, and `GOON` writes are locked behind an expert-mode acknowledgement. The manual says not to directly change power-supply parameters unless directed by Coherent support.
- The dedicated SBR manager shows all reported spot conditions, refuses BAD/current/undocumented targets, checks USED-spot lifetime, confirms how the current spot will be marked, and verifies that the controller is already in Service Mode before sending `SHSBRTO` exactly once.
- SBR reads are sequential and a refresh stops on its first error. After any shift response, including undocumented status `73`, the app closes RS-232, invalidates queued polling, waits 10 seconds, reopens the same connection, and performs one read-only verification refresh. The shift command is never automatically retried.
- The documented shift protocol cannot assign the factory/unused `GOOD` state. It can mark the previous spot only `USED` (normal and reusable while below its lifetime) or `BAD`; the UI states this explicitly.
- Closing the program does not switch the laser off. If the last known shutter state is open, the app warns before exit.

## Controller connection

The operator's manual specifies:

| Setting | Value |
| --- | --- |
| Interface | RS-232, pins 2, 3, and 5 connected |
| Default baud | 9600 |
| Data bits | 8 |
| Parity | None |
| Stop bits | 1 |
| Command terminator | Carriage return (the app supplies it) |
| Minimum command spacing | 200 ms (the app uses 220 ms) |

Confirm the correct straight-through/crossover wiring for the actual controller and adapter in your lab before connection; the manual identifies the required pins but the app cannot inspect cable wiring.

## Run from source

Python 3.10 or newer is required. Tk is included in the normal Windows Python installer.

```powershell
cd C:\path\to\paladin-laser-controller
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\paladin-controller.exe
```

For a no-hardware trial, choose `SIMULATOR`, leave the baud rate at 9600, and click **Connect**.

You can also launch directly after installation:

```powershell
.\.venv\Scripts\python.exe .\run_paladin_controller.py
```

## Build a standalone Windows executable

The included script creates `dist\PaladinLaserController.exe` using PyInstaller:

```powershell
.\build_windows.ps1
```

Run the executable first with `SIMULATOR`. Windows may assign a different COM number when the USB-to-RS-232 adapter is moved to another port; use **Refresh** to rescan.

## App layout

- **Dashboard** - live state, readiness, diode, shutter, actual power, warnings, guarded controls, and power setpoint.
- **Diagnostics** - one-click identity, temperature, current, operating-hour, fault, monitoring, and settings queries.
- **SBR spots** - current spot and time, manual refresh, every spot's condition/hours/remaining lifetime, and a guarded move-to-specific-spot workflow.
- **Command guide** - the basic, service, power-control, current-mode, SBR, SHG, temperature, monitoring, and settings commands from the manual, searchable by plain language.
- **Terminal** - one-command-at-a-time fallback. Automatic status traffic can be shown for troubleshooting.

All commands are serialized in one worker thread so the UI stays responsive and the controller's 200 ms timing rule is respected. The app requests default prompt-off response mode (`>=0`) on connection and parses the documented `value:fault;` format, including optional echoed commands.

## QuDit Lab door display

Use [QuDit Lab door display v1.2.0](https://github.com/GauravTathed/DoorSignGUI/releases/tag/qudit-door-v1.2.0) or later on the Pi. In Paladin, enter `welcome-pi.local` or the Pi's IP address, SSH port `22`, and the Pi account username and password. Click **Connect to Pi**. The app verifies the Pi's host key before signing in. The password is cleared from the form and you enter it again when starting a new connection.

The Pi and COM port connections have separate controls. The app publishes confirmed `?S` responses while both are connected. The door switches to automatic status on the first valid hardware reading, shows **DANGER** when the shutter is open, and shows **UNKNOWN** when readings expire.

Choose **SIMULATOR**, click **Start laser**, then use **Open shutter** and **Close shutter** to test the sign. The door labels these readings **SIM OPEN** or **SIM CLOSED**. The simulator can show a test notice while the dashboard reports the real shutter off in manual mode. Real warnings take priority.

## Tests

The protocol and simulator tests use Python's standard library:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## Manual basis

Implemented against *Paladin Scan Modelocked Laser System Operator's Manual*, document `1298483`, Rev. AA. The source command tables are Section Six, pages 6-1 through 6-13; faults and system messages are in Section Seven, pages 7-1 through 7-5.
