# Apple TV Remote for Omarchy

A native Omarchy bar panel backed by [pyatv](https://pyatv.dev/).

## Install

```bash
omarchy plugin add https://github.com/andershfranzen/omarchy-atv-remote --enable
```

The widget is added to the Omarchy bar. Open its remote icon to continue.

## Pair

1. Open the remote icon and choose **Install and pair Apple TV**. The setup terminal
   installs `pyatv` into a private virtual environment under
   `~/.local/share/omarchy/apple-tv-remote/` and starts its pairing wizard. The
   computer and Apple TV must be on the same network.

2. All Apple TVs discovered on the local network appear at the top of the
   panel. Select one to make it the active target. You can pair and switch
   between any number of devices.

Pairing credentials are stored by pyatv in `~/.pyatv.conf`.

## Keyboard remote

Open the pop-out and use:

- Arrow keys — navigate
- Enter — select
- Backspace — back/menu
- Space — play/pause
- `H` — home
- `+` / `-` — volume
- Escape — close the remote

The panel displays each keystroke and the action sent to Apple TV. It maintains
a persistent Companion connection, so repeated navigation commands do not
reconnect for every keypress.

The panel can also be scripted with Omarchy Shell IPC, for example:

```bash
omarchy-shell anders.appletv-remote playPause
omarchy-shell anders.appletv-remote home
```
