import socket
import threading
import time
import secrets

HOST = "0.0.0.0"
PORT = 50008
MAX_ROOMS = 100
MAX_HANDSHAKE = 256
SOCKET_TIMEOUT = 60 * 60  # 1 час

rooms = {}
lock = threading.Lock()


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def safe_close(sock):
    try:
        sock.close()
    except Exception:
        pass


def bridge(sock1, sock2):
    """Перекидывает байты между двумя сокетами, пока один не закроется."""

    def forward(src, dst):
        try:
            while True:
                data = src.recv(65536)
                if not data:
                    break
                dst.sendall(data)
        except Exception:
            pass
        finally:
            safe_close(src)
            safe_close(dst)

    t1 = threading.Thread(target=forward, args=(sock1, sock2), daemon=True)
    t2 = threading.Thread(target=forward, args=(sock2, sock1), daemon=True)
    t1.start()
    t2.start()
    t1.join()
    t2.join()


def handle_client(conn, addr):
    conn.settimeout(SOCKET_TIMEOUT)
    handed_off = False
    try:
        # --- Рукопожатие ---
        raw = b""
        while b"\n" not in raw and len(raw) < MAX_HANDSHAKE:
            chunk = conn.recv(MAX_HANDSHAKE - len(raw))
            if not chunk:
                return
            raw += chunk

        if b"\n" not in raw:
            conn.sendall(b"ERROR:Bad handshake\n")
            return

        line = raw.split(b"\n", 1)[0].decode("utf-8", errors="ignore").strip()
        if ":" not in line:
            conn.sendall(b"ERROR:Bad handshake\n")
            return

        role, room_token = line.split(":", 1)
        role = role.upper()
        room_token = room_token.strip()

        if role not in ("HOST", "JOIN"):
            conn.sendall(b"ERROR:Bad role\n")
            return

        if len(room_token) < 8 or len(room_token) > 128:
            conn.sendall(b"ERROR:Bad room token\n")
            return

        # ================== HOST ==================
        if role == "HOST":
            with lock:
                if room_token in rooms:
                    conn.sendall(b"ERROR:Room exists\n")
                    return
                if len(rooms) >= MAX_ROOMS:
                    conn.sendall(b"ERROR:Server busy\n")
                    return
                ev = threading.Event()
                rooms[room_token] = {"host": conn, "client": None, "event": ev}

            conn.sendall(b"OK:Waiting for client\n")
            log(f"HOST {addr} created room {room_token[:6]}...")

            # Ждём, пока клиент зайдёт (или таймаут)
            ev.wait(timeout=SOCKET_TIMEOUT)

            with lock:
                room = rooms.get(room_token)
                if not room or room["client"] is None:
                    if room:
                        del rooms[room_token]
                    log(f"HOST {addr} room {room_token[:6]} aborted/timeout")
                    return
                client_conn = room["client"]
                del rooms[room_token]

            log(f"Room {room_token[:6]} bridged. Starting transfer...")
            handed_off = True  # сокеты теперь принадлежат bridge, finally не закрываем
            bridge(conn, client_conn)
            log(f"Room {room_token[:6]} closed")
            return

        # ================== JOIN ==================
        if role == "JOIN":
            with lock:
                room = rooms.get(room_token)
                if not room:
                    conn.sendall(b"ERROR:Room not found\n")
                    return
                if room["client"] is not None:
                    conn.sendall(b"ERROR:Room is full\n")
                    return
                room["client"] = conn
                conn.sendall(b"OK:Connected to host\n")
                room["event"].set()  # будим HOST-поток

            log(f"JOIN {addr} joined room {room_token[:6]}...")

            # Наш сокет теперь обслуживается bridge в HOST-потоке.
            # Мы не должны его закрывать — просто ждём, пока bridge его закроет.
            handed_off = True
            try:
                while True:
                    time.sleep(2)
                    if conn.fileno() == -1:
                        break
            except Exception:
                pass
            return

    except Exception as e:
        log(f"Client {addr} error: {e}")
    finally:
        if not handed_off:
            safe_close(conn)


def main():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, PORT))
    server.listen(50)
    log(f"Relay server listening on {HOST}:{PORT}")
    log("Rooms are in-memory only. Restart clears everything.")

    while True:
        conn, addr = server.accept()
        threading.Thread(target=handle_client, args=(conn, addr), daemon=True).start()


if __name__ == "__main__":
    main()