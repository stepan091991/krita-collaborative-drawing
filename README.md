# KritaTogether

[🇷🇺 Русская версия](README.ru.md)

A Krita plugin that enables real-time collaborative drawing on a shared canvas. Multiple users can work on the same document simultaneously, with synchronization of layers, pixel changes, and filter parameters over a local network or through a relay server.

## Features

- Real-time drawing synchronization with approximately 70 ms latency.
- Multi-layer document support: creation, deletion, renaming of layers, control of visibility, opacity, and blending mode.
- ~~Synchronization of filter layer parameters (for supported filter types).~~ Not stable!
- Two connection modes:
  - Direct TCP connection (when ports are reachable).
  - Through a relay server (for environments behind NAT).
- Password-based authentication to restrict access.
- Transmission of changed canvas regions only (dirty rectangles), reducing network load.

## Requirements

- Krita 5.2 or newer (stable release recommended).
- The Python interpreter bundled with Krita (no additional packages required).
- All dependencies are part of the Python standard library.

## Installation

1. Copy the `krita_together` directory into the Krita plugin folder:
   - Windows: `%APPDATA%\krita\pykrita\`
   - Linux: `~/.local/share/krita/pykrita/`
   - macOS: `~/Library/Application Support/krita/pykrita/`
2. Restart Krita.
3. Open **Settings → Configure Krita → Python Plugin Manager** and enable the **KritaTogether** plugin.
4. Restart Krita once more.

After activation, a **Shared Access...** entry will appear in the **Tools** menu, and a control panel will be available in the list of dockers.

## Usage

### Direct connection

1. Host: in the plugin panel, specify a port (default `50007`) and click **Create Session**.
2. Client: enter the host's IP address and the same port, then click **Connect**.
3. If a password is set, it must be identical on both sides.
4. After connecting, the client automatically creates a document with the host's parameters and requests a full synchronization.

### Connection through a relay server

1. Deploy the relay server on a machine with a public IP address:
   ```bash
   python3 relay_server.py
2. Open a single TCP port (default 50008) in the firewall.
3. In the plugin, switch to the Through Server tab and fill in the fields:
 - Server IP — the relay server address.
 - Port — the relay server port.
- Room token — an arbitrary string of at least 8 characters (a random token is recommended).
 - Password — the session password.
The host clicks Create Room, the client clicks Join Room.

The relay server does not store or analyze transmitted data; it only forwards bytes between participants.
