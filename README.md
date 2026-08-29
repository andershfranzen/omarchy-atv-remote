# Apple TV Remote for Omarchy

A native Omarchy bar panel backed by [pyatv](https://pyatv.dev/).

Dependencies are Python 3, `python-venv`, Avahi (`avahi-browse`), and the
[`pyatv`](https://pyatv.dev/) package installed by the pairing flow.

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

When tvOS focuses a search or login field, the panel detects it automatically
and switches to text-input mode. Printable keys and Space type directly into
the Apple TV field; Backspace deletes text. The normal remote mappings return
as soon as the field loses focus.

The panel can also be scripted with Omarchy Shell IPC, for example:

```bash
omarchy-shell anders.appletv-remote playPause
omarchy-shell anders.appletv-remote home
```

## Remove

```bash
omarchy plugin remove anders.appletv-remote
```

Omarchy removes the plugin itself. Pairing credentials in `~/.pyatv.conf` and
the isolated backend under `~/.local/share/omarchy/apple-tv-remote/` are left
in place intentionally so removal never deletes user data without consent.

## License

The plugin is MIT licensed. The bundled Siri Remote SVG is CC0; its source and
license notice are in `assets/LICENSE.txt`.
